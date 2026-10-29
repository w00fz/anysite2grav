#!/usr/bin/env python3
"""Generate Grav pages, media, redirects and language config from the extracted content.

Usage:
  build_pages.py migration --grav grav [--languages auto|native|trees] [--template-map map.json]
                 [--modular auto|off] [--modular-threshold 3] [--keep-sample-pages] [--dry-run] [--allow-incomplete]

What it does (idempotent; rerun after improving extraction or the template map):
  * one Grav page folder per source route, preserving every URL; numeric folder prefixes follow
    the source menu order; missing parents become non-routable folders
  * frontmatter: title, head_title (exact source <title>), menu label, metadata/OG,
    source provenance, template, `sections` (structured blocks) or a Markdown body (articles)
  * composed pages with more than --modular-threshold visible sections (default 3) become Grav
    modular pages: modular.<lang>.md plus one module per section (NN._name/<kind>.<lang>.md, kinds
    hero|section|cards|gallery|form|shared) with that module's media beside it; shorter pages
    keep every section in one page's `sections` frontmatter
  * media: page-only assets beside the page, repeated assets in user/media/images
    (media://images/…), documents in user/media/files; links to the old origin become local
  * shared sections (newsletter bands, CTA strips) become non-routable pages under /shared
  * languages: native Grav multilang (page.<lang>.md, system.yaml languages) or separate trees
  * redirects observed on the source → system.yaml pages.redirects
  * writes migration/page-map.json (route → folder/file/template) for later steps

--template-map JSON: {"<cluster id or ^route-regex>": "<template>", ...}; first match wins.
Default templates: "sections" for composed pages, "default" for articles/legal text, "modular"
for composed pages over the threshold. Mapped templates are never made modular.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gravkit import merge_config, write_page  # noqa: E402
import layoutkit  # noqa: E402
from htmlkit import read_json, route_of, site_key, slugify, write_json  # noqa: E402

LANG_PREFIX = re.compile(r"^/([a-z]{2}(?:-[a-z]{2,4})?)(?=/|$)", re.I)
# Grav treats a folder whose slug (name minus the "NN." order prefix) starts with "_" as a module.
MODULE_FOLDER = re.compile(r"^(\d+\.)?_")


class Builder:
    def __init__(self, args):
        self.args = args
        self.migration = Path(args.migration)
        self.grav = Path(args.grav)
        self.pages_dir = self.grav / "user" / "pages"
        self.routes = read_json(self.migration / "routes.json")
        self.index = read_json(self.migration / "content-index.json")
        self.chrome = read_json(self.migration / "chrome.json") if (self.migration / "chrome.json").exists() else {}
        self.shared = read_json(self.migration / "shared-sections.json") if (self.migration / "shared-sections.json").exists() else {}
        self.manifest = read_json(self.migration / "media-manifest.json") if (self.migration / "media-manifest.json").exists() else {}
        self.template_map = read_json(Path(args.template_map)) if args.template_map else {}
        self.site = site_key(urlsplit(self.routes["source"]).hostname or "")
        self.records = {item["route"]: read_json(self.migration / item["file"]) for item in self.index["pages"]}
        self.cluster_of = {route: cluster["id"] for cluster in self.index["clusters"] for route in cluster["routes"]}
        home = self.records.get("/")
        self.default_lang = (home or {}).get("lang") or Counter(record["lang"] for record in self.records.values()).most_common(1)[0][0]
        self.languages = sorted({record["lang"] for record in self.records.values() if record["lang"] and record["lang"] != "x"})
        self.mode = self.resolve_language_mode()
        self.copied: dict[str, str] = {}
        self.stats = Counter()
        self.unresolved_controls = []
        self.current_source_route = None
        self.current: tuple | None = None  # (folder, logical route, lang) of the page being written
        self.current_heading: str | None = None
        self.collection_names_used: set[str] = set()
        self.item_meta: dict[str, dict] = {}  # imported item pages → listing date/terms/image
        # Measured source layout (measure_layout.mjs): section/block styles, type scale, fonts.
        self.layout = layoutkit.load(self.migration)
        self.scale = layoutkit.type_scale(self.layout)
        self.roles = layoutkit.font_roles(self.layout)
        self.header_variants = layoutkit.header_variants(self.layout)
        self.current_layout: dict = {}
        self.current_text: tuple[dict, dict] = ({}, {})
        self.current_modals: set[str] = set()

    # --- languages ------------------------------------------------------------
    def counterpart(self, record: dict) -> str | None:
        """Default-language route for a localized page, via hreflang then prefix stripping."""
        if record["lang"] == self.default_lang:
            return record["route"]
        for alternate in record.get("hreflang", []):
            code = (alternate.get("hreflang") or "").split("-")[0].lower()
            if code in (self.default_lang, "x-default") and alternate.get("href"):
                candidate = route_of(alternate["href"])
                if candidate in self.records and candidate != record["route"]:
                    return candidate
        match = LANG_PREFIX.match(record["route"])
        if match and match.group(1).split("-")[0].lower() == record["lang"]:
            stripped = record["route"][match.end():] or "/"
            if stripped in self.records:
                return stripped
        return None

    def resolve_language_mode(self) -> str:
        if len(self.languages) <= 1:
            return "single"
        if self.args.languages != "auto":
            return self.args.languages
        localized = [record for record in self.records.values() if record["lang"] != self.default_lang]
        mapped = sum(1 for record in localized if self.counterpart(record))
        return "native" if localized and mapped / len(localized) >= 0.8 else "trees"

    def logical_route(self, record: dict) -> str:
        """Route used for the folder tree (localized routes collapse onto their counterpart in native mode)."""
        if self.mode != "native" or record["lang"] == self.default_lang:
            return record["route"]
        counterpart = self.counterpart(record)
        if counterpart:
            return counterpart
        match = LANG_PREFIX.match(record["route"])
        return (record["route"][match.end():] or "/") if match else record["route"]

    # --- templates --------------------------------------------------------------
    def template_for(self, route: str, record: dict) -> str:
        cluster = self.cluster_of.get(route)
        for key, template in self.template_map.items():
            if key == cluster or (key.startswith("^") and re.search(key, route)):
                return template
        return "default" if record["kind"] == "article" else "sections"

    # --- folders ------------------------------------------------------------------
    def menu_order(self) -> dict[str, int]:
        order: dict[str, int] = {}
        chrome = self.chrome.get(self.default_lang) or next(iter(self.chrome.values()), {})
        position = 1
        for item in chrome.get("menu", []):
            for entry in [item, *item.get("children", [])]:
                url = entry.get("url")
                if url and site_key(urlsplit(url).hostname or "") == self.site:
                    first = "/" + route_of(url).strip("/").split("/")[0]
                    if first not in order and first != "/":
                        order[first] = position
                        position += 1
        return order

    def folder_for(self, logical: str) -> Path:
        if logical == "/":
            return self.pages_dir / "01.home"
        order = self.menu_order_cache
        parts = logical.strip("/").split("/")
        folders = []
        for depth, part in enumerate(parts):
            name = part
            if depth == 0 and ("/" + part) in order:
                name = f"{order['/' + part] + 1:02d}.{part}"
            folders.append(name)
        return self.pages_dir.joinpath(*folders)

    # --- media + links ----------------------------------------------------------
    def media_ref(self, url: str, page_folder: Path | None) -> str:
        entry = self.manifest.get(url)
        if not entry or entry.get("error"):
            self.stats["media_unresolved"] += 1
            return url
        source = self.migration / "media-cache" / entry["file"]
        clean = re.sub(r"^[0-9a-f]{12}-", "", entry["file"])
        scope = entry.get("scope", "shared")
        if scope == "page" and page_folder is not None:
            target, reference = page_folder / clean, clean
        elif scope == "document":
            target = self.grav / "user" / "media" / "files" / clean
            reference = f"/user/media/files/{clean}"
        else:
            target = self.grav / "user" / "media" / "images" / clean
            reference = f"media://images/{clean}"
        # Two different files that share a clean name keep their hash prefix.
        if self.copied.get(str(target), entry["sha256"]) != entry["sha256"]:
            target = target.with_name(entry["file"])
            reference = reference.rsplit("/", 1)[0] + "/" + entry["file"] if "/" in reference else entry["file"]
        if not self.args.dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copyfile(source, target)
        self.copied[str(target)] = entry["sha256"]
        return reference

    def local_link(self, url: str | None) -> str | None:
        if not url:
            return url
        parts = urlsplit(url)
        if parts.scheme in ("http", "https") and site_key(parts.hostname or "") == self.site:
            if url in self.manifest and self.manifest[url].get("scope") == "document":
                return self.media_ref(url, None)
            path = parts.path or "/"
            return path + (f"?{parts.query}" if parts.query else "") + (f"#{parts.fragment}" if parts.fragment else "")
        return url

    def rewrite_markdown(self, text: str, page_folder: Path | None) -> str:
        def link(match):
            label, target = match.group(1), match.group(2)
            if target in self.manifest and self.manifest[target].get("scope") != "document":
                return f"[{label}]({self.media_ref(target, page_folder)})"
            return f"[{label}]({self.local_link(target)})"

        # URLs may contain balanced parentheses (e.g. "image%20(33).jpg").
        target = r"((?:[^()\s]|\([^()\s]*\))+)"
        text = re.sub(r"!\[([^\]]*)\]\(" + target + r"\)", lambda match: f"![{match.group(1)}]({self.media_ref(match.group(2), page_folder)})", text)
        return re.sub(r"(?<!!)\[([^\]]*)\]\(" + target + r"\)", link, text)

    def rewrite_blocks(self, blocks: list[dict], page_folder: Path | None) -> list[dict]:
        output = []
        headings, paragraphs = self.current_text
        for block in blocks:
            block = dict(block)
            if block.get("type") == "heading" and headings:
                block.update(headings.get(layoutkit.plain(block.get("text"))[:60], {}))
            if block.get("type") == "text" and paragraphs:
                block.update(paragraphs.get(layoutkit.plain(block.get("text"))[:60], {}))
            if block.get("_path") and block.get("type") in ("columns", "cards", "list"):
                block.update(layoutkit.block_style(self.current_layout.get("blocks", {}).get(block["_path"]), block["type"]))
            if block.get("type") == "button" and not block.get("href") and not block.get("modal"):
                target = (block.get("action") or "").lstrip("#")
                if target and target in self.current_modals:
                    block["modal"] = target
                    block.pop("action", None)
                else:
                    self.unresolved_controls.append({
                        "route": self.current_source_route,
                        "label": block.get("label"), "action": block.get("action"),
                        "target": block.get("_target"), "source_path": block.get("_path"),
                    })
                    self.stats["dead_controls"] += 1
                    if block.get("_target") in ("dialog", "missing"):
                        continue
            if block.get("type") == "image" and block.get("src"):
                block["src"] = self.media_ref(block["src"], page_folder)
            if block.get("sources"):
                block["sources"] = [self.media_ref(source, page_folder) for source in block["sources"]]
            if block.get("poster"):
                block["poster"] = self.media_ref(block["poster"], page_folder)
            if block.get("text"):
                block["text"] = self.rewrite_markdown(block["text"], page_folder)
            if block.get("items") and block.get("type") == "list":
                block["items"] = [self.rewrite_markdown(item, page_folder) for item in block["items"]]
            if block.get("href"):
                block["href"] = self.local_link(block["href"])
            for dimension in ("width", "height"):
                if dimension in block and not str(block[dimension]).isdigit():
                    block.pop(dimension)
            if block.get("type") == "gallery":
                block["images"] = [{**image, "src": self.media_ref(image["src"], page_folder), **({"href": self.local_link(image["href"])} if image.get("href") else {})} for image in block["images"]]
            if block.get("type") == "cards":
                block["cards"] = [{**card, "blocks": self.rewrite_blocks(card["blocks"], page_folder), **({"href": self.local_link(card["href"])} if card.get("href") else {})} for card in block["cards"]]
                block["cards"] = [card for card in block["cards"] if card["blocks"]]
                if not block["cards"]:
                    continue
            if block.get("type") == "columns":
                block["columns"] = [{**column, "blocks": self.rewrite_blocks(column["blocks"], page_folder)} for column in block["columns"]]
            if block.get("type") == "listing":
                block = self.listing_block(block, page_folder)
            if block.get("type") == "form":
                block["form"] = self.form_names.get(block.pop("ref"), block.get("ref"))
            # `_path` and other underscore keys are extraction bookkeeping (layout capture), never frontmatter.
            output.append({key: value for key, value in block.items() if value not in (None, "", []) and not key.startswith("_")})
        return output

    # --- collections ----------------------------------------------------------------
    def listing_block(self, block: dict, page_folder: Path | None) -> dict:
        """A listing becomes a Grav collection block. Its items are real pages, so pagination,
        taxonomy filters, ordering and Admin editing come from Grav instead of a frozen card list."""
        if self.args.collections == "off" or self.current is None:
            items = []
            for item in block["items"]:
                entry = {key: item.get(key) for key in ("title", "date", "excerpt")}
                entry["href"] = self.local_link(item["href"])
                entry["image"] = self.media_ref(item["image"], page_folder) if item.get("image") else None
                entry["terms"] = [term["label"] for term in item.get("terms", [])] or None
                items.append({key: value for key, value in entry.items() if value})
            return {"type": "listing", "style": block.get("style"), "items": items}
        folder, logical, lang = self.current
        measured = self.current_layout.get("blocks", {}).get(block.get("_path") or "")
        routes = [route_of(item["href"]) for item in block["items"]]
        built = [route for route in routes if route in self.records]
        collection = {
            "type": "collection",
            "style": block.get("style") or "list",
            "order": {"by": "default", "dir": "asc"},
            "limit": (block.get("pagination") or {}).get("per_page") or len(block["items"]),
            "pagination": True if block.get("pagination") else None,
            "taxonomy": block.get("taxonomy"),
            "search": block.get("search") or None,
            # Only the collection that owns the URL filters reacts to /category:x, so other
            # collections and the modules of a modular page are never filtered away.
            "url_taxonomy_filters": True if block.get("taxonomy") else None,
            **layoutkit.block_style(measured, "collection"),
        }
        if measured and measured.get("title"):
            collection["title_size"] = layoutkit.size_step(measured["title"]["size"], self.scale)
            if str(measured["title"].get("weight")) not in ("400", "normal", ""):
                collection["title_weight"] = str(measured["title"]["weight"])
            role = layoutkit.family_role(measured["title"]["family"], self.roles)
            if role and role != "heading":
                collection["title_font"] = role
        if routes and len(built) >= 0.8 * len(routes):
            # The items were imported as pages: list them where they live, newest first.
            common = built[0].strip("/").split("/")[:-1]
            for route in built[1:]:
                parts = route.strip("/").split("/")[:-1]
                common = [part for part, other in zip(common, parts) if part == other]
            for item in block["items"]:
                self.item_meta[route_of(item["href"])] = item
            collection.update({"from": "/" + "/".join(common), "descendants": True, "order": {"by": "date", "dir": "desc"}})
        else:
            name = self.collection_name()
            collection["from"] = self.grav_route(folder / name)
            self.write_collection_items(folder / name, name, block, lang)
        self.stats["collections"] += 1
        return {key: value for key, value in collection.items() if value is not None}

    def grav_route(self, folder: Path) -> str:
        """The route Grav gives a page folder: path below pages/ without NN. prefixes (home is /home)."""
        parts = [re.sub(r"^\d+\.", "", part) for part in folder.relative_to(self.pages_dir).parts]
        return "/" + "/".join(parts)

    def collection_name(self) -> str:
        base = slugify(plain_text(self.current_heading or ""), "")[:32].strip("-") or "items"
        name, counter = base, 2
        while name in self.collection_names_used:
            name, counter = f"{base}-{counter}", counter + 1
        self.collection_names_used.add(name)
        return name

    def write_collection_items(self, items_folder: Path, name: str, block: dict, lang: str):
        """Item records for a listing whose items weren't imported (a scoped copy, a CMS feed):
        title, date, taxonomy, image, summary and the original link, plus the card's own text."""
        keep = set()
        for position, item in enumerate(block["items"], 1):
            slug = slugify(item["title"], f"item-{position}")[:48].strip("-") or f"item-{position}"
            item_folder = items_folder / f"{position:02d}.{slug}"
            keep.add(item_folder.name)
            image = self.media_ref(item["image"], item_folder) if item.get("image") else None
            header = {
                "title": item["title"],
                "date": item.get("date"),
                "taxonomy": {"category": [term["label"] for term in item.get("terms", [])]} if item.get("terms") else None,
                "image": image,
                "summary": item.get("excerpt"),
                # Items link where the source card linked; the record itself isn't a public page.
                "link": self.local_link(item["href"]),
                "routable": False,
                "source": {"url": item["href"]},
            }
            blocks = [
                entry for entry in self.rewrite_blocks(item.get("blocks", []), item_folder)
                if not (entry.get("type") == "heading" and plain_text(entry.get("text")) == item["title"])
                and not (entry.get("type") == "image" and image and entry.get("src") == image)
            ]
            body = markdown_from_sections([{"type": "section", "blocks": blocks}])
            if not self.args.dry_run:
                write_page(item_folder / self.file_name("item", lang), {key: value for key, value in header.items() if value not in (None, [], {})}, body)
            self.stats["collection_items"] += 1
        if not self.args.dry_run:
            write_page(items_folder / self.file_name("default", lang), {"title": plain_text(self.current_heading or name.replace("-", " ").capitalize()), "routable": False, "visible": False})
            for stale in items_folder.iterdir():
                if stale.is_dir() and stale.name not in keep:
                    for file in stale.glob(f"*.{lang}.md" if self.mode == "native" else "*.md"):
                        file.unlink()
                    if not any(stale.glob("*.md")):
                        shutil.rmtree(stale)

    # --- modular pages ------------------------------------------------------------
    def is_hidden(self, section: dict) -> bool:
        """Popups (own or shared) render as dialogs, not as horizontal sections."""
        if "shared" in section:
            return bool(self.shared.get(section["shared"], {}).get("modal"))
        return bool(section.get("modal"))

    def module_kind(self, section: dict, lead: bool) -> str:
        """lead: the first visible section after any section menu, the only hero candidate."""
        if "shared" in section:
            return "shared"
        blocks = section.get("blocks", [])
        types = {block["type"] for block in blocks}
        if lead and (section.get("backgrounds") or section.get("background_video") or any(block["type"] == "heading" and block.get("level") == 1 for block in blocks)):
            return "hero"
        if "form" in types:
            return "form"
        if "cards" in types:
            return "cards"
        if "gallery" in types:
            return "gallery"
        return "section"

    def module_plan(self, record: dict, template: str) -> list[tuple[str, str]] | None:
        """[(folder, kind)] for a page that should be modular, else None.

        Decided on the default-language record so every translation shares one module tree.
        """
        if self.args.modular == "off" or template != "sections" or record["kind"] == "article":
            return None
        visible = [section for section in record["sections"] if not self.is_hidden(section)]
        if len(visible) <= self.args.modular_threshold or any(section.get("body") for section in visible):
            return None
        plan, used = [], set()
        lead = self.lead_index(visible)
        for position, section in enumerate(visible):
            kind = self.module_kind(section, position == lead)
            if kind == "shared":
                name = self.shared_names.get(section["shared"], "shared")
            elif kind == "hero":
                name = "hero"
            elif section.get("role") == "subnav":
                name = "subnav"
            else:
                heading = first_heading(section.get("blocks", []))
                name = slugify(plain_text(heading), "")[:32].strip("-") or section.get("id") or kind
            base, counter = name, 2
            while name in used:
                name, counter = f"{base}-{counter}", counter + 1
            used.add(name)
            plan.append((f"{position + 1:02d}._{name}", kind))
        return plan

    @staticmethod
    def lead_index(visible: list[dict]) -> int:
        return next((index for index, section in enumerate(visible) if section.get("role") != "subnav"), 0)

    def section_entry(self, section: dict, folder: Path) -> dict:
        self.current_heading = first_heading(section.get("blocks", []))
        if "shared" in section:
            return {"type": "shared", "shared": self.shared_names.get(section["shared"], section["shared"])}
        if section.get("body"):
            return {key: value for key, value in {"type": "body", "id": section.get("id"), "classes": section.get("classes")}.items() if value}
        metrics = self.current_layout.get("sections", {}).get(section.get("_path") or "")
        measured = layoutkit.section_style(metrics)
        measured.pop("background_color", None)
        if any(block.get("type") == "columns" for block in section.get("blocks", [])):
            # The split was measured on the columns block itself; the section stays stacked.
            for key in ("layout", "ratio", "split_divider"):
                measured.pop(key, None)
        self.current_text = layoutkit.text_styles(metrics, self.scale, self.roles)
        entry = {
            "type": "section",
            "id": section.get("id"),
            "classes": section.get("classes"),
            # Measured values (computed styles on the source) beat what the CSS alone suggested.
            "tone": measured.get("tone", section.get("tone")),
            "space": measured.get("space", section.get("space")),
            "divider": measured.get("divider"),
            "align": measured.get("align"),
            "layout": measured.get("layout"),
            "ratio": measured.get("ratio"),
            "split_divider": measured.get("split_divider"),
            "role": section.get("role"),
            "modal": section.get("modal") or None,
            "background": self.media_ref(section["backgrounds"][0], folder) if section.get("backgrounds") else None,
            "background_video": self.rewrite_blocks([section["background_video"]], folder)[0] if section.get("background_video") else None,
            "blocks": self.rewrite_blocks(section["blocks"], folder),
        }
        if entry["modal"] and not entry["id"]:
            # Stable dialog id (modal-<id>) so buttons can target it across rebuilds.
            heading = next((block["text"] for block in section["blocks"] if block["type"] == "heading"), None)
            entry["id"] = slugify(re.sub(r"[*\[\]()]", "", heading or "popup"), "popup")[:40]
        self.current_text = ({}, {})
        return {key: value for key, value in entry.items() if value not in (None, [], "")}

    def write_modules(self, folder: Path, plan: list[tuple[str, str]] | None, record: dict, lang: str) -> list[dict]:
        """Write one module per visible section and drop this language's stale module files."""
        written, keep = [], set()
        if plan:
            visible = [section for section in record["sections"] if not self.is_hidden(section)]
            for position, section in enumerate(visible):
                if position < len(plan):
                    module_folder_name, kind = plan[position]
                else:
                    # A translation with more sections than the default language keeps them, in order.
                    kind = self.module_kind(section, position == self.lead_index(visible))
                    module_folder_name = f"{position + 1:02d}._{kind}-{position + 1}"
                module_folder = folder / module_folder_name
                entry = self.section_entry(section, module_folder)
                heading = first_heading(entry.get("blocks", []))
                title = plain_text(heading)[:80]
                header = {"title": title or module_folder_name.split("._", 1)[1].replace("-", " ").capitalize()}
                if kind == "shared":
                    header["shared"] = entry["shared"]
                else:
                    header.update({key: entry.get(field) for key, field in (
                        ("anchor", "id"), ("tone", "tone"), ("space", "space"), ("divider", "divider"), ("align", "align"),
                        ("layout", "layout"), ("ratio", "ratio"), ("split_divider", "split_divider"), ("role", "role"), ("classes", "classes"),
                        ("background", "background"), ("background_video", "background_video"), ("blocks", "blocks"),
                    )})
                if any(block.get("type") == "collection" for block in iter_blocks(entry.get("blocks", []))):
                    # A module's rendered HTML is cached with its content; collections depend on the URL
                    # (page:2, category:x, ?q=), so this module renders on every request.
                    header["cache_enable"] = False
                target = module_folder / self.file_name(kind, lang)
                if not self.args.dry_run:
                    for stale in module_folder.glob(f"*.{lang}.md" if self.mode == "native" else "*.md"):
                        if stale != target and stale.name.count(".") == target.name.count("."):
                            stale.unlink()
                    write_page(target, {key: value for key, value in header.items() if value not in (None, [], "")})
                keep.add(module_folder.name)
                written.append({"folder": str(module_folder.relative_to(self.grav)), "file": target.name, "template": f"modular/{kind}"})
                self.stats["modules"] += 1
        if not self.args.dry_run and folder.exists():
            for module_folder in folder.iterdir():
                if module_folder.is_dir() and MODULE_FOLDER.match(module_folder.name) and module_folder.name not in keep:
                    for stale in module_folder.glob(f"*.{lang}.md" if self.mode == "native" else "*.md"):
                        stale.unlink()
                    if not any(module_folder.glob("*.md")):
                        shutil.rmtree(module_folder)
        return written

    # --- build --------------------------------------------------------------------
    def shared_ids(self) -> dict[str, str]:
        """Map every shared-section id to a stable slug shared by its translations."""
        names: dict[str, str] = {}
        by_classes: dict[tuple, str] = {}
        for shared_id, section in sorted(self.shared.items(), key=lambda item: item[1]["lang"] != self.default_lang):
            key = tuple(section["classes"])
            if self.mode == "native" and key in by_classes and section["lang"] != self.default_lang:
                names[shared_id] = by_classes[key]
                continue
            heading = next((block.get("text") for block in section["blocks"] if block["type"] == "heading"), None)
            slug = slugify(heading or "-".join(section["classes"][:2]) or shared_id, shared_id)[:40]
            base, counter = slug, 2
            while slug in names.values() and (self.mode != "native" or section["lang"] == self.default_lang):
                slug, counter = f"{base}-{counter}", counter + 1
            names[shared_id] = slug if self.mode == "native" or section["lang"] == self.default_lang else f"{slug}-{section['lang']}"
            by_classes.setdefault(key, names[shared_id])
        return names

    def file_name(self, template: str, lang: str) -> str:
        if self.mode == "native":
            return f"{template}.{lang}.md"
        return f"{template}.md"

    def run(self):
        audit = read_json(self.migration / "audit.json") if (self.migration / "audit.json").exists() else {"forms": []}
        # Same builder name in different languages = one multilingual form; same name twice in one
        # language = two different forms, so the second gets a suffix instead of overwriting the first.
        self.form_names, taken = {}, defaultdict(set)
        for index, form in enumerate(audit.get("forms", []), 1):
            base = slugify(form.get("name") or f"form-{index}", f"form-{index}")
            langs = {self.records[route]["lang"] for route in form["pages"] if route in self.records} or {self.default_lang}
            name, counter = base, 2
            while any(name in taken[lang] for lang in langs):
                name, counter = f"{base}-{counter}", counter + 1
            for lang in langs:
                taken[lang].add(name)
            self.form_names[form["signature"]] = name
        self.menu_order_cache = self.menu_order()
        if not self.args.keep_sample_pages and not self.args.dry_run:
            for sample in ("01.home", "02.typography"):
                path = self.pages_dir / sample
                if path.exists() and any(child.name in ("default.md",) for child in path.iterdir()) and "Grav" in (path / "default.md").read_text():
                    shutil.rmtree(path)

        menu_labels = {}
        chrome = self.chrome.get(self.default_lang, {})
        for item in chrome.get("menu", []):
            for entry in [item, *item.get("children", [])]:
                if entry.get("url"):
                    menu_labels.setdefault(route_of(entry["url"]), entry["label"])

        # Imported item pages (posts listed on /news…) take their date, category and image from the
        # listing, so collections can sort and filter them.
        for record in self.records.values():
            for section in record["sections"]:
                for block in iter_blocks(section.get("blocks", [])):
                    if block.get("type") == "listing":
                        for item in block["items"]:
                            if route_of(item["href"]) in self.records:
                                self.item_meta.setdefault(route_of(item["href"]), item)

        page_map = {}
        folders_with_pages = set()
        for route, record in sorted(self.records.items()):
            self.current_source_route = route
            logical = self.logical_route(record)
            folder = self.folder_for(logical)
            lang = record["lang"] if self.mode == "native" else self.default_lang
            anchor_record = self.records.get(logical, record)
            template = self.template_for(logical if logical in self.records else route, anchor_record)
            plan = self.module_plan(anchor_record, template)
            if plan:
                template = "modular"
            self.current = (folder, logical, lang)
            self.collection_names_used = set()
            self.current_modals = {section.get("id") for section in record["sections"] if section.get("modal") and section.get("id")}
            # Translations reuse their default-language counterpart's measurements.
            self.current_layout = self.layout.get(route) or self.layout.get(logical) or {}
            # Modular pages keep only their popups here; every visible section becomes a module.
            sections = [self.section_entry(section, folder) for section in record["sections"] if not plan or self.is_hidden(section)]
            visible_heading = next((block["text"] for section in record["sections"] if "blocks" in section and not section.get("modal") for block in section["blocks"] if block["type"] == "heading" and block.get("level") == 1), None)
            # Source <title> minus a trailing " | Brand" is what editors recognise; the hero H1 stays in sections.
            source_title = re.split(r"\s+[|–—-]\s+", record.get("title") or "")[0].strip() if record.get("title") else None
            title = source_title or visible_heading or logical.strip("/").split("/")[-1].replace("-", " ").title()
            title = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", title).replace("**", "").replace("  \n", " ")
            title = title.split("\n")[0][:120]
            header = {
                "title": title,
                # Exact source <title>, so the browser title and search snippet stay 1:1.
                "head_title": record.get("title") or None,
                "menu": menu_labels.get(route),
                "metadata": {key: value for key, value in {
                    "description": record.get("description"),
                    "og:title": record.get("og", {}).get("title"),
                    "og:description": record.get("og", {}).get("description"),
                    "og:image": self.media_ref(record["og"]["image"], folder) if record.get("og", {}).get("image") else None,
                    "og:type": record.get("og", {}).get("type"),
                }.items() if value} or None,
                "source": {"url": record["url"], "crawled_at": self.routes["crawled_at"], "layout": self.cluster_of.get(route)},
                "forms": record.get("forms") and [self.form_names.get(ref, ref) for ref in record["forms"]] or None,
            }
            if self.mode == "trees" and record["lang"] != self.default_lang:
                header["language"] = record["lang"]
            if self.header_variants.get("routes", {}).get(route) or self.header_variants.get("routes", {}).get(logical):
                # This page's source header uses the alternate colors (e.g. dark on inner pages).
                header["header_variant"] = "alt"
            listed = self.item_meta.get(route)
            if listed:
                header["date"] = listed.get("date")
                header["taxonomy"] = {"category": [term["label"] for term in listed.get("terms", [])]} if listed.get("terms") else None
                header["image"] = self.media_ref(listed["image"], folder) if listed.get("image") else None
                header["summary"] = listed.get("excerpt")
            body = ""
            if template == "default" or record["kind"] == "article":
                body = self.rewrite_markdown(record.get("body_markdown") or markdown_from_sections(sections), folder)
                if not record.get("body_markdown"):
                    sections = [section for section in sections if section["type"] != "section"]
            # Articles keep their hero/related/CTA sections; a {type: body} block marks where the Markdown goes.
            header["sections"] = sections
            if plan:
                # url_taxonomy_filters: false keeps /page/category:x from filtering the modules away.
                header["content"] = {"items": "@self.modular", "order": {"by": "default", "dir": "asc"}, "url_taxonomy_filters": False}
            if any(block.get("type") == "body" for section in sections for block in section.get("blocks", [])) or any(section.get("type") == "body" for section in sections):
                header["body_slot"] = True
            header = {key: value for key, value in header.items() if value not in (None, [], {})}
            target = folder / self.file_name(template, lang)
            if not self.args.dry_run:
                for stale in folder.glob(f"*.{lang}.md" if self.mode == "native" else "*.md"):
                    if stale != target and stale.name.count(".") == target.name.count("."):
                        stale.unlink()
                write_page(target, header, body)
            modules = self.write_modules(folder, plan, record, lang)
            folders_with_pages.add(folder)
            page_map[route] = {"folder": str(folder.relative_to(self.grav)), "file": target.name, "template": template, "lang": record["lang"], "logical_route": logical}
            if modules:
                page_map[route]["modules"] = modules
                self.stats["modular"] += 1
            self.stats["pages"] += 1

        # Non-routable parents for nested routes whose parent page does not exist at the source.
        for folder in sorted(folders_with_pages):
            parent = folder.parent
            while parent != self.pages_dir and parent not in folders_with_pages:
                stub = parent / (f"default.{self.default_lang}.md" if self.mode == "native" else "default.md")
                if not self.args.dry_run and not any(parent.glob("*.md")):
                    write_page(stub, {"title": re.sub(r"^\d+\.", "", parent.name).replace("-", " ").title(), "routable": False, "visible": False})
                    self.stats["parents"] += 1
                folders_with_pages.add(parent)
                parent = parent.parent

        # Shared sections as non-routable pages under /shared.
        for shared_id, section in self.shared.items():
            self.current_source_route = section.get("routes", [])
            name = self.shared_names[shared_id]
            folder = self.pages_dir / "shared" / name
            lang = section["lang"] if self.mode == "native" else self.default_lang
            shared_section = {"type": "section", "classes": section["classes"], "tone": section.get("tone"), "modal": section.get("modal") or None, "blocks": self.rewrite_blocks(section["blocks"], None)}
            heading = next((block.get("text") for block in section["blocks"] if block["type"] == "heading"), None)
            header = {"title": re.sub(r"[*\[\]]|\(.*?\)", "", heading).strip() if heading else name.replace("-", " ").capitalize(), "routable": False, "visible": False, "sections": [{key: value for key, value in shared_section.items() if value is not None}], "used_on": section["routes"]}
            if not self.args.dry_run:
                write_page(folder / self.file_name("sections", lang), header)
        if self.shared and not self.args.dry_run:
            write_page(self.pages_dir / "shared" / (f"default.{self.default_lang}.md" if self.mode == "native" else "default.md"), {"title": "Shared sections", "routable": False, "visible": False})

        if not self.args.dry_run:
            self.write_config()
        write_json(self.migration / "page-map.json", {"mode": self.mode, "default_lang": self.default_lang, "languages": self.languages, "pages": page_map, "shared": self.shared_names, "forms": self.form_names})
        write_json(self.migration / "unresolved-controls.json", self.unresolved_controls)
        if self.unresolved_controls:
            print(f"DRAFT INCOMPLETE: {len(self.unresolved_controls)} controls need implementation; see {self.migration / 'unresolved-controls.json'}")
        print(f"{self.stats['pages']} page files ({self.mode} languages: {self.languages or [self.default_lang]}), {self.stats['modular']} modular ({self.stats['modules']} module files), {self.stats['parents']} non-routable parents, {len(self.shared)} shared sections, {self.stats['collections']} collections ({self.stats['collection_items']} item records), {self.stats['dead_controls']} unresolved controls in draft, {self.stats['media_unresolved']} unresolved media refs" + (" [dry run]" if self.args.dry_run else ""))

    def write_config(self):
        redirects = {}
        for redirect in read_json(self.migration / "redirects.json") if (self.migration / "redirects.json").exists() else []:
            if redirect["from"] != redirect["to"] and redirect["from"] not in self.records:
                redirects[redirect["from"]] = f"{redirect['to']}[{redirect['status'] if redirect['status'] in (301, 302, 303, 307, 308) else 301}]"
        system = {"pages": {"redirects": redirects}} if redirects else {}
        if self.mode == "native":
            system["languages"] = {
                "supported": [self.default_lang] + [lang for lang in self.languages if lang != self.default_lang],
                "default_lang": self.default_lang,
                "include_default_lang": False,
                "include_default_lang_file_extension": True,
                "translations": True,
                "session_store_active": False,
                "http_accept_language": False,
                "pages_fallback_only": False,
            }
        if system:
            merge_config(self.grav, "user/config/system.yaml", system)
        home = self.records.get("/", {})
        title = (home.get("og") or {}).get("title") or home.get("title") or self.site
        site_title = title.split("|")[0].split(" - ")[0].strip()
        merge_config(self.grav, "user/config/site.yaml", {"title": site_title, "author": {"name": site_title, "email": ""}, "metadata": {"description": home.get("description") or ""}})

    @property
    def shared_names(self):
        if not hasattr(self, "_shared_names"):
            self._shared_names = self.shared_ids()
        return self._shared_names


