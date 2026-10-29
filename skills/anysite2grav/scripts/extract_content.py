#!/usr/bin/env python3
"""Turn cached HTML into structured, source-backed content for Grav pages.

Usage:
  extract_content.py migration [--main-selector main] [--shared-threshold 0.5]

Reads <migration>/routes.json + html/. Writes:
  content/<page>.json      sections → ordered blocks (heading, text, list, image, video,
                           embed, button, cards, form, table, quote) + all text strings
  content-index.json       per-route summary, page kind, layout signature and cluster
  chrome.json              header menu tree, CTAs, logo, language links, footer, socials
  shared-sections.json     sections repeated across many pages (newsletter, CTA bands…)

Page kinds: "article" (one dominant rich-text region → Markdown body) or "sections"
(composed landing page → structured frontmatter). Clusters group routes whose section
layout matches, so each cluster becomes one Grav page type (template + blueprint).
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from csskit import GENERATED_CLASS, SourceStyles, to_hex, tone_of  # noqa: E402
from htmlkit import (  # noqa: E402
    Node, background_images, image_source, meta_content, normalize_space, normalize_url,
    parse_html, read_json, route_of, short_hash, site_key, write_json,
)

NOISE_TAGS = {"script", "style", "noscript", "template", "link", "meta", "svg", "canvas"}
HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
WRAPPER_HINT = re.compile(r"(?:^|[-_ ])(wrapper|wrap|page|main|content|container|body|site)(?:$|[-_ ])", re.I)
RICH_TEXT_HINT = re.compile(r"w-richtext|rich-?text|entry-content|post-content|article-body|prose|blog-content|sqs-html-content", re.I)
BUTTON_HINT = re.compile(r"\b(btn|button|cta|w-button)\b", re.I)
# Accessibility helpers that sit beside the page wrapper and must not stop section discovery.
SKIP_HINT = re.compile(r"(?:^|\s)(skip-link|skip-to-content|screen-reader-text|sr-only|visually-hidden|visuallyhidden)(?:$|\s)", re.I)
# Prose elements: a container made mostly of these is one section (or an article), not a stack of sections.
FLOW_TAGS = {"p", "ul", "ol", "blockquote", "pre", "table", "hr", "dl", "h1", "h2", "h3", "h4", "h5", "h6"}
# Filled from the source CSS in main(): block-level classes are kept only when the source styles them.
STYLED_CLASSES: set[str] = set()
COLUMNS_HINT = re.compile(r"(?:^|[-_ ])(columns|wp-block-columns|two-col|three-col|split|w-layout-grid|grid-2|grid-3|row)(?:$|[-_ ])", re.I)
SOCIAL_HOSTS = {
    "facebook.com": "facebook", "instagram.com": "instagram", "linkedin.com": "linkedin", "twitter.com": "x",
    "x.com": "x", "youtube.com": "youtube", "tiktok.com": "tiktok", "github.com": "github", "pinterest.com": "pinterest",
    "threads.net": "threads", "bsky.app": "bluesky", "medium.com": "medium", "vimeo.com": "vimeo",
}


# --- inline markdown ---------------------------------------------------------

def inline_markdown(node: Node, base: str) -> str:
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(re.sub(r"\s+", " ", child))
            continue
        tag = child.tag
        if tag in NOISE_TAGS:
            continue
        if tag == "br":
            parts.append("  \n")
        elif tag in ("strong", "b"):
            inner = inline_markdown(child, base).strip()
            parts.append(f"**{inner}**" if inner else "")
        elif tag in ("em", "i"):
            inner = inline_markdown(child, base).strip()
            parts.append(f"*{inner}*" if inner else "")
        elif tag == "code":
            parts.append(f"`{normalize_space(child.text())}`")
        elif tag == "a":
            inner = inline_markdown(child, base).strip()
            href = normalize_url(child.get("href"), base, keep_query=True) or child.get("href")
            parts.append(f"[{inner}]({href})" if inner and href else inner)
        elif tag == "img":
            continue
        else:
            parts.append(inline_markdown(child, base))
    text = "".join(parts)
    return re.sub(r"[ \t]+", " ", text).replace(" \n", "\n").strip()


# --- block extraction ---------------------------------------------------------

def child_signature(node: Node) -> str:
    return f"{node.tag}.{'.'.join(sorted(cls for cls in node.classes if not cls.startswith('w-node-')))}"


def has_content(node: Node) -> bool:
    return bool(node.text()) or bool(node.find("img", "video", "picture", "iframe"))


def is_card_grid(node: Node) -> bool:
    children = [child for child in node.element_children() if child.tag not in NOISE_TAGS]
    if len(children) < 2:
        return False
    signatures = Counter(child_signature(child) for child in children)
    signature, count = signatures.most_common(1)[0]
    if count < 2 or count < len(children) * 0.6 or signature.startswith(("li.", "p.", "span.", "a.") ) and node.tag in ("ul", "ol"):
        return False
    similar = [child for child in children if child_signature(child) == signature]
    # Cards carry their own heading or image plus text; plain paragraph runs are not cards.
    return all(has_content(child) for child in similar) and sum(1 for child in similar if child.find(*HEADINGS, "img", "picture", "strong")) >= len(similar) * 0.6 and any(len(child.element_children()) > 0 for child in similar)


def code_text(node: Node) -> str:
    """Raw text of a code sample, keeping line breaks and markup characters as typed."""
    parts = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
        elif child.tag == "br":
            parts.append("\n")
        else:
            parts.append(code_text(child))
    return "".join(parts)


def is_columns(node: Node) -> bool:
    """A side-by-side layout row: two to four content columns (text beside media, feature splits)."""
    children = meaningful_children(node)
    return 2 <= len(children) <= 4 and all(child.tag not in FLOW_TAGS for child in children)


LISTING_ITEM_HINT = re.compile(r"(?:^|\s)(wp-block-post|hentry|type-post|post|entry|w-dyn-item|collection-item|product|sqs-blog-item|summary-item)(?:$|\s)", re.I)
PAGINATION_HINT = re.compile(r"pagination|page-numbers|w-pagination|pager", re.I)
PAGED_URL = re.compile(r"/page/(\d+)/?$|[?&](?:paged|page|p)=(\d+)")
DATE_TEXT = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.? \d{1,2},? \d{4}\b|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2} (?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]* \d{4}\b",
    re.I,
)
TERM_HINT = re.compile(r"term|categor|tag|topic|label|badge", re.I)


def listing_items(node: Node) -> list[Node]:
    """Repeated item nodes of a collection-like container (2+ with the same tag)."""
    children = [child for child in meaningful_children(node)]
    if len(children) < 3:
        return []
    counts = Counter(child.tag for child in children)
    tag, count = counts.most_common(1)[0]
    items = [child for child in children if child.tag == tag]
    return items if count >= max(3, 0.7 * len(children)) else []


def listing_item(item: Node, base: str) -> dict | None:
    """Title, link, date, image, excerpt and terms of one collection item."""
    heading = item.find(*HEADINGS)
    title_anchor = (heading.find("a") if heading is not None else None) or next((anchor for anchor in item.find_all("a") if normalize_space(anchor.text())), None)
    title = normalize_space((heading or title_anchor or Node("x")).text())
    href = normalize_url((title_anchor.get("href") if title_anchor is not None else "") or (item.get("href") if item.tag == "a" else ""), base, keep_query=True)
    if not title or not href:
        return None
    entry: dict = {"title": title, "href": href}
    time_node = item.find("time")
    date_text = (time_node.get("datetime") or normalize_space(time_node.text())) if time_node is not None else None
    date_match = DATE_TEXT.search(item.text(" ")) if not date_text else None
    if date_text or date_match:
        entry["date"] = date_text or date_match.group(0)
    image = item.find("img", "picture")
    if image is not None:
        block = media_block(image, base)
        if block:
            entry["image"] = block["src"]
            entry["alt"] = block.get("alt") or ""
    terms = []
    for holder in item.iter():
        if holder is item or not TERM_HINT.search(holder.get("class")):
            continue
        for anchor in holder.find_all("a"):
            label = normalize_space(anchor.text())
            if label and label != title and label not in [term["label"] for term in terms]:
                terms.append({"label": label, "href": normalize_url(anchor.get("href"), base, keep_query=True)})
    if terms:
        entry["terms"] = terms
    title_texts = {title, *(term["label"] for term in terms), entry.get("date") or ""}
    excerpt = next((normalize_space(paragraph.text()) for paragraph in item.find_all("p") if normalize_space(paragraph.text()) not in title_texts and len(normalize_space(paragraph.text())) > 20), None)
    if excerpt:
        entry["excerpt"] = excerpt
    # Everything else the item shows (location, price, rating, author…) stays as blocks: it becomes
    # the item page's body, so turning cards into a collection never drops text.
    entry["blocks"] = extract_blocks(item, base, {})
    return entry


def detect_listing(node: Node, base: str) -> dict | None:
    """A collection (posts, products, directory cards) rather than hand-placed cards.

    Needs collection signals so ordinary navigation cards stay cards: post/CMS-item markup,
    dates on most items, or pagination right after the list.
    """
    if node.tag == "nav" or any(ancestor.tag == "nav" for ancestor in node.ancestors()):
        return None  # menus are chrome or section menus, never collections
    items = listing_items(node)
    if not items:
        return None
    signals = sum(1 for item in items if LISTING_ITEM_HINT.search(item.get("class")) or item.tag == "article")
    dated = sum(1 for item in items if item.find("time") is not None or DATE_TEXT.search(item.text(" ")))
    if signals < 0.6 * len(items) and dated < 0.6 * len(items):
        return None
    entries = [entry for entry in (listing_item(item, base) for item in items) if entry]
    if len(entries) < 3:
        return None
    routes = [route_of(entry["href"]) for entry in entries]
    parents = Counter("/".join(route.rstrip("/").split("/")[:-1]) or "/" for route in routes)
    listing = {
        "type": "listing",
        "style": "cards" if sum(1 for entry in entries if entry.get("image")) >= 0.6 * len(entries) else "list",
        "items": entries,
        "item_parent": parents.most_common(1)[0][0],
        "classes": [name for name in node.classes if name in STYLED_CLASSES and not GENERATED_CLASS.search(name)][:4],
    }
    if any(entry.get("terms") for entry in entries):
        listing["taxonomy"] = "category"
    return listing


def pagination_info(root: Node) -> dict | None:
    """Pages of a paginated listing: the highest page number linked from a pagination nav."""
    for node in root.iter():
        if not (PAGINATION_HINT.search(node.get("class")) or "pagination" in node.get("aria-label").lower()):
            continue
        numbers = [int(match.group(1) or match.group(2)) for anchor in node.find_all("a") for match in [PAGED_URL.search(anchor.get("href"))] if match]
        if numbers:
            return {"pages": max(numbers)}
    return None


def scoped_search(root: Node, page_url: str) -> Node | None:
    """The search form that searches this page's own collection (its action is the page itself)."""
    for form in root.find_all("form"):
        inputs = form.find_all("input")
        if not any(field.get("type") == "search" or field.get("name") in ("s", "q", "search", "query") for field in inputs):
            continue
        action = normalize_url(form.get("action") or page_url, page_url) or ""
        if route_of(action).rstrip("/") == route_of(page_url).rstrip("/"):
            return form
    return None


