#!/usr/bin/env python3
"""Discover every public route of a live site and cache its HTML.

Seeds from robots.txt sitemaps and sitemap.xml (when present), then runs a
bounded same-site crawl, because many hosted builders (Webflow, Squarespace)
omit pages from the sitemap or publish none at all.

Usage:
  crawl_site.py https://example.com --out migration [--max-pages 1500] [--workers 4]
                [--alias www.example.com] [--keep-query page] [--exclude '^/blog/tag/']
                [--include '^/(about|pricing)?$'] [--max-depth 1] [--no-sitemaps]

Writes:
  <out>/routes.json   route inventory (status, redirects, lang, hreflang, meta, links)
  <out>/html/*.html   raw HTML per route, consumed by audit/extract scripts
  <out>/redirects.json source redirects worth recreating as Grav redirects
"""

from __future__ import annotations

import argparse
import gzip
import random
import re
import string
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent))
from htmlkit import (  # noqa: E402
    DOCUMENT_EXTENSIONS, html_cache_name, is_asset_url, meta_content, normalize_space,
    normalize_url, parse_html, route_of, short_hash, site_key, write_json,
)

ASSET_CDN = re.compile(r"website-files\.com|squarespace-cdn\.com|static\d*\.squarespace\.com|wixstatic\.com|framerusercontent\.com|cdn\.shopify\.com|amazonaws\.com|cloudfront\.net|googleusercontent\.com")
USER_AGENT = "Mozilla/5.0 (compatible; anysite2grav/1.0; +https://getgrav.org)"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def fetch(url: str, *, timeout: int = 30, max_redirects: int = 8):
    """GET with manual redirect handling so the redirect chain is recorded."""
    chain = []
    current = url
    for _ in range(max_redirects + 1):
        request = urllib.request.Request(current, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"})
        try:
            response = OPENER.open(request, timeout=timeout)
            status = response.status
            headers = response.headers
            body = response.read()
        except urllib.error.HTTPError as error:
            status, headers, body = error.code, error.headers, error.read() if error.fp else b""
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            return {"url": current, "status": 0, "error": str(error), "chain": chain, "headers": {}, "body": b""}
        if status in (301, 302, 303, 307, 308) and headers.get("Location"):
            # Follow the raw Location: normalizing it (e.g. stripping a trailing slash) can loop
            # forever on servers that redirect /about → /about/. The chain records the normalized form.
            raw_target = urljoin(current, headers["Location"].strip())
            target = normalize_url(raw_target, current, keep_query=True)
            chain.append({"from": current, "to": target, "status": status})
            if not target or raw_target == current:
                break
            current = raw_target
            continue
        if headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
        return {"url": current, "status": status, "chain": chain, "headers": dict(headers), "body": body}
    return {"url": current, "status": 0, "error": "too many redirects", "chain": chain, "headers": {}, "body": b""}


def decode(body: bytes, headers: dict) -> str:
    charset = "utf-8"
    match = re.search(r"charset=([\w-]+)", headers.get("Content-Type", ""), re.I)
    if match:
        charset = match.group(1)
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def sitemap_urls(origin: str, robots_sitemaps: list[str]) -> tuple[list[str], list[str]]:
    """Return (page urls, sitemap files read). Follows sitemap indexes."""
    queue = list(dict.fromkeys(robots_sitemaps + [f"{origin}/sitemap.xml", f"{origin}/sitemap_index.xml"]))
    seen, pages, read = set(), [], []
    while queue:
        sitemap = queue.pop(0)
        if sitemap in seen:
            continue
        seen.add(sitemap)
        result = fetch(sitemap)
        if result["status"] != 200 or not result["body"]:
            continue
        body = result["body"]
        if sitemap.endswith(".gz") and body[:2] == b"\x1f\x8b":
            body = gzip.decompress(body)
        text = body.decode("utf-8", errors="replace")
        if "<urlset" not in text and "<sitemapindex" not in text:
            continue
        read.append(sitemap)
        locations = [normalize_space(location) for location in re.findall(r"<loc>\s*(.*?)\s*</loc>", text, re.S)]
        if "<sitemapindex" in text:
            queue.extend(locations)
        else:
            pages.extend(locations)
    return pages, read


def page_record(url: str, result: dict, markup: str, site: str, keep_query: set[str]) -> dict:
    document = parse_html(markup)
    html_tag = document.find("html")
    title = document.find("title")
    heading = document.find("h1")
    canonical = next((link.get("href") for link in document.find_all("link") if "canonical" in link.get("rel").lower().split()), None)
    alternates = [
        {"hreflang": link.get("hreflang"), "href": normalize_url(link.get("href"), url)}
        for link in document.find_all("link")
        if "alternate" in link.get("rel").lower().split() and link.get("hreflang")
    ]
    links, documents = set(), set()
    for anchor in document.find_all("a", "area"):
        absolute = normalize_url(anchor.get("href"), url, keep_query=True)
        if not absolute:
            continue
        host = site_key(urlsplit(absolute).hostname or "")
        # Builders host uploaded PDFs on their asset CDN, not the site domain.
        if DOCUMENT_EXTENSIONS.search(urlsplit(absolute).path) and (host == site or ASSET_CDN.search(host)):
            documents.add(absolute)
            continue
        if host != site:
            continue
        if is_asset_url(absolute):
            continue
        links.add(strip_query(absolute, keep_query))
    robots = (meta_content(document, name="robots") or "") + " " + result["headers"].get("X-Robots-Tag", "")
    return {
        "url": url,
        "route": route_of(url),
        "status": result["status"],
        "redirect_chain": result["chain"],
        "content_type": result["headers"].get("Content-Type", ""),
        "lang": (html_tag.get("lang") if html_tag else "") or None,
        "title": normalize_space(title.text()) if title else None,
        "h1": normalize_space(heading.text()) if heading else None,
        "description": meta_content(document, name="description"),
        "canonical": normalize_url(canonical, url) if canonical else None,
        "noindex": "noindex" in robots.lower(),
        "hreflang": alternates,
        "og": {
            key: meta_content(document, prop=f"og:{key}")
            for key in ("title", "description", "image", "type")
            if meta_content(document, prop=f"og:{key}")
        },
        "generator": meta_content(document, name="generator"),
        "fingerprint": short_hash((normalize_space(title.text()) if title else "") + "|" + (normalize_space(heading.text()) if heading else "")),
        "links": sorted(links),
        "documents": sorted(documents),
    }


def strip_query(url: str, keep: set[str]) -> str:
    parts = urlsplit(url)
    kept = [(key, value) for key, value in parse_qsl(parts.query) if key in keep or any(key.endswith(suffix) for suffix in keep)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), ""))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("url")
    parser.add_argument("--out", default="migration")
    parser.add_argument("--max-pages", type=int, default=1500)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--delay", type=float, default=0.1, help="seconds between requests per worker")
    parser.add_argument("--alias", action="append", default=[], help="extra hostnames that belong to the same site")
    parser.add_argument("--keep-query", action="append", default=[], help="query keys to keep (e.g. pagination like page or _page suffix)")
    parser.add_argument("--exclude", action="append", default=[], help="regex of routes to skip")
    parser.add_argument("--include", action="append", default=[], help="regex of routes to keep (allow-list); the start URL is always kept")
    parser.add_argument("--max-depth", type=int, default=None, help="stop following links this many clicks from the start page")
    parser.add_argument("--no-sitemaps", action="store_true", help="don't seed from sitemaps (scoped crawls: menu pages only, one section)")
    args = parser.parse_args()

    start = normalize_url(args.url, args.url)
    origin_parts = urlsplit(start)
    origin = f"{origin_parts.scheme}://{origin_parts.netloc}"
    site = site_key(origin_parts.hostname or "")
    sites = {site, *(site_key(alias) for alias in args.alias)}
    keep_query = set(args.keep_query)
    excludes = [re.compile(pattern) for pattern in args.exclude]
    includes = [re.compile(pattern) for pattern in args.include]

    def wanted(url: str) -> bool:
        route = route_of(url)
        if any(pattern.search(route) for pattern in excludes):
            return False
        return not includes or any(pattern.search(route) for pattern in includes)
    out = Path(args.out)
    (out / "html").mkdir(parents=True, exist_ok=True)

    robots = fetch(f"{origin}/robots.txt")
    robots_text = decode(robots["body"], robots["headers"]) if robots["status"] == 200 else ""
    robots_sitemaps = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots_text)
    from_sitemap, sitemap_files = ([], []) if args.no_sitemaps else sitemap_urls(origin, robots_sitemaps)

    # A random path reveals soft-404 pages that answer 200 (common on site builders).
    probe_path = "/" + "".join(random.choices(string.ascii_lowercase, k=18))
    probe = fetch(origin + probe_path)
    probe_record = page_record(origin + probe_path, probe, decode(probe["body"], probe["headers"]), site, keep_query) if probe["body"] else None

    queue = [start] + [normalize_url(url, origin, keep_query=True) for url in from_sitemap]
    queue = [strip_query(url, keep_query) for url in queue if url]
    queue = queue[:1] + [url for url in queue[1:] if wanted(url)]
    queued = set(queue)
    depth = {url: 0 for url in queue}
    sitemap_routes = {route_of(url) for url in queue[1:]}
    records: dict[str, dict] = {}
    canonical_hosts = set()

    def crawl(url: str):
        time.sleep(args.delay)
        result = fetch(url)
        content_type = result["headers"].get("Content-Type", "")
        record = {"requested": url, "status": result["status"], "redirect_chain": result["chain"], "error": result.get("error")}
        if result["status"] == 200 and "html" in content_type:
            markup = decode(result["body"], result["headers"])
            record = {**page_record(result["url"], result, markup, site, keep_query), "requested": url}
            cache = out / "html" / html_cache_name(record["route"])
            cache.write_text(markup, encoding="utf-8")
            record["html_file"] = str(cache.relative_to(out))
        return record

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        while queue and len(records) < args.max_pages:
            batch, queue = queue[: args.workers * 4], queue[args.workers * 4:]
            for record in pool.map(crawl, batch):
                final_host = site_key(urlsplit(record.get("url") or record["requested"]).hostname or "")
                if final_host not in sites:
                    record["offsite"] = True
                canonical_hosts.add(urlsplit(record.get("url") or record["requested"]).netloc)
                key = record.get("url") or record["requested"]
                records[key] = record
                record["in_sitemap"] = route_of(record["requested"]) in sitemap_routes
                if probe_record and record.get("fingerprint") == probe_record["fingerprint"] and record.get("route") != "/":
                    record["soft_404"] = True
                next_depth = depth.get(record["requested"], 0) + 1
                if args.max_depth is not None and next_depth > args.max_depth:
                    continue
                for link in record.get("links", []):
                    host = site_key(urlsplit(link).hostname or "")
                    if host not in sites or link in queued or not wanted(link):
                        continue
                    queued.add(link)
                    depth[link] = next_depth
                    queue.append(link)
            print(f"crawled {len(records)} / queued {len(queue)}", file=sys.stderr)

    pages, redirects, broken, documents = [], [], [], set()
    seen_routes = set()
    for record in records.values():
        if record.get("redirect_chain"):
            first, last = record["redirect_chain"][0], record["redirect_chain"][-1]
            if site_key(urlsplit(first["from"]).hostname or "") in sites and route_of(first["from"]) != route_of(last["to"] or ""):
                redirects.append({"from": route_of(first["from"]), "to": route_of(last["to"]) if site_key(urlsplit(last["to"] or "").hostname or "") in sites else last["to"], "status": first["status"]})
        if record.get("status") != 200:
            broken.append({"url": record["requested"], "status": record.get("status"), "error": record.get("error")})
            continue
        if record.get("soft_404") or record.get("offsite") or "route" not in record:
            continue
        if record["route"] in seen_routes:
            continue
        seen_routes.add(record["route"])
        documents.update(record.get("documents", []))
        pages.append(record)

    pages.sort(key=lambda page: page["route"])
    languages = sorted({(page.get("lang") or "").split("-")[0].lower() for page in pages if page.get("lang")})
    write_json(out / "routes.json", {
        "source": origin,
        "crawled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "robots_txt": robots_text,
        "sitemaps_read": sitemap_files,
        "sitemap_page_count": len(sitemap_routes),
        "soft_404_probe": {"path": probe_path, "status": probe["status"], "fingerprint": probe_record and probe_record["fingerprint"]},
        "languages": languages,
        "hosts_seen": sorted(canonical_hosts),
        "page_count": len(pages),
        "pages": pages,
        "documents": sorted(documents),
        "broken": broken,
        "truncated": bool(queue),
    })
    write_json(out / "redirects.json", sorted({(r["from"], r["to"]): r for r in redirects}.values(), key=lambda r: r["from"]))
    not_in_sitemap = [page["route"] for page in pages if not page.get("in_sitemap")]
    print(
        f"{len(pages)} routes ({len(sitemap_routes)} listed in sitemaps, {len(not_in_sitemap)} found only by crawling), "
        f"{len(redirects)} redirects, {len(broken)} broken, {len(documents)} documents, languages={languages or ['?']}"
        + (" — TRUNCATED: raise --max-pages" if queue else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
