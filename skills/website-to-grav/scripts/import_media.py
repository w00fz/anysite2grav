#!/usr/bin/env python3
"""Download every referenced asset once, dedupe by content hash, and assign a Grav home.

Usage:
  import_media.py migration [--workers 8]

Reads content/*.json, chrome.json, shared-sections.json and routes.json documents.
Writes:
  media-cache/<sha>-<name>.<ext>   downloaded originals (one file per unique byte content)
  media-manifest.json              url → {file, sha256, bytes, scope, routes}

Scopes (consumed by build_pages.py / scaffold_theme.py):
  page      used by exactly one route → copied into that page folder
  shared    used by several routes or shared sections → user/media/images (media://images/…)
  theme     header/footer/logo/menu icons → user/themes/<theme>/images
  document  PDFs and other downloads → user/media/files (media://files/…)
Re-running is safe: cached files are reused.
"""

from __future__ import annotations

import argparse
import hashlib
import mimetypes
import re
import sys
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from htmlkit import read_json, slugify, write_json  # noqa: E402

USER_AGENT = "Mozilla/5.0 (compatible; website-to-grav/1.0)"
EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/avif": ".avif", "image/gif": ".gif", "image/svg+xml": ".svg", "video/mp4": ".mp4", "video/webm": ".webm", "application/pdf": ".pdf"}


def collect_theme_refs(chrome: dict) -> set[str]:
    refs = set()

    def walk(value):
        if isinstance(value, dict):
            for key, inner in value.items():
                if key in ("src", "image", "icon") and isinstance(inner, str) and inner.startswith("http"):
                    refs.add(inner)
                else:
                    walk(inner)
        elif isinstance(value, list):
            for inner in value:
                walk(inner)

    walk(chrome)
    return refs


def collect_block_refs(blocks) -> set[str]:
    refs = set()
    for block in blocks or []:
        if block.get("type") == "image" and block.get("src"):
            refs.add(block["src"])
        refs.update(block.get("sources", []))
        if block.get("poster"):
            refs.add(block["poster"])
        for card in block.get("cards", []):
            refs |= collect_block_refs(card.get("blocks"))
        refs.update(image["src"] for image in block.get("images", []))
    return refs


def safe_name(url: str) -> str:
    path = unquote(urlsplit(url).path)
    stem = Path(path).stem
    # Webflow prefixes uploads with a 24-hex asset id: keep the human part.
    stem = re.sub(r"^[0-9a-f]{24}_", "", stem)
    return slugify(stem, "asset")[:60]


def download(url: str, cache: Path):
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read()
            content_type = response.headers.get_content_type()
    except Exception as error:  # noqa: BLE001 - recorded for the report
        return url, {"error": str(error)}
    digest = hashlib.sha256(data).hexdigest()
    extension = Path(urlsplit(url).path).suffix.lower() or EXTENSIONS.get(content_type) or mimetypes.guess_extension(content_type) or ""
    if extension == ".jpeg":
        extension = ".jpg"
    existing = next(cache.glob(f"{digest[:12]}-*"), None)
    target = existing or cache / f"{digest[:12]}-{safe_name(url)}{extension}"
    if not existing:
        target.write_bytes(data)
    return url, {"file": target.name, "sha256": digest, "bytes": len(data), "content_type": content_type}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("migration", nargs="?", default="migration")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    root = Path(args.migration)
    cache = root / "media-cache"
    cache.mkdir(exist_ok=True)

    usage: dict[str, set[str]] = defaultdict(set)
    for content_file in (root / "content").glob("*.json"):
        record = read_json(content_file)
        for url in record.get("media", []):
            usage[url].add(record["route"])
    shared_refs = set()
    if (root / "shared-sections.json").exists():
        for section in read_json(root / "shared-sections.json").values():
            shared_refs |= collect_block_refs(section["blocks"])
    theme_refs = collect_theme_refs(read_json(root / "chrome.json")) if (root / "chrome.json").exists() else set()
    documents = set(read_json(root / "routes.json").get("documents", []))
    every_url = set(usage) | shared_refs | theme_refs | documents

    previous = read_json(root / "media-manifest.json") if (root / "media-manifest.json").exists() else {}
    pending = [url for url in sorted(every_url) if not (previous.get(url, {}).get("file") and (cache / previous[url]["file"]).exists())]
    manifest = {url: entry for url, entry in previous.items() if url in every_url}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for count, (url, entry) in enumerate(pool.map(lambda url: download(url, cache), pending), 1):
            manifest[url] = entry
            if count % 50 == 0:
                print(f"downloaded {count}/{len(pending)}", file=sys.stderr)

    by_hash: dict[str, set[str]] = defaultdict(set)
    for url, entry in manifest.items():
        if entry.get("sha256"):
            by_hash[entry["sha256"]] |= usage.get(url, set())
    for url, entry in manifest.items():
        if entry.get("error"):
            continue
        routes = sorted(by_hash[entry["sha256"]])
        if url in theme_refs:
            scope = "theme"
        elif url in documents or entry["content_type"] in ("application/pdf",) or entry["file"].endswith((".pdf", ".docx", ".xlsx", ".pptx", ".zip", ".csv")):
            scope = "document"
        elif url in shared_refs or len(routes) > 1:
            scope = "shared"
        else:
            scope = "page"
        entry.update({"scope": scope, "routes": routes})

    write_json(root / "media-manifest.json", dict(sorted(manifest.items())))
    failures = [url for url, entry in manifest.items() if entry.get("error")]
    scopes = defaultdict(int)
    for entry in manifest.values():
        scopes[entry.get("scope", "failed")] += 1
    unique = len({entry["sha256"] for entry in manifest.values() if entry.get("sha256")})
    total = sum(entry.get("bytes", 0) for entry in {entry.get("sha256"): entry for entry in manifest.values() if entry.get("sha256")}.values())
    print(f"{len(manifest)} urls → {unique} unique files ({total / 1_048_576:.1f} MiB); scopes {dict(scopes)}; {len(failures)} failed")
    for url in failures[:10]:
        print(f"  failed: {url} ({manifest[url]['error']})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