def control_target(root: Node, action: str) -> str:
    """What a label-only control opens: `content` (a tab pane), `dialog` (a popup/dropdown) or `missing`."""
    document = root
    while document.parent is not None:
        document = document.parent
    target = next((node for node in document.iter() if node.get("id") == action.lstrip("#")), None)
    if target is None:
        return "missing"
    chain = [target, *target.ancestors()]
    if any(node.tag == "dialog" or node.get("role") in ("dialog", "menu", "listbox") or re.search(r"modal|popover|dropdown|overlay", node.get("class"), re.I) for node in chain):
        return "dialog"
    return "content"


def is_pagination(node: Node) -> bool:
    return bool(PAGINATION_HINT.search(node.get("class")) or "pagination" in node.get("aria-label").lower())


def drop_blocks(blocks: list[dict], unwanted) -> list[dict]:
    """Remove blocks matching `unwanted`, also inside columns and cards."""
    kept = []
    for block in blocks:
        if unwanted(block):
            continue
        for key in ("columns", "cards"):
            if key in block:
                block[key] = [{**inner, "blocks": drop_blocks(inner["blocks"], unwanted)} for inner in block[key]]
                block[key] = [inner for inner in block[key] if inner["blocks"]]
        kept.append(block)
    return kept


def poster_url(video: Node, base: str) -> str | None:
    """Video poster, including Webflow's background-video wrapper (data-poster-url)."""
    for node in [video, *list(video.ancestors())[:2]]:
        for attribute in ("poster", "data-poster-url"):
            if node.get(attribute):
                return normalize_url(node.get(attribute), base, keep_query=True)
    return None


def media_block(node: Node, base: str):
    if node.tag in ("img",):
        source = image_source(node, base)
        if source:
            return {"type": "image", "src": source, "alt": normalize_space(node.get("alt")), "width": node.get("width") or None, "height": node.get("height") or None}
    if node.tag == "picture":
        image = node.find("img")
        source = None
        for candidate in node.find_all("source"):
            if candidate.get("srcset") and "webp" not in candidate.get("type") and "avif" not in candidate.get("type"):
                from htmlkit import best_srcset_candidate
                source = best_srcset_candidate(candidate.get("srcset"), base)
                break
        source = source or (image_source(image, base) if image else None)
        if source:
            return {"type": "image", "src": source, "alt": normalize_space(image.get("alt")) if image else ""}
    if node.tag == "video":
        sources = [normalize_url(node.get("src"), base, keep_query=True)] if node.get("src") else []
        sources += [normalize_url(source.get("src") or source.get("data-src"), base, keep_query=True) for source in node.find_all("source")]
        sources = [source for source in sources if source]
        if sources:
            return {
                "type": "video", "sources": sources,
                "poster": poster_url(node, base),
                "autoplay": "autoplay" in node.attrs, "loop": "loop" in node.attrs, "muted": "muted" in node.attrs,
            }
    if node.tag == "iframe":
        source = node.get("src") or node.get("data-src")
        if source:
            return {"type": "embed", "src": normalize_url(source, base, keep_query=True) or source, "title": node.get("title") or None}
    return None


