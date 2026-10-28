"""Dependency-free HTML helpers shared by the anysite2grav scripts.

Builds a forgiving element tree on top of html.parser so the crawler, auditor
and extractor work on any Python 3.9+ without pip installs.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}
# Tags whose open element is implicitly closed when a sibling of the same kind starts.
AUTO_CLOSE = {
    "p": {"p", "div", "section", "ul", "ol", "table", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "form", "header", "footer", "nav", "figure"},
    "li": {"li"},
    "dt": {"dt", "dd"},
    "dd": {"dt", "dd"},
    "option": {"option", "optgroup"},
    "tr": {"tr"},
    "td": {"td", "th", "tr"},
    "th": {"td", "th", "tr"},
}
RAW_TEXT_TAGS = {"script", "style", "noscript", "template", "textarea"}
ASSET_EXTENSIONS = re.compile(
    r"\.(?:avif|bmp|css|csv|docx?|eot|gif|ico|jpe?g|js|json|m4a|mjs|mov|mp3|mp4|ogg|otf|pdf|png|pptx?|svg|ttf|txt|wav|webm|webp|woff2?|xlsx?|xml|zip)$",
    re.I,
)
DOCUMENT_EXTENSIONS = re.compile(r"\.(?:csv|docx?|pdf|pptx?|xlsx?|zip)$", re.I)


class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag: str, attrs: dict | None = None, parent: "Node | None" = None):
        self.tag = tag
        self.attrs = attrs or {}
        self.children: list = []
        self.parent = parent

    # --- queries -----------------------------------------------------------
    def iter(self):
        stack = [self]
        while stack:
            node = stack.pop()
            if isinstance(node, Node):
                yield node
                stack.extend(reversed(node.children))

    def find_all(self, *tags: str):
        wanted = set(tags)
        return [node for node in self.iter() if not wanted or node.tag in wanted]

    def find(self, *tags: str):
        for node in self.iter():
            if node.tag in tags:
                return node
        return None

    def get(self, name: str, default: str = "") -> str:
        value = self.attrs.get(name)
        return default if value is None else value

    @property
    def classes(self) -> list[str]:
        return self.get("class").split()

    def has_class(self, *names: str) -> bool:
        own = set(self.classes)
        return any(name in own for name in names)

    def ancestors(self):
        node = self.parent
        while node is not None:
            yield node
            node = node.parent

    def element_children(self):
        return [child for child in self.children if isinstance(child, Node)]

    def text(self, separator: str = " ") -> str:
        parts: list[str] = []

        # Inline elements join without spaces (as browsers render them); blocks and <br> break.
        def walk(node):
            for child in node.children:
                if isinstance(child, str):
                    parts.append(child)
                elif child.tag in RAW_TEXT_TAGS or child.tag == "svg":
                    continue
                elif child.tag == "br":
                    parts.append("\n" if separator == "\n" else " ")
                else:
                    block = child.tag in BLOCK_TAGS
                    if block:
                        parts.append(separator)
                    walk(child)
                    if block:
                        parts.append(separator)

        walk(self)
        return normalize_space("".join(parts))

    def remove(self):
        if self.parent is not None:
            self.parent.children = [child for child in self.parent.children if child is not self]
            self.parent = None

    def outer_signature(self) -> str:
        """Short structural fingerprint used to detect repeated site chrome."""
        return f"{self.tag}#{self.get('id')}.{'.'.join(sorted(self.classes))}"


BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "dd", "div", "dl", "dt", "fieldset", "figcaption",
    "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main",
    "nav", "ol", "p", "pre", "section", "table", "td", "th", "tr", "ul",
}


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#document")
        self.current = self.root

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        closers = {open_tag for open_tag, triggers in AUTO_CLOSE.items() if tag in triggers}
        if closers:
            for ancestor in [self.current, *self.current.ancestors()]:
                if ancestor.tag in closers:
                    self.current = ancestor.parent or self.root
                    break
                if ancestor.tag in BLOCK_TAGS and ancestor.tag not in closers:
                    break
        node = Node(tag, {name.lower(): (value if value is not None else "") for name, value in attrs}, self.current)
        self.current.children.append(node)
        if tag not in VOID_TAGS:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        node = Node(tag, {name.lower(): (value if value is not None else "") for name, value in attrs}, self.current)
        self.current.children.append(node)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in VOID_TAGS:
            return
        for node in [self.current, *self.current.ancestors()]:
            if node.tag == tag:
                self.current = node.parent or self.root
                return

    def handle_data(self, data):
        if data:
            self.current.children.append(data)


def parse_html(markup: str) -> Node:
    builder = _TreeBuilder()
    builder.feed(markup)
    builder.close()
    return builder.root


# --- text + url helpers -----------------------------------------------------

def normalize_space(value: str) -> str:
    value = html.unescape(value or "").replace(" ", " ")
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in value.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def site_key(host: str) -> str:
    host = (host or "").lower()
    return host[4:] if host.startswith("www.") else host


def normalize_url(raw: str, base: str, *, keep_query: bool = False) -> str | None:
    """Absolute, fragment-free URL; None for mailto/tel/javascript/data links."""
    if not raw:
        return None
    raw = html.unescape(raw.strip())
    if re.match(r"^(?:#|mailto:|tel:|sms:|javascript:|data:|blob:)", raw, re.I):
        return None
    try:
        parts = urlsplit(urljoin(base, raw))
    except ValueError:
        return None
    if parts.scheme not in ("http", "https"):
        return None
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    query = parts.query if keep_query else ""
    return urlunsplit((parts.scheme, parts.netloc.lower(), path, query, ""))


def route_of(url: str) -> str:
    path = urlsplit(url).path or "/"
    if len(path) > 1:
        path = path.rstrip("/")
    return path or "/"


def is_asset_url(url: str) -> bool:
    return bool(ASSET_EXTENSIONS.search(urlsplit(url).path))


def best_srcset_candidate(srcset: str, base: str) -> str | None:
    """Largest candidate from a srcset string (by width descriptor or density)."""
    best_url, best_score = None, -1.0
    for candidate in re.split(r",\s+(?=\S)", srcset or ""):
        bits = candidate.strip().split()
        if not bits:
            continue
        score = 1.0
        if len(bits) > 1:
            descriptor = bits[1].lower()
            try:
                score = float(descriptor[:-1]) * (1 if descriptor.endswith("w") else 1000)
            except ValueError:
                score = 1.0
        if score > best_score:
            best_url, best_score = bits[0], score
    return normalize_url(best_url, base, keep_query=True) if best_url else None


def image_source(node: Node, base: str) -> str | None:
    """Best original URL for an <img>, honoring lazy-load attributes and srcset."""
    for attribute in ("srcset", "data-srcset"):
        if node.get(attribute):
            candidate = best_srcset_candidate(node.get(attribute), base)
            if candidate:
                return candidate
    for attribute in ("data-src", "data-lazy-src", "data-original", "src"):
        value = node.get(attribute)
        if value and not value.startswith("data:"):
            return normalize_url(value, base, keep_query=True)
    return None


BACKGROUND_URL = re.compile(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)", re.I)


def background_images(node: Node, base: str) -> list[str]:
    urls = []
    for attribute in ("style", "data-bg", "data-background", "data-bg-src"):
        value = node.get(attribute)
        if not value:
            continue
        matches = BACKGROUND_URL.findall(value) or ([value] if attribute != "style" else [])
        for match in matches:
            absolute = normalize_url(match, base, keep_query=True)
            if absolute:
                urls.append(absolute)
    return urls


def slugify(value: str, fallback: str = "item") -> str:
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
    value = re.sub(r"['’]", "", value)
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:80] or fallback


def short_hash(value: str | bytes, length: int = 12) -> str:
    data = value.encode() if isinstance(value, str) else value
    return hashlib.sha256(data).hexdigest()[:length]


def html_cache_name(route: str) -> str:
    return f"{slugify(route.strip('/') or 'home', 'home')[:60]}-{short_hash(route, 8)}.html"


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, payload) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def meta_content(document: Node, *, name: str | None = None, prop: str | None = None) -> str | None:
    for meta in document.find_all("meta"):
        if name and meta.get("name").lower() == name:
            return normalize_space(meta.get("content")) or None
        if prop and meta.get("property").lower() == prop:
            return normalize_space(meta.get("content")) or None
    return None