def iter_blocks(blocks: list[dict]):
    """Every block, including those nested in columns and cards."""
    for block in blocks:
        yield block
        for inner in block.get("columns", []) + block.get("cards", []):
            yield from iter_blocks(inner.get("blocks", []))


def first_heading(blocks: list[dict]) -> str | None:
    """First heading text, looking inside columns and cards (side-by-side layouts put it there)."""
    for block in blocks:
        if block.get("type") == "heading":
            return block.get("text")
        for inner in block.get("columns", []) + block.get("cards", []):
            found = first_heading(inner.get("blocks", []))
            if found:
                return found
    return None


def plain_text(markdown: str | None) -> str:
    """First line of a Markdown snippet without links or emphasis (for titles and folder names)."""
    text = re.sub(r"\[([^\]]*)\]\((?:[^()\s]|\([^()\s]*\))+\)", r"\1", markdown or "")
    return re.sub(r"[*_`]", "", text).replace("  \n", " ").split("\n")[0].strip()


def markdown_from_sections(sections: list[dict]) -> str:
    from extract_content import markdown_from_blocks

    return "\n\n".join(markdown_from_blocks(section.get("blocks", [])) for section in sections if section.get("type") == "section")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("migration", nargs="?", default="migration")
    parser.add_argument("--grav", required=True, help="Grav root (folder containing user/)")
    parser.add_argument("--languages", choices=["auto", "native", "trees"], default="auto")
    parser.add_argument("--template-map", help="JSON file mapping cluster ids or ^route regexes to template names")
    parser.add_argument("--modular", choices=["auto", "off"], default="auto", help="auto: composed pages with more than --modular-threshold visible sections become modular pages")
    parser.add_argument("--modular-threshold", type=int, default=3, help="visible sections a single page may hold before it becomes modular (default 3)")
    parser.add_argument("--collections", choices=["auto", "off"], default="auto", help="auto: listings (posts, directories) become Grav collections of item pages")
    parser.add_argument("--keep-sample-pages", action="store_true", help="keep Grav's sample Home/Typography pages")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-incomplete", action="store_true", help="allow a draft import with unresolved controls; omissions still need implementation")
    args = parser.parse_args()
    builder = Builder(args)
    builder.run()
    return 1 if builder.unresolved_controls and not args.allow_incomplete else 0


if __name__ == "__main__":
    sys.exit(main())