def style_hooks(node: Node) -> dict:
    """Typography/color classes on a text block (WordPress has-*-font-size, Webflow combo classes)."""
    hooks = [name for name in node.classes if name in STYLED_CLASSES and not GENERATED_CLASS.search(name)][:4]
    return {"classes": hooks} if hooks else {}


def extract_blocks(node: Node, base: str, forms_by_node: dict) -> list[dict]:
    blocks: list[dict] = []

    def emit_text(text_node: Node, kind: str = "text"):
        markdown = inline_markdown(text_node, base)
        if markdown and len(normalize_space(markdown)) > 1:
            blocks.append({"type": kind, "text": markdown, **style_hooks(text_node)})

    def walk(current: Node):
        for child in current.children:
            if isinstance(child, str):
                text = normalize_space(child)
                if len(text) > 1 and current.tag not in ("ul", "ol", "table", "tr"):
                    blocks.append({"type": "text", "text": text})
                continue
            tag = child.tag
            if tag in NOISE_TAGS or child.get("aria-hidden") == "true" and not child.find("img", "picture", "video"):
                continue
            if child.has_class("w-form-done", "w-form-fail", "form-success", "form-error") or child.get("role") == "alert":
                continue
            if "hidden" in child.attrs or "display:none" in child.get("style").replace(" ", "").lower():
                continue
            if tag == "grav-body":
                blocks.append({"type": "body"})
                continue
            if id(child) in forms_by_node:
                blocks.append({"type": "form", "ref": forms_by_node[id(child)]})
                continue
            if tag in HEADINGS:
                text = inline_markdown(child, base)
                if text:
                    blocks.append({"type": "heading", "level": int(tag[1]), "text": text, **style_hooks(child)})
                for image in child.find_all("img"):
                    block = media_block(image, base)
                    if block:
                        blocks.append(block)
                continue
            if tag == "p":
                emit_text(child)
                for image in child.find_all("img", "picture"):
                    block = media_block(image, base)
                    if block:
                        blocks.append(block)
                continue
            if tag == "pre" or (tag == "code" and "\n" in "".join(text for text in child.children if isinstance(text, str))):
                code = child.find("code") or child
                language = next((name.split("-", 1)[1] for name in code.classes if name.startswith(("language-", "lang-"))), None)
                source = code_text(code)
                if source.strip():
                    blocks.append({"type": "code", "code": source.strip("\n"), **({"language": language} if language else {})})
                continue
            if is_pagination(child) and child.find("a") is not None:
                continue  # rebuilt by the collection's own pagination
            listing = detect_listing(child, base)
            if listing:
                blocks.append({**listing, "_path": css_path(child)})
                continue
            block_items = any(item.find(*HEADINGS, "img", "picture", "figure", "p", "dl") is not None for item in child.element_children() if item.tag == "li")
            if tag in ("ul", "ol") and block_items and not is_card_grid(child):
                # Items that are whole blocks (a slide, a feature row) aren't list text: keep their structure.
                walk(child)
                continue
            if tag in ("ul", "ol") and not is_card_grid(child):
                items, groups = [], []
                for item in child.element_children():
                    if item.tag != "li":
                        continue
                    sub = next((inner for inner in item.element_children() if inner.tag in ("ul", "ol")), None) or item.find("ul", "ol")
                    if sub is None:
                        items.append(inline_markdown(item, base))
                        continue
                    # Menus and outlines: "Label" + its own links, instead of one run-on string.
                    owner = sub.parent
                    owner.children = [node for node in owner.children if node is not sub]
                    label = inline_markdown(item, base)
                    owner.children.append(sub)
                    entries = [inline_markdown(entry, base) for entry in sub.find_all("li")]
                    groups.append({"type": "list", "ordered": sub.tag == "ol", "title": label or None, "items": [entry for entry in entries if entry]})
                items = [item for item in items if item]
                if items:
                    entry = {"type": "list", "ordered": tag == "ol", "items": items, "_path": css_path(child)}
                    lis = [item for item in child.element_children() if item.tag == "li"]
                    active = next((index for index, item in enumerate(lis) if re.search(r"(?:^|[\s_-])(current|active|is-active)(?:$|[\s_-])", item.get("class")) or item.find_all("a") and any(anchor.get("aria-current") for anchor in item.find_all("a"))), None)
                    if active is not None:
                        entry["active"] = active
                    blocks.append(entry)
                blocks.extend({key: value for key, value in group.items() if value is not None} for group in groups if group["items"])
                for image in child.find_all("img"):
                    block = media_block(image, base)
                    if block:
                        blocks.append(block)
                continue
            if tag == "blockquote":
                emit_text(child, "quote")
                continue
            if tag == "table":
                rows = [[normalize_space(cell.text()) for cell in row.find_all("td", "th")] for row in child.find_all("tr")]
                if rows:
                    blocks.append({"type": "table", "rows": rows})
                continue
            if tag in ("img", "picture", "video", "iframe"):
                block = media_block(child, base)
                if block:
                    blocks.append(block)
                continue
            if tag == "a":
                label = normalize_space(child.text())
                href = normalize_url(child.get("href"), base, keep_query=True) or child.get("href") or ""
                images = child.find_all("img", "picture")
                if label and (BUTTON_HINT.search(child.get("class")) or child.get("role") == "button" or len(label) <= 40 and not child.find(*HEADINGS, "p")):
                    blocks.append({"type": "button", "label": label, "href": href})
                    for image in images:
                        block = media_block(image, base)
                        if block:
                            blocks.append({**block, "href": href})
                    continue
                if images and not label:
                    for image in images:
                        block = media_block(image, base)
                        if block:
                            blocks.append({**block, "href": href})
                    continue
                # Linked card or rich link block: keep inner structure, remember the link.
                start = len(blocks)
                walk(child)
                for block in blocks[start:]:
                    block.setdefault("href", href)
                continue
            for background in background_images(child, base):
                blocks.append({"type": "image", "src": background, "alt": "", "role": "background"})
            if COLUMNS_HINT.search(child.get("class")) and is_columns(child) and (child.has_class("wp-block-columns") or not is_card_grid(child)):
                columns = [extract_blocks(column, base, forms_by_node) for column in meaningful_children(child)]
                columns = [{"blocks": column} for column in columns if column]
                if len(columns) >= 2:
                    blocks.append({"type": "columns", "columns": columns, "_path": css_path(child)})
                    continue
                blocks.extend(block for column in columns for block in column["blocks"])
                continue
            if is_card_grid(child):
                items = []
                for item in child.element_children():
                    if item.tag in NOISE_TAGS:
                        continue
                    item_blocks = extract_blocks(item, base, forms_by_node)
                    href = item.get("href") if item.tag == "a" else None
                    if item_blocks:
                        items.append({"blocks": item_blocks, "classes": [cls for cls in item.classes if not cls.startswith("w-")][:4], **({"href": normalize_url(href, base, keep_query=True)} if href else {})})
                if items:
                    blocks.append({"type": "cards", "classes": child.classes[:4], "cards": items, "_path": css_path(child)})
                continue
            if tag in ("button",):
                label = normalize_space(child.text())
                if label:
                    action = child.get("data-target") or child.get("aria-controls") or None
                    entry = {"type": "button", "label": label, "href": None, "action": action, "_path": css_path(child)}
                    if action:
                        entry["_target"] = control_target(node, action)
                    blocks.append(entry)
                continue
            walk(child)

    walk(node)
    return merge_text_runs(blocks)


