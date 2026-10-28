#!/usr/bin/env python3
"""Check the local Grav site against the crawled source, route by route.

Usage:
  verify_parity.py migration --local http://127.0.0.1:8000 [--min-coverage 0.95] [--routes /a,/b]
                   [--expect-noindex] [--workers 6]

Per route: HTTP 200, exact <title>, meta description, source text coverage (share of extracted
source text blocks found in the local page), image count, forms present, no links/assets still
pointing at the source origin, <html lang>, hreflang alternates, and (with --expect-noindex) that
local responses carry noindex and load no analytics. Also replays source redirects.
Writes migration/parity-report.json and parity-report.md; exits 1 when any route fails.
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from htmlkit import normalize_space, parse_html, read_json, site_key, write_json  # noqa: E402

ANALYTICS = re.compile(r"googletagmanager\.com/gtm\.js|gtag/js\?id=|connect\.facebook\.net|hs-scripts\.com|static\.hotjar\.com|cdn\.heapanalytics|clarity\.ms/tag|plausible\.io/js", re.I)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fetch(url: str, follow: bool = True):
    opener = urllib.request.build_opener() if follow else urllib.request.build_opener(NoRedirect)
    try:
        response = opener.open(urllib.request.Request(url, headers={"User-Agent": "anysite2grav-verify"}), timeout=60)
        return response.status, dict(response.headers), response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read().decode("utf-8", errors="replace") if error.fp else ""
    except Exception as error:  # noqa: BLE001
        return 0, {}, str(error)


def comparable(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = re.sub(r"[\u200b-\u200d\u2060\ufeff\u00ad]", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text).replace("**", "").replace("*", "")
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", text).strip().lower()


def check_route(route: str, record: dict, page: dict, args, source_site: str) -> dict:
    url = args.local.rstrip("/") + route
    status, headers, markup = fetch(url, follow=False)
    result = {"route": route, "status": status, "problems": [], "warnings": []}
    if status != 200:
        location = headers.get("Location", "")
        hint = " (fresh Grav redirects to Admin until an account exists: run bootstrap_access.sh)" if "/admin" in location else ""
        result["problems"].append(f"HTTP {status}{' → ' + location if location else ''}{hint}")
        return result
    document = parse_html(markup)
    title = document.find("title")
    local_title = normalize_space(title.text()) if title else ""
    if record.get("title") and comparable(local_title) != comparable(record["title"]):
        result["problems"].append(f"title “{local_title}” ≠ source “{record['title']}”")
    description = next((meta.get("content") for meta in document.find_all("meta") if meta.get("name").lower() == "description"), None)
    if record.get("description") and comparable(description or "") != comparable(record["description"]):
        result["warnings"].append("meta description differs")
    body = document.find("body") or document
    local_text = comparable(body.text())
    texts = [comparable(text) for text in record.get("texts", []) if len(comparable(text)) >= 3]
    found = [text for text in texts if text in local_text]
    coverage = len(found) / len(texts) if texts else 1.0
    result["coverage"] = round(coverage, 3)
    if coverage < args.min_coverage:
        missing = [text for text in texts if text not in local_text][:5]
        result["problems"].append(f"text coverage {coverage:.0%} < {args.min_coverage:.0%}; missing e.g. {missing}")
    images = len(document.find_all("img")) + markup.count("--section-background") + len(document.find_all("video"))
    expected_images = len(record.get("media", []))
    result["images"] = f"{images}/{expected_images}"
    if expected_images and images < expected_images * 0.8:
        result["warnings"].append(f"only {images} images/videos for {expected_images} source media")
    if record.get("forms") and not document.find("form"):
        result["problems"].append(f"source forms {record['forms']} not rendered")
    leftovers = sorted({value for node in document.iter() for attribute in ("href", "src", "poster") if (value := node.get(attribute)) and site_key(urlsplit(value).hostname or "") == source_site})
    cdn_leftovers = sorted({value for node in document.iter() for attribute in ("src", "poster", "srcset") if (value := node.get(attribute)) and re.search(r"website-files\.com|wixstatic|squarespace-cdn|framerusercontent", value)})
    if leftovers:
        result["warnings"].append(f"{len(leftovers)} links still point at the source origin, e.g. {leftovers[:3]}")
    if cdn_leftovers:
        result["problems"].append(f"{len(cdn_leftovers)} assets still load from the source CDN, e.g. {cdn_leftovers[:2]}")
    html_tag = document.find("html")
    if record.get("lang") and html_tag is not None and html_tag.get("lang", "").split("-")[0] != record["lang"]:
        result["problems"].append(f"html lang {html_tag.get('lang')} ≠ {record['lang']}")
    if len(record.get("hreflang", [])) > 1 and not any(link.get("hreflang") for link in document.find_all("link")):
        result["warnings"].append("source has hreflang alternates; local has none")
    if args.expect_noindex:
        robots = " ".join(meta.get("content") for meta in document.find_all("meta") if meta.get("name").lower() == "robots") + " " + headers.get("X-Robots-Tag", "")
        if "noindex" not in robots.lower():
            result["problems"].append("local/preview response is indexable (missing noindex)")
        if ANALYTICS.search(markup):
            result["problems"].append("analytics loads on a local/preview host")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("migration", nargs="?", default="migration")
    parser.add_argument("--local", required=True)
    parser.add_argument("--min-coverage", type=float, default=0.95)
    parser.add_argument("--routes")
    parser.add_argument("--expect-noindex", action="store_true")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    migration = Path(args.migration)
    routes = read_json(migration / "routes.json")
    index = read_json(migration / "content-index.json")
    page_map = read_json(migration / "page-map.json")["pages"] if (migration / "page-map.json").exists() else {}
    source_site = site_key(urlsplit(routes["source"]).hostname or "")
    records = {item["route"]: read_json(migration / item["file"]) for item in index["pages"]}
    wanted = args.routes.split(",") if args.routes else sorted(records)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda route: check_route(route, records[route], page_map.get(route, {}), args, source_site), wanted))

    redirect_results = []
    for redirect in read_json(migration / "redirects.json") if (migration / "redirects.json").exists() and not args.routes else []:
        status, headers, _ = fetch(args.local.rstrip("/") + redirect["from"], follow=False)
        location = headers.get("Location", "")
        ok = status in (301, 302, 303, 307, 308) and urlsplit(location).path.rstrip("/") == redirect["to"].rstrip("/")
        redirect_results.append({**redirect, "local_status": status, "location": location, "ok": ok})

    failed = [result for result in results if result["problems"]]
    coverage = [result["coverage"] for result in results if "coverage" in result]
    summary = {
        "routes": len(results),
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "average_text_coverage": round(sum(coverage) / len(coverage), 3) if coverage else None,
        "redirects_ok": sum(1 for result in redirect_results if result["ok"]),
        "redirects_total": len(redirect_results),
    }
    write_json(migration / "parity-report.json", {"summary": summary, "routes": results, "redirects": redirect_results})
    lines = [f"# Parity report — {summary['passed']}/{summary['routes']} routes pass", "",
             f"Average text coverage {summary['average_text_coverage']:.1%}; redirects {summary['redirects_ok']}/{summary['redirects_total']}." if coverage else "", "",
             "| Route | Status | Coverage | Images | Problems | Warnings |", "| --- | --- | --- | --- | --- | --- |"]
    for result in sorted(results, key=lambda item: (not item["problems"], item["route"])):
        lines.append(f"| `{result['route']}` | {result['status']} | {result.get('coverage', '—')} | {result.get('images', '—')} | {'; '.join(result['problems']).replace('|', '/') or '✓'} | {'; '.join(result['warnings']).replace('|', '/')} |")
    for redirect in redirect_results:
        if not redirect["ok"]:
            lines.append(f"\nRedirect `{redirect['from']}` → `{redirect['to']}` failed (got {redirect['local_status']} {redirect['location']})")
    (migration / "parity-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{summary['passed']}/{summary['routes']} routes pass; avg coverage {summary['average_text_coverage']}; redirects {summary['redirects_ok']}/{summary['redirects_total']} → {migration / 'parity-report.md'}")
    for result in failed[:15]:
        print(f"  FAIL {result['route']}: {'; '.join(result['problems'])[:300]}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