LOGO_HINT = re.compile(r"logo|brand|partner|client|award|badge|press", re.I)


def merge_text_runs(blocks: list[dict]) -> list[dict]:
    merged: list[dict] = []
    for block in blocks:
        if merged and block["type"] == "text" and merged[-1]["type"] == "text" and len(block["text"]) < 3:
            merged[-1]["text"] += " " + block["text"]
            continue
        merged.append(block)
    return group_galleries(merged)


def group_galleries(blocks: list[dict]) -> list[dict]:
    """Runs of 3+ consecutive non-background images become one gallery (logo strips, photo grids)."""
    output: list[dict] = []
    run: list[dict] = []

    def flush():
        if len(run) >= 3:
            images = [{key: image[key] for key in ("src", "alt", "href", "width", "height") if image.get(key)} for image in run]
            logos = sum(1 for image in run if image["src"].lower().split("?")[0].endswith(".svg") or LOGO_HINT.search(image["src"] + " " + image.get("alt", ""))) >= len(run) * 0.6
            output.append({"type": "gallery", "style": "logos" if logos else "photos", "images": images})
        else:
            output.extend(run)
        run.clear()

    for block in blocks:
        if block["type"] == "image" and block.get("role") != "background":
            run.append(block)
            continue
        flush()
        output.append(block)
    flush()
    return output


# --- page structure -----------------------------------------------------------

def content_root(document: Node, selector: str | None) -> Node:
    body = document.find("body") or document
    if selector:
        if selector.startswith("."):
            match = next((node for node in body.iter() if node.has_class(selector[1:])), None)
        elif selector.startswith("#"):
            match = next((node for node in body.iter() if node.get("id") == selector[1:]), None)
        else:
            match = body.find(selector)
        if match:
            return match
    return body


def css_path(node: Node) -> str:
    """body > … > tag:nth-child(n) path, so capture_pages.mjs can measure this exact element on the source."""
    parts = []
    while node is not None and node.parent is not None and node.tag not in ("body", "html", "#root"):
        siblings = node.parent.element_children()
        parts.append(f"{node.tag}:nth-child({next(index for index, sibling in enumerate(siblings, 1) if sibling is node)})")
        node = node.parent
    return "body > " + " > ".join(reversed(parts)) if parts else "body"


def is_ignorable(node: Node) -> bool:
    """Skip links, screen-reader-only text and hidden nodes: never sections, never wrappers."""
    if node.tag in NOISE_TAGS or "hidden" in node.attrs or SKIP_HINT.search(node.get("class")):
        return True
    return node.get("aria-hidden") == "true" and node.find("img", "picture", "video") is None


def meaningful_children(node: Node) -> list[Node]:
    return [child for child in node.element_children() if not is_ignorable(child) and (has_content(child) or child.tag in ("header", "nav", "footer"))]


def is_flow_container(node: Node) -> bool:
    """Mostly headings/paragraphs/lists: a prose region to keep whole."""
    children = meaningful_children(node)
    return len(children) >= 3 and sum(1 for child in children if child.tag in FLOW_TAGS) >= 0.6 * len(children)


def section_nodes(root: Node) -> list[Node]:
    """Section-level nodes: split around <main>, descend through single wrappers until siblings appear.

    Stops at prose containers (a privacy policy is one section, not sixty) and ignores skip links,
    which builders and WordPress place beside the page wrapper.
    """
    node = root
    for _ in range(8):
        children = meaningful_children(node)
        main = next((child for child in children if child.tag == "main" or child.get("role") == "main"), None)
        holders = [child for child in children if child.find("main") is not None or any(inner.get("role") == "main" for inner in child.iter())]
        if main is None and len(holders) == 1 and len(children) > 1:
            # <main> sits inside a wrapper beside the header/footer (classic WordPress themes: div.site).
            main = holders[0]
        if main is not None:
            # Header, local navigation, footer and modals stay as siblings, in document order.
            position = next(index for index, child in enumerate(children) if child is main)
            return expand_chrome_wrappers(children[:position]) + section_nodes(main) + expand_chrome_wrappers(children[position + 1:])
        if len(children) == 1 and not is_flow_container(children[0]) and (
            children[0].tag in ("div", "main", "section", "article") or WRAPPER_HINT.search(children[0].get("class"))
        ):
            node = children[0]
            continue
        if not children or is_flow_container(node):
            return [node]
        return children
    return [node]


def expand_chrome_wrappers(nodes: list[Node]) -> list[Node]:
    """A wrapper holding the site <header> plus a section menu splits into its parts, so the menu
    isn't dropped with the header (WordPress: div.site-header-container > header + local nav)."""
    expanded = []
    for node in nodes:
        if node.tag not in ("header", "footer", "nav") and node.find("header") is not None and len(meaningful_children(node)) > 1:
            expanded.extend(expand_chrome_wrappers(meaningful_children(node)))
        else:
            expanded.append(node)
    return expanded


def selected_sections(root: Node, selector: str) -> list[Node]:
    """--section-selector: the outermost nodes matching a tag, .class or #id, in document order."""
    def matches(node: Node) -> bool:
        if selector.startswith("."):
            return node.has_class(selector[1:])
        if selector.startswith("#"):
            return node.get("id") == selector[1:]
        return node.tag == selector
    found = [node for node in root.iter() if node is not root and matches(node)]
    found_ids = {id(node) for node in found}
    return [node for node in found if not any(id(ancestor) in found_ids for ancestor in node.ancestors())]


def is_link_bar(node: Node) -> bool:
    """A secondary navigation bar (section menu, breadcrumbs strip): links carry nearly all its text."""
    anchors = node.find_all("a")
    text = normalize_space(node.text())
    if len(anchors) < 3 or not text or len(text) > 800 or node.find(*HEADINGS) is not None:
        return False
    link_text = sum(len(normalize_space(anchor.text())) for anchor in anchors)
    return (node.tag == "nav" or node.find("nav") is not None) and link_text >= 0.6 * len(text)


def section_key(node: Node) -> str:
    return child_signature(node) + "|" + short_hash(normalize_space(node.text())[:4000])


def is_chrome(node: Node) -> bool:
    joined = node.get("class").lower() + " " + node.get("id").lower()
    return node.tag in ("header", "nav", "footer") or node.get("role") in ("banner", "navigation", "contentinfo") or bool(re.search(r"\b(nav|navbar|header|footer|menu)\b", joined))


# --- chrome: menu + footer ------------------------------------------------------

def link_entry(anchor: Node, base: str) -> dict | None:
    href = normalize_url(anchor.get("href"), base, keep_query=True)
    lines = [line for line in anchor.text("\n").split("\n") if line.strip()]
    raw_href = anchor.get("href").strip()
    if not href and lines and (raw_href.startswith("#") or raw_href == "" or anchor.get("data-target")):
        # In-page/modal triggers (e.g. "Schedule a demo" opening a popup form).
        return {"label": lines[0], "url": None, "action": raw_href or anchor.get("data-target") or "button"}
    if not href or not lines:
        image = anchor.find("img")
        if href and image is not None:
            return {"label": normalize_space(image.get("alt")) or None, "url": href, "image": image_source(image, base)}
        return None
    entry = {"label": lines[0], "url": href}
    if len(lines) > 1:
        entry["description"] = " ".join(lines[1:])
    image = anchor.find("img")
    if image is not None:
        entry["icon"] = image_source(image, base)
    if anchor.get("hreflang"):
        entry["hreflang"] = anchor.get("hreflang")
    return entry


DROPDOWN_HINT = re.compile(r"drop-?down|has-children|submenu|sub-menu|mega|flyout", re.I)
LOCALE_HINT = re.compile(r"locale|language|lang-|-lang|transl|wpml|weglot|i18n", re.I)
CTA_HINT = re.compile(r"(?:^|[-_ ])(btn|cta|primary|w-button|button|get|download|signup|sign-up|register)(?:$|[-_ ])", re.I)


def dropdown_label(node: Node) -> str | None:
    """A short text label that is a direct child and contains no links (a menu toggle)."""
    for child in node.element_children():
        if child.find("a") is not None or child.tag == "a":
            continue
        text = normalize_space(child.text())
        if 0 < len(text) <= 40 and not child.find("ul", "ol"):
            return text
    for child in node.children:
        if isinstance(child, str) and 0 < len(normalize_space(child)) <= 40:
            return normalize_space(child)
    return None


def is_dropdown(node: Node, header: Node) -> bool:
    if node is header or node.tag == "a":
        return False
    links = node.find_all("a")
    if len(links) < 2:
        return False
    toggle_anchor = next((child for child in node.element_children() if child.tag == "a"), None)
    structural = (dropdown_label(node) is not None or toggle_anchor is not None) and any(
        child.tag != "a" and len(child.find_all("a")) >= 2 for child in node.element_children()
    )
    return structural and (DROPDOWN_HINT.search(node.get("class")) is not None or any(DROPDOWN_HINT.search(child.get("class")) for child in node.iter()) or node.tag == "li")


def menu_tree(header: Node, base: str) -> list[dict]:
    """Ordered top-level menu entries; dropdowns carry children. Works on Webflow
    (label div + drop-down list), WordPress (nested ul.sub-menu) and plain nav markup."""
    candidates = [node for node in header.iter() if is_dropdown(node, header)]
    # The innermost container that still owns a label + link group is the dropdown.
    dropdowns = [node for node in candidates if not any(other is not node and node in list(other.ancestors()) for other in candidates) or True]
    dropdowns = [node for node in dropdowns if not any(inner is not node and node in list(inner.ancestors()) and dropdown_label(inner) for inner in candidates)]
    seen: set[int] = set()
    order: list[tuple[int, dict]] = []
    positions = {id(node): index for index, node in enumerate(header.iter())}
    for dropdown in dropdowns:
        if any(id(anchor) in seen for anchor in dropdown.find_all("a")):
            continue
        toggle_anchor = next((child for child in dropdown.element_children() if child.tag == "a"), None)
        label = dropdown_label(dropdown) or (normalize_space(toggle_anchor.text()) if toggle_anchor is not None else None)
        children = []
        for anchor in dropdown.find_all("a"):
            seen.add(id(anchor))
            if anchor is toggle_anchor:
                continue
            entry = link_entry(anchor, base)
            if entry:
                children.append(entry)
        if label and children:
            locale = bool(LOCALE_HINT.search(" ".join(node.get("class") for node in [dropdown, *dropdown.iter()])))
            order.append((positions[id(dropdown)], {
                "label": label,
                "url": link_entry(toggle_anchor, base)["url"] if toggle_anchor is not None and link_entry(toggle_anchor, base) else None,
                "children": children,
                **({"locale_switcher": True} if locale else {}),
            }))
    for anchor in header.find_all("a"):
        if id(anchor) in seen:
            continue
        entry = link_entry(anchor, base)
        if entry:
            entry["classes"] = anchor.classes[:4]
            entry["in_list"] = any(node.tag == "li" for node in anchor.ancestors() if node is not header and header in list(node.ancestors()))
            entry["locale"] = bool(LOCALE_HINT.search(anchor.get("class"))) or bool(
                entry.get("url") and re.fullmatch(r"/[a-z]{2}(?:-[a-z]{2})?", route_of(entry["url"])) and not anchor.find("img")
            )
            order.append((positions[id(anchor)], entry))
    return [entry for _, entry in sorted(order, key=lambda pair: pair[0])]


def inline_logo(header: Node) -> Node | None:
    """The first <svg> inside a home link or a logo/brand element."""
    for svg in header.find_all("svg"):
        holders = [svg, *list(svg.ancestors())[:4]]
        home = any(node.tag == "a" and re.fullmatch(r"(?:https?://[^/]+)?/(?:[a-z]{2}(?:-[a-z]{2})?/?)?", node.get("href").strip()) for node in holders)
        if home or any(re.search(r"logo|brand", node.get("class"), re.I) for node in holders):
            return svg
    return None


def logo_position(header: Node, target: Node) -> int:
    return next((index for index, node in enumerate(header.iter()) if node is target), 10**9)


LANGUAGE_NAMES = {"english", "español", "espanol", "français", "francais", "nederlands", "deutsch", "italiano", "português", "portugues", "日本語", "中文", "en", "es", "fr", "nl", "de", "it", "pt", "ja", "zh"}


def chrome_summary(header: Node | None, footer: Node | None, base: str, site: str) -> dict:
    summary: dict = {"menu": [], "ctas": [], "logo": None, "languages": [], "footer": {"columns": [], "socials": [], "legal": None}}
    if header is not None and any(
        field.get("type") == "search" or field.get("name") in ("s", "q", "search", "query") for field in header.find_all("input")
    ):
        # Site search in the header → Grav's simplesearch (or tntsearch) at /search.
        summary["search"] = True
    if header is not None:
        items = menu_tree(header, base)
        home = next((item for item in items if item.get("image") and item.get("url") and re.fullmatch(r"/(?:[a-z]{2}(?:-[a-z]{2})?)?", route_of(item["url"]))), None)
        if home:
            summary["logo"] = {"src": home["image"], "alt": home.get("label")}
        else:
            logo = header.find("img")
            svg = inline_logo(header)
            if logo is not None and (svg is None or logo_position(header, logo) < logo_position(header, svg)):
                summary["logo"] = {"src": image_source(logo, base), "alt": normalize_space(logo.get("alt"))}
            elif svg is not None:
                # Inline SVG logos (WordPress, many hand-built sites) have no URL; keep the markup.
                label = svg.get("aria-label") or normalize_space((svg.find("title") or Node("x")).text()) or (svg.parent.get("aria-label") if svg.parent else "")
                summary["logo"] = {"svg": svg.html(), "alt": label or None}
        for item in items:
            if item is home:
                continue
            url = item.get("url") or ""
            label = (item.get("label") or "").lower()
            if item.get("locale_switcher"):
                summary["languages"].extend(item["children"])
            elif item.get("children"):
                summary["menu"].append(item)
            elif item.pop("locale", False) or item.get("hreflang") or label in LANGUAGE_NAMES:
                summary["languages"].append(item)
            elif CTA_HINT.search(" ".join(item.get("classes", []))) or item.get("action") or (url and site_key(urlsplit(url).hostname or "") != site and not item.get("in_list")):
                if re.search(r"only-mobile|mobile-only|hide-desktop|show-mobile|visible-xs", " ".join(item.get("classes", [])), re.I):
                    item["mobile_only"] = True
                summary["ctas"].append(item)
            elif not any(existing.get("label") == item.get("label") and existing.get("url") == item.get("url") for existing in summary["menu"]):
                summary["menu"].append(item)
            item.pop("classes", None)
            item.pop("locale", None)
            item.pop("in_list", None)
        # A CTA also listed in the (mobile) menu shows once, as the CTA.
        cta_keys = {(cta.get("label"), cta.get("url")) for cta in summary["ctas"]}
        summary["menu"] = [item for item in summary["menu"] if (item.get("label"), item.get("url")) not in cta_keys]
        # Mobile-only duplicates of a CTA (same label) are noise.
        summary["ctas"] = list({(cta.get("label") or "").lower(): cta for cta in summary["ctas"]}.values())
        if any(not cta.get("mobile_only") for cta in summary["ctas"]):
            summary["ctas"] = [cta for cta in summary["ctas"] if not cta.get("mobile_only")]
    if footer is not None:
        for anchor in footer.find_all("a"):
            href = normalize_url(anchor.get("href"), base, keep_query=True) or ""
            host = site_key(urlsplit(href).hostname or "")
            network = next((name for domain, name in SOCIAL_HOSTS.items() if host == domain or host.endswith("." + domain)), None)
            if network:
                summary["footer"]["socials"].append({"network": network, "url": href, "label": normalize_space(anchor.text()) or anchor.get("aria-label") or None})
        groups, grouped = [], set()
        for column in footer.iter():
            anchors = [anchor for anchor in column.element_children() if anchor.tag == "a"] or [item.find("a") for item in column.element_children() if item.tag == "li" and item.find("a")]
            anchors = [anchor for anchor in anchors if anchor is not None and id(anchor) not in grouped]
            if len(anchors) >= 2:
                siblings = column.parent.element_children() if column.parent else []
                heading = next((node for node in [*column.element_children(), *siblings] if node.tag in HEADINGS or re.search(r"heading|title", node.get("class"), re.I)), None)
                links = [entry for entry in (link_entry(anchor, base) for anchor in anchors) if entry]
                grouped.update(id(anchor) for anchor in anchors)
                groups.append({"heading": normalize_space(heading.text()) if heading else None, "links": links})
        summary["footer"]["columns"] = groups
        legal = next((line for line in footer.text("\n").split("\n") if re.search(r"©|\(c\)|copyright|all rights reserved", line, re.I)), None)
        summary["footer"]["legal"] = legal.strip() if legal else None
    return summary


# --- main ---------------------------------------------------------------------

def page_kind(sections: list[dict], document: Node) -> tuple[str, Node | None]:
    rich = [node for node in document.iter() if (node.tag == "article" or RICH_TEXT_HINT.search(node.get("class"))) and is_prose(node)]
    if rich:
        largest = max(rich, key=lambda node: len(node.text()))
        total = sum(len(" ".join(block.get("text", "") for block in section["blocks"])) for section in sections) or 1
        if len(largest.text()) > 0.45 * total and len(largest.find_all("p")) >= 4:
            return "article", largest
    return "sections", None


def is_prose(node: Node) -> bool:
    """Prose after unwrapping single wrappers: WordPress block themes mark the whole <main> as
    entry-content, so the class alone would turn every composed page into an article."""
    for _ in range(4):
        children = meaningful_children(node)
        if len(children) == 1 and children[0].tag in ("div", "section", "article"):
            node = children[0]
            continue
        break
    return is_flow_container(node)


def markdown_from_blocks(blocks: list[dict]) -> str:
    out: list[str] = []
    for block in blocks:
        kind = block["type"]
        if kind == "heading":
            out.append("#" * block["level"] + " " + block["text"])
        elif kind in ("text",):
            out.append(block["text"])
        elif kind == "quote":
            out.append("> " + block["text"].replace("\n", "\n> "))
        elif kind == "list":
            out.append("\n".join(("1. " if block["ordered"] else "- ") + item for item in block["items"]))
        elif kind == "image":
            out.append(f"![{block.get('alt', '')}]({block['src']})")
        elif kind == "button":
            if block.get("href"):
                out.append(f"[{block['label']}]({block['href']})")
        elif kind == "embed":
            out.append(f"<iframe src=\"{block['src']}\" loading=\"lazy\" title=\"{block.get('title') or 'Embedded content'}\"></iframe>")
        elif kind == "video":
            out.append(f"<video src=\"{block['sources'][0]}\" controls></video>")
        elif kind == "table":
            rows = block["rows"]
            if rows:
                width = max(len(row) for row in rows)
                padded = [row + [""] * (width - len(row)) for row in rows]
                out.append("| " + " | ".join(padded[0]) + " |\n|" + " --- |" * width + "\n" + "\n".join("| " + " | ".join(row) + " |" for row in padded[1:]))
        elif kind == "cards":
            for item in block["cards"]:
                out.append(markdown_from_blocks(item["blocks"]))
        elif kind == "code":
            out.append(f"```{block.get('language') or ''}\n{block['code']}\n```")
        elif kind == "listing":
            out.append("\n".join(f"- [{item['title']}]({item['href']})" for item in block["items"]))
        elif kind == "columns":
            for column in block["columns"]:
                out.append(markdown_from_blocks(column["blocks"]))
        elif kind == "gallery":
            out.append("\n".join(f"![{image.get('alt', '')}]({image['src']})" for image in block["images"]))
        elif kind == "form":
            out.append(f"<!-- form: {block['ref']} -->")
    return "\n\n".join(part for part in out if part.strip())


def all_texts(blocks: list[dict]) -> list[str]:
    texts = []
    for block in blocks:
        if block.get("text"):
            texts.append(normalize_space(re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", block["text"]).replace("**", "").replace("*", "")))
        texts.extend(normalize_space(item) for item in block.get("items", []) if isinstance(item, str))
        if block.get("label"):
            texts.append(block["label"])
        for card in block.get("cards", []) + block.get("columns", []):
            texts.extend(all_texts(card["blocks"]))
        for item in block.get("items", []) if block["type"] == "listing" else []:
            texts.extend(all_texts(item.get("blocks") or [{"type": "text", "text": item.get("title") or ""}]))
    return [text for text in texts if text]


def media_refs(blocks: list[dict]) -> list[str]:
    refs = []
    for block in blocks:
        if block.get("src") and block["type"] == "image":
            refs.append(block["src"])
        refs.extend(block.get("sources", []))
        if block.get("poster"):
            refs.append(block["poster"])
        for card in block.get("cards", []) + block.get("columns", []):
            refs.extend(media_refs(card["blocks"]))
        for item in block.get("items", []) if block["type"] == "listing" else []:
            refs.extend(media_refs(item.get("blocks", [])) or ([item["image"]] if item.get("image") else []))
        refs.extend(image["src"] for image in block.get("images", []))
    return refs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("migration", nargs="?", default="migration")
    parser.add_argument("--main-selector", default=None, help="CSS-ish selector of the main content wrapper (tag, .class or #id)")
    parser.add_argument("--section-selector", default=None, help="tag, .class or #id that marks each section, when automatic splitting finds too few")
    parser.add_argument("--shared-threshold", type=float, default=0.5, help="share of same-language pages a section must repeat on to count as shared")
    args = parser.parse_args()
    root = Path(args.migration)
    routes = read_json(root / "routes.json")
    audit = read_json(root / "audit.json") if (root / "audit.json").exists() else {"forms": []}
    site = site_key(urlsplit(routes["source"]).hostname or "")
    pages = routes["pages"]

    styles = SourceStyles(root)
    STYLED_CLASSES.clear()
    parsed = {}
    lang_counts = Counter()
    key_counts: dict[str, Counter] = defaultdict(Counter)
    for page in pages:
        document = parse_html((root / page["html_file"]).read_text(encoding="utf-8"))
        for style in document.find_all("style"):
            styles.add_css("".join(child for child in style.children if isinstance(child, str)))
        content = content_root(document, args.main_selector)
        nodes = section_nodes(content)
        if args.section_selector:
            chrome_nodes = [node for node in nodes if is_chrome(node)]
            nodes = chrome_nodes + [node for node in selected_sections(content, args.section_selector) if not any(node is chrome or chrome in list(node.ancestors()) for chrome in chrome_nodes)]
        lang = (page.get("lang") or "x").split("-")[0].lower()
        lang_counts[lang] += 1
        for node in nodes:
            key_counts[lang][section_key(node)] += 1
        parsed[page["route"]] = (page, document, nodes, lang)

    STYLED_CLASSES.update(styles.styled)
    # Map form DOM nodes back to the audit's form signatures.
    from audit_site import extract_forms  # local import keeps audit optional

    shared_sections: dict[str, dict] = {}
    chrome_by_lang: dict[str, dict] = {}
    index = []
    (root / "content").mkdir(exist_ok=True)
    for route, (page, document, nodes, lang) in parsed.items():
        threshold = max(3, lang_counts[lang] * args.shared_threshold) if lang_counts[lang] >= 4 else 10**9
        forms_by_node = {}
        page_lang = (page.get("lang") or "").split("-")[0].lower() or None
        for form_node, form in zip(document.find_all("form"), extract_forms(document, page["url"], page_lang) + [None] * 999):
            if form is not None:
                forms_by_node[id(form_node)] = form["signature"]
        header = footer = None
        sections = []
        section_nodes_kept: list[Node] = []
        main_node = document.find("main")
        for position, node in enumerate(nodes):
            key = section_key(node)
            repeated = key_counts[lang][key] >= threshold
            # Inside <main>, a <header>/<footer> is page content (a post list's footer band, a hero).
            in_main = main_node is not None and (node is main_node or main_node in list(node.ancestors()))
            # Only the last footer-like node is the site footer; an earlier one that isn't repeated
            # site-wide is a content band (a newsletter/"follow us" footer template part).
            later_footer = any(is_chrome(other) and re.search(r"footer", other.tag + other.get("class"), re.I) for other in nodes[position + 1:])
            content_footer = later_footer and not repeated and re.search(r"footer", node.tag + node.get("class"), re.I)
            chrome = is_chrome(node) and not in_main and not content_footer
            if chrome or (not in_main and repeated and position in (0, len(nodes) - 1) and is_chrome_like_position(node)):
                if node.tag == "footer" or re.search(r"footer", node.get("class") + node.get("id"), re.I) or position == len(nodes) - 1:
                    footer = footer or node
                else:
                    header = header or node
                continue
            nested_navs = [] if is_link_bar(node) else [inner for inner in node.iter() if inner is not node and is_nested_site_nav(inner)]
            for nested in nested_navs:
                if nested.parent is None:
                    continue  # already detached with an outer nav
                header = header or nested
                nested.remove()
            blocks = extract_blocks(node, page["url"], forms_by_node)
            if not blocks:
                continue
            section = {
                "id": node.get("id") or None,
                "_path": css_path(node),
                "_hint": normalize_space(node.text())[:60],
                "tag": node.tag,
                "classes": [cls for cls in node.classes if not GENERATED_CLASS.search(cls)][:6],
                "backgrounds": background_images(node, page["url"]),
                "blocks": blocks,
            }
            color = styles.background_color(node.classes, node.get("style"))
            if color:
                # tone goes to frontmatter; the measured color only feeds the theme's tone tokens.
                section["tone"] = tone_of(color)
                section["background_color"] = to_hex(color)
            space = styles.space(node.get("style"))
            if space:
                section["space"] = space
            if is_link_bar(node):
                # Section menus often ship twice (desktop + mobile overlay); keep one copy.
                section["role"] = "subnav"
                unique = {}
                for block in blocks:
                    # Compare content only: the desktop and mobile copies sit at different paths.
                    unique.setdefault(repr(sorted((key, value) for key, value in block.items() if not key.startswith("_"))), block)
                section["blocks"] = blocks = list(unique.values())
            if node.tag == "dialog" or re.search(r"modal|popup|lightbox|overlay", node.get("class"), re.I):
                section["modal"] = True
            # An autoplaying muted video at the top of a section is a background, not content.
            first_video = next((block for block in blocks[:2] if block["type"] == "video"), None)
            if first_video and first_video.get("autoplay") and (first_video.get("muted") or first_video.get("loop")):
                section["background_video"] = first_video
                section["blocks"] = [block for block in blocks if block is not first_video]
            if repeated:
                shared_id = "shared-" + short_hash(key, 8)
                shared_sections.setdefault(shared_id, {"id": shared_id, "lang": lang, "classes": section["classes"], "tone": section.get("tone"), "background_color": section.get("background_color"), "modal": section.get("modal", False), "blocks": blocks, "routes": []})["routes"].append(route)
                section = {"shared": shared_id, "classes": section["classes"]}
            sections.append(section)
            section_nodes_kept.append(node)
        listings = [block for section in sections for block in section.get("blocks", []) if block["type"] == "listing"]
        if listings:
            scope = main_node or document
            primary = max(listings, key=lambda block: len(block["items"]))
            pages = pagination_info(scope)
            if pages:
                primary["pagination"] = {"pages": pages["pages"], "per_page": len(primary["items"])}
            search_form = scoped_search(document, page["url"])
            if search_form is not None:
                # The collection renders its own search box; the source form would duplicate it.
                primary["search"] = True
                signature = forms_by_node.get(id(search_form))
                if signature:
                    for section in sections:
                        if "blocks" in section:
                            section["blocks"] = drop_blocks(section["blocks"], lambda block: block.get("type") == "form" and block.get("ref") == signature)
        if lang not in chrome_by_lang and (header is not None or footer is not None):
            chrome_by_lang[lang] = chrome_summary(header, footer, page["url"], site)
        kind, article_node = page_kind([section for section in sections if "blocks" in section], document)
        body_markdown = None
        blocks_flat = [block for section in sections for block in section.get("blocks", [])]
        media_flat = media_refs(blocks_flat) + [
            ref for section in sections if section.get("background_video")
            for ref in section["background_video"]["sources"] + ([section["background_video"]["poster"]] if section["background_video"].get("poster") else [])
        ]
        if kind == "article" and article_node is not None:
            body_markdown = markdown_from_blocks(extract_blocks(article_node, page["url"], forms_by_node))
            # Swap only the rich-text node for a {type: body} block; the hero, related cards and CTAs
            # around it (often in the same section) stay structured.
            for position, node in enumerate(section_nodes_kept):
                within_article = article_node in list(node.ancestors())
                if "blocks" in sections[position] and (node is article_node or within_article or node in list(article_node.ancestors())):
                    if node is article_node or within_article:
                        # The section sits inside the article: the Markdown body replaces it, never both.
                        sections[position]["blocks"] = [{"type": "body"}]
                    else:
                        parent = article_node.parent
                        placeholder = Node("grav-body", {}, parent)
                        parent.children = [placeholder if child is article_node else child for child in parent.children]
                        sections[position]["blocks"] = extract_blocks(node, page["url"], forms_by_node)
                    break
        signature = [".".join(section["classes"][:2]) or section.get("tag", "div") for section in sections]
        record = {
            "route": route,
            "url": page["url"],
            "lang": lang,
            "title": page.get("title"),
            "h1": page.get("h1"),
            "description": page.get("description"),
            "og": page.get("og", {}),
            "canonical": page.get("canonical"),
            "hreflang": page.get("hreflang", []),
            "kind": kind,
            "layout_signature": signature,
            "sections": sections,
            "body_markdown": body_markdown,
            "texts": all_texts(blocks_flat),
            "media": sorted(set(media_flat + [bg for section in sections for bg in section.get("backgrounds", [])] + ([page["og"]["image"]] if page.get("og", {}).get("image") else []))),
            "forms": sorted({block["ref"] for block in blocks_flat if block["type"] == "form"}),
        }
        file_name = Path(page["html_file"]).with_suffix(".json").name
        write_json(root / "content" / file_name, record)
        index.append({
            "route": route, "file": f"content/{file_name}", "lang": lang, "kind": kind,
            "title": page.get("title"), "sections": len(sections), "texts": len(record["texts"]),
            "media": len(record["media"]), "forms": record["forms"], "layout_signature": signature,
        })

    clusters = cluster_layouts(index)
    # A composed page that comes out as one giant section means the splitter missed the page's
    # structure. Fix extraction (--main-selector / --section-selector); never fall back to raw HTML.
    monoliths = sorted(item["route"] for item in index if item["kind"] == "sections" and item["sections"] <= 1 and item["texts"] >= 30)
    quality = {"monolith_pages": monoliths, "chrome_languages": sorted(chrome_by_lang)}
    write_json(root / "content-index.json", {"pages": sorted(index, key=lambda item: item["route"]), "clusters": clusters, "quality": quality})
    write_json(root / "chrome.json", chrome_by_lang)
    write_json(root / "shared-sections.json", shared_sections)
    kinds = Counter(item["kind"] for item in index)
    print(f"{len(index)} pages → {dict(kinds)}, {len(clusters)} layout clusters, {len(shared_sections)} shared sections, chrome for {sorted(chrome_by_lang)}")
    if not chrome_by_lang:
        print("WARNING: no header/footer detected — pass --main-selector or inspect html/ to locate the site chrome", file=sys.stderr)
    if monoliths:
        print(f"WARNING: {len(monoliths)} composed page(s) came out as a single section ({', '.join(monoliths[:5])}{'…' if len(monoliths) > 5 else ''}). "
              "Inspect html/ and rerun with --section-selector (or --main-selector); do not replace pages with raw HTML.", file=sys.stderr)
    return 0


def is_nested_site_nav(node: Node) -> bool:
    """A site header/menu nested inside a content section (Webflow puts the navbar inside heroes)."""
    if node.tag not in ("nav", "header") and node.get("role") not in ("navigation", "banner") and not re.search(r"\b(navbar|site-header|main-nav|w-nav)\b", node.get("class")):
        return False
    if any(ancestor.tag == "article" or LISTING_ITEM_HINT.search(ancestor.get("class")) for ancestor in [node, *node.ancestors()]):
        return False  # a post's entry header (title + terms links) is content, not the site menu
    anchors = node.find_all("a")
    home_logo = any(anchor.find("img") is not None and re.fullmatch(r"/(?:[a-z]{2}(?:-[a-z]{2})?)?", urlsplit(anchor.get("href") or "#").path or "/") for anchor in anchors)
    site_menu_class = re.search(r"(?:^|[\s_-])(nav|navbar|menu|site-header|global-header|main-header|masthead)(?:$|[\s_-])", node.get("class"), re.I)
    return len(anchors) >= 3 and (home_logo or bool(site_menu_class))


def is_chrome_like_position(node: Node) -> bool:
    return bool(node.find("a")) and len(normalize_space(node.text())) < 2500


def cluster_layouts(index: list[dict]) -> list[dict]:
    """Group routes whose section-class sets overlap ≥ 60% (Jaccard), seeded by path prefix."""
    clusters: list[dict] = []
    for item in sorted(index, key=lambda entry: (entry["lang"] != "en", entry["route"])):
        signature = set(item["layout_signature"])
        best, best_score = None, 0.0
        for cluster in clusters:
            union = signature | cluster["signature"]
            score = len(signature & cluster["signature"]) / len(union) if union else 1.0
            if score > best_score:
                best, best_score = cluster, score
        if best is not None and best_score >= 0.6 and best["kind"] == item["kind"]:
            best["routes"].append(item["route"])
            continue
        clusters.append({"signature": signature, "kind": item["kind"], "routes": [item["route"]]})
    result = []
    for number, cluster in enumerate(sorted(clusters, key=lambda entry: -len(entry["routes"])), 1):
        prefixes = Counter("/" + route.strip("/").split("/")[-2] if route.count("/") > 1 else "/" for route in cluster["routes"])
        result.append({
            "id": f"layout-{number:02d}",
            "kind": cluster["kind"],
            "size": len(cluster["routes"]),
            "common_parent": prefixes.most_common(1)[0][0],
            "example": cluster["routes"][0],
            "routes": cluster["routes"],
            "section_signature": sorted(cluster["signature"]),
        })
    return result


if __name__ == "__main__":
    sys.exit(main())
