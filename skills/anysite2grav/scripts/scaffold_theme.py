#!/usr/bin/env python3
"""Create a standalone Grav theme that renders the migrated pages and mimics the source style.

Usage:
  scaffold_theme.py migration --grav grav --name acme [--title "Acme"] [--tailwind] [--no-build]
                    [--fonts download|link|skip] [--force]

Creates user/themes/<name> from the skill's theme skeleton and writes the site-specific config
to user/config/themes/<name>.yaml:
  navigation.<lang>  main menu (dropdowns), CTAs, footer columns, socials, legal line
  logo, language_labels, noindex_hosts, shared_form_routes
  analytics          source IDs pre-filled but DISABLED until the user confirms hosts
Design tokens come from migration/design-tokens.json (capture_pages.mjs, computed styles) when
present, else from the audit's CSS digest. Fonts declared by the source CSS are downloaded
(default), linked, or skipped. --tailwind adds a Tailwind 4 CLI build (css/src/site.css → css/site.css).
Activates the theme in system.yaml. Rerun with --force to regenerate tokens and seed missing config
without overwriting Admin edits. --reset-config explicitly replaces site settings from the audit;
--force-templates replaces edited skeleton files and the theme blueprint.
"""

from __future__ import annotations

import argparse
import colorsys
import json
import re
import shutil
import subprocess
import sys
import urllib.request
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import layoutkit  # noqa: E402
from csskit import GENERATED_CLASS, TONES, css_blocks, declarations, luminance, parse_color, to_hex  # noqa: E402
from gravkit import get_config, merge_config, yaml_dump  # noqa: E402
from htmlkit import read_json, route_of, site_key, slugify, write_json  # noqa: E402

SKELETON = Path(__file__).resolve().parent.parent / "assets" / "theme"
TAILWIND_VERSION = "4.3.3"


def tokens_from_digest(audit: dict) -> dict:
    style = audit.get("style", {})
    colors = []
    for value, count in style.get("colors", []):
        rgb, alpha = parse_color(value)
        if rgb and alpha >= 0.9:
            colors.append((rgb, count))
    saturated = [(rgb, count) for rgb, count in colors if colorsys.rgb_to_hls(*(channel / 255 for channel in rgb))[2] > 0.25 and max(rgb) - min(rgb) > 40]
    darks = [(rgb, count) for rgb, count in colors if luminance(rgb) < 0.05]
    lights = [(rgb, count) for rgb, count in colors if luminance(rgb) > 0.85]
    primary = max(saturated, key=lambda pair: pair[1])[0] if saturated else (37, 99, 235)
    text = max(darks, key=lambda pair: pair[1])[0] if darks else (17, 17, 17)
    background = max(lights, key=lambda pair: pair[1])[0] if lights else (255, 255, 255)
    families = [family for family, _ in style.get("font_families", []) if family and not re.search(r"icon|webflow|inherit|unset|initial|monospace|serif$|sans-serif$", family, re.I)]
    family = families[0] if families else "system-ui"
    widths = [width for width, _ in style.get("container_widths", []) if 900 <= width <= 1600]
    return {
        "color-primary": to_hex(primary),
        "color-on-primary": "#111111" if luminance(primary) > 0.4 else "#ffffff",
        "color-text": to_hex(text),
        "color-background": to_hex(background),
        "color-surface": "#ffffff" if luminance(background) > 0.5 else "#1c1c1c",
        "color-border": "rgb(0 0 0 / .12)" if luminance(background) > 0.5 else "rgb(255 255 255 / .16)",
        "color-header-bg": to_hex(text),
        "color-header-text": to_hex(background),
        "color-footer-bg": to_hex(text),
        "color-footer-text": to_hex(background),
        "font-body": f'"{family}", system-ui, sans-serif',
        "font-heading": f'"{family}", system-ui, sans-serif',
        "font-weight-heading": "700",
        "text-base": "1rem",
        "text-h1": "clamp(2.25rem, 4vw + 1rem, 4rem)",
        "text-h2": "clamp(1.75rem, 2.5vw + 1rem, 2.75rem)",
        "text-h3": "1.5rem",
        "radius": "8px",
        "radius-button": "999px",
        "container": f"{max(widths) if widths else 1200}px",
        "gutter": "clamp(1rem, 5vw, 3rem)",
        "section-space": "clamp(3rem, 8vw, 7rem)",
        "space-s": "clamp(1rem, 2vw, 1.5rem)",
        "space-m": "clamp(2rem, 4vw, 3rem)",
        "space-l": "clamp(3rem, 6vw, 5rem)",
        "space-xl": "clamp(4rem, 9vw, 8rem)",
        "card-gap": "1.5rem",
    }


THEME_NAMESPACES = ("color-", "font-", "text-", "radius")


def tone_tokens(migration: Path, tokens: dict) -> dict:
    """One background per section tone: the source's most used color for that tone.

    Sections carry `tone: light|muted|dark|accent` instead of builder classes, so every page shares
    the same few backgrounds and editors pick a tone in Admin rather than a hex value.
    """
    seen: dict[str, Counter] = {tone: Counter() for tone in TONES}

    def collect(section: dict):
        if section.get("tone") in seen and section.get("background_color"):
            seen[section["tone"]][section["background_color"]] += 1

    for content_file in (migration / "content").glob("*.json"):
        for section in read_json(content_file).get("sections", []):
            collect(section)
    if (migration / "shared-sections.json").exists():
        for section in read_json(migration / "shared-sections.json").values():
            collect(section)
    fallback = {
        "light": tokens.get("color-background", "#ffffff"),
        "muted": "#f2f2f2",
        "dark": tokens.get("color-text", "#111111"),
        "accent": tokens.get("color-primary", "#2563eb"),
    }
    result = {}
    for tone in TONES:
        background = seen[tone].most_common(1)[0][0] if seen[tone] else fallback[tone]
        rgb, _ = parse_color(background)
        light = luminance(rgb) > 0.4 if rgb else tone in ("light", "muted")
        result[f"tone-{tone}-bg"] = background
        result[f"tone-{tone}-text"] = tokens.get("color-text", "#111111") if light else "#ffffff"
    return result


def tokens_css(tokens: dict, tailwind: bool) -> str:
    namespaced = {key: value for key, value in tokens.items() if key.startswith(THEME_NAMESPACES)}
    others = {key: value for key, value in tokens.items() if key not in namespaced}
    body = lambda values: "\n".join(f"  --{key}: {value};" for key, value in values.items())  # noqa: E731
    if tailwind:
        return f"/* Generated from the source site; edit freely. */\n@theme static {{\n{body(namespaced)}\n}}\n\n:root {{\n{body(others)}\n}}\n"
    return f"/* Generated from the source site; edit freely. */\n:root {{\n{body(tokens)}\n}}\n"


def font_faces(migration: Path, theme: Path, mode: str) -> tuple[str, list[str]]:
    """@font-face rules for families the source declares; returns (css, notes)."""
    index_file = migration / "css" / "index.json"
    if mode == "skip" or not index_file.exists():
        return "", []
    notes, rules, seen = [], [], set()
    (theme / "fonts").mkdir(exist_ok=True)
    for file_name, css_url in read_json(index_file).items():
        css = (migration / "css" / file_name).read_text(encoding="utf-8", errors="replace")
        for block in re.findall(r"@font-face\s*{[^}]*}", css, re.I):
            if re.search(r"webflow-icons|icomoon|fontawesome", block, re.I):
                continue
            family = re.search(r"font-family\s*:\s*['\"]?([^;'\"]+)", block, re.I)
            if not family:
                continue
            key = re.sub(r"\s+", " ", block)
            if key in seen:
                continue
            seen.add(key)

            def replace(match):
                url = urljoin(css_url, match.group(1).strip())
                if mode != "download" or url.startswith("data:"):
                    return f"url('{url}')"
                name = slugify(Path(urlsplit(url).path).stem, "font")[:60] + Path(urlsplit(url).path).suffix
                target = theme / "fonts" / name
                if not target.exists():
                    try:
                        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 anysite2grav"})
                        target.write_bytes(urllib.request.urlopen(request, timeout=60).read())
                    except Exception as error:  # noqa: BLE001
                        notes.append(f"font download failed {url}: {error}")
                        return f"url('{url}')"
                return f"url('../fonts/{name}')"

            rules.append(re.sub(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)", replace, block))
    if rules:
        notes.append("Fonts were copied from the source site's CSS: confirm the font license allows self-hosting before publishing.")
    return "\n".join(rules) + ("\n" if rules else ""), notes


SIMPLE_CLASS_SELECTOR = re.compile(r"^((?:\.[A-Za-z_][\w-]*)+)((?::{1,2}[\w-]+(?:\([^)]*\))?)*)$")


# Hooks land on the theme's own markup, which is structured differently from the source, so only
# visual declarations carry over. Layout (display, position, grid, flex, sizing, margins) comes from
# measure_layout.mjs; a source `display: contents` once erased a whole section's background.
LAYOUT_PROPERTY = re.compile(
    r"^(display|position|top|right|bottom|left|inset.*|float|clear|z-index|order|grid.*|flex.*|align-.*|justify-.*|place-.*|gap|row-gap|column-gap|"
    r"width|min-width|max-width|height|min-height|max-height|margin.*|overflow.*|contain|content-visibility|columns|column-.*|transform|translate|scale|rotate|"
    r"visibility|clip|clip-path|pointer-events|aspect-ratio|container.*|box-sizing)$",
    re.I,
)


def visual_declarations(body: str) -> str:
    kept = []
    for declaration in declarations(body):
        name, _, value = declaration.partition(":")
        if name.strip() and value.strip() and (name.strip().startswith("--") or not LAYOUT_PROPERTY.match(name.strip())):
            # No !important: the page's measured tone and the theme's tokens must be able to win.
            cleaned_value = re.sub(r"\s*!important", "", value.strip())
            kept.append(f"{name.strip()}:{cleaned_value}")
    return ";".join(kept)


def inline_styles(migration: Path):
    """(css, page url) for each distinct inline <style> in the crawled pages (WordPress global
    styles carry the preset variables the has-* classes use)."""
    seen = set()
    routes = read_json(migration / "routes.json") if (migration / "routes.json").exists() else {"pages": []}
    for page in routes.get("pages", []):
        path = migration / page.get("html_file", "")
        if not page.get("html_file") or not path.exists():
            continue
        for css in re.findall(r"<style[^>]*>(.*?)</style>", path.read_text(encoding="utf-8", errors="replace"), re.S | re.I):
            key = hash(css)
            if css.strip() and key not in seen:
                seen.add(key)
                yield css, page["url"]


def port_source_css(migration: Path, theme: Path, classes: set[str], reserved: set[str] | None = None) -> tuple[str, int]:
    """Copy source rules whose selectors are made only of section/card classes onto .src-* hooks.

    Builders (Webflow especially) put section backgrounds, spacing and colors in class rules, not
    markup, so the crawl alone misses them. url() assets are downloaded into images/source/.
    """
    index_file = migration / "css" / "index.json"
    sources = [((migration / "css" / name).read_text(encoding="utf-8", errors="replace"), url) for name, url in read_json(index_file).items()] if index_file.exists() else []
    sources += list(inline_styles(migration))
    if not sources:
        return "", 0
    reserved = reserved or set()
    (theme / "images" / "source").mkdir(parents=True, exist_ok=True)
    # Every rule once: builders and WordPress repeat the same stylesheet (or inline block) on every
    # page, and copying per page produced hundreds of near-identical files. @media groups merge.
    rules: dict[str, list[str]] = {"": []}
    seen: set[tuple[str, str]] = set()
    ported, root_vars = 0, {}

    def keep(media: str, rule: str) -> bool:
        nonlocal ported
        if (media, rule) in seen:
            return False
        seen.add((media, rule))
        rules.setdefault(media, []).append(rule)
        ported += 1
        return True

    def rewrite_urls(body: str, css_url: str) -> str:
        def replace(match):
            raw = match.group(1).strip()
            if raw.startswith(("data:", "#")):
                return match.group(0)
            url = urljoin(css_url, raw)
            name = slugify(Path(urlsplit(url).path).stem, "asset")[:60] + Path(urlsplit(url).path).suffix.lower()
            target = theme / "images" / "source" / name
            if not target.exists():
                try:
                    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 anysite2grav"})
                    target.write_bytes(urllib.request.urlopen(request, timeout=60).read())
                except Exception:  # noqa: BLE001 - keep the remote URL if the asset can't be fetched
                    return f"url('{url}')"
            return f"url('../images/source/{name}')"
        return re.sub(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)", replace, body)

    def convert(prelude: str, body: str, css_url: str) -> str | None:
        selectors = []
        for selector in (part.strip() for part in prelude.split(",")):
            match = SIMPLE_CLASS_SELECTOR.match(selector)
            if not match:
                continue
            names = match.group(1).strip(".").split(".")
            if all(name in classes for name in names):
                selectors.append("".join(f".src-{name}" for name in names) + match.group(2))
        if not selectors:
            return None
        visual = visual_declarations(body)
        if not visual:
            return None
        return f"{', '.join(selectors)} {{{rewrite_urls(visual, css_url)}}}"

    for css, css_url in sources:
        for prelude, body in css_blocks(css):
            if re.fullmatch(r"(?::root|html|body|:where\(body\)|:root\s*,\s*body)", prelude.strip()):
                for declaration in declarations(body):
                    name, _, value = declaration.partition(":")
                    if name.strip().startswith("--") and value.strip():
                        root_vars.setdefault(name.strip(), value.strip())
            elif prelude.startswith("@media"):
                media = " ".join(prelude.split())
                for inner_prelude, inner_body in css_blocks(body):
                    rule = convert(inner_prelude, inner_body, css_url)
                    if rule:
                        keep(media, rule)
            elif not prelude.startswith("@"):
                rule = convert(prelude, body, css_url)
                if rule:
                    keep("", rule)
    header = "/* Ported from the source stylesheet: rules for section/card classes, mapped to .src-* hooks.\n   Regenerated by scaffold_theme.py --force; put hand edits in components.css or a later file. */\n"
    # Only the custom properties the ported rules use (and what those use), and never one that would
    # override a theme token (a plugin's :root { --font-body: 16px } once replaced the theme font).
    needed, queue = set(), [rule for group in rules.values() for rule in group]
    while queue:
        for name in re.findall(r"var\(\s*(--[\w-]+)", queue.pop()):
            if name not in needed and name in root_vars and name[2:] not in reserved:
                needed.add(name)
                queue.append(root_vars[name])
    variables = (":root {\n  " + ";\n  ".join(f"{name}: {root_vars[name]}" for name in sorted(needed)) + ";\n}\n") if needed else ""
    output = rules.pop("")
    output += [f"{media} {{\n  " + "\n  ".join(inner) + "\n}" for media, inner in rules.items()]
    return header + variables + "\n".join(output) + "\n", ported


def section_classes(migration: Path) -> set[str]:
    classes: set[str] = set()

    def walk_blocks(blocks):
        for block in blocks or []:
            classes.update(block.get("classes", []))
            for card in block.get("cards", []) + block.get("columns", []):
                classes.update(card.get("classes", []))
                walk_blocks(card.get("blocks"))

    for content_file in (migration / "content").glob("*.json"):
        for section in read_json(content_file).get("sections", []):
            classes.update(section.get("classes", []))
            walk_blocks(section.get("blocks"))
    if (migration / "shared-sections.json").exists():
        for section in read_json(migration / "shared-sections.json").values():
            classes.update(section.get("classes", []))
            walk_blocks(section.get("blocks"))
    # Per-page generated names (Webflow w-node-*, WordPress wp-container-*/wp-elements-*) are not
    # design: porting them only duplicates layout rules.
    return {name for name in classes if not GENERATED_CLASS.search(name)}


def localize(url: str | None, site: str) -> str | None:
    if not url:
        return url
    parts = urlsplit(url)
    if parts.scheme in ("http", "https") and site_key(parts.hostname or "") == site:
        return route_of(url) + (f"#{parts.fragment}" if parts.fragment else "")
    return url


def theme_asset(url: str | None, manifest: dict, theme: Path) -> str | None:
    entry = manifest.get(url or "")
    if not entry or not entry.get("file"):
        return url
    clean = re.sub(r"^[0-9a-f]{12}-", "", entry["file"])
    target = theme / "images" / clean
    if not target.exists():
        shutil.copyfile(Path(theme_asset.migration) / "media-cache" / entry["file"], target)
    return f"theme://images/{clean}"


def navigation_config(chrome: dict, site: str, manifest: dict, theme: Path) -> dict:
    navigation = {}
    for lang, summary in chrome.items():
        def link(entry):
            result = {"label": entry.get("label"), "url": localize(entry.get("url"), site)}
            if entry.get("description"):
                result["description"] = entry["description"]
            if entry.get("icon"):
                result["icon"] = theme_asset(entry["icon"], manifest, theme)
            if entry.get("action"):
                result["modal"] = ""
            return {key: value for key, value in result.items() if value is not None}

        navigation[lang] = {
            "main": [{**link(item), **({"children": [link(child) for child in item["children"]]} if item.get("children") else {})} for item in summary.get("menu", [])],
            "ctas": [link(cta) for cta in summary.get("ctas", [])],
            # The source header has a site search: rendered when the simplesearch plugin is enabled.
            "search": True if summary.get("search") else None,
            "footer": {
                "columns": [{"heading": column.get("heading"), "links": [link(entry) for entry in column["links"] if not any(domain in (entry.get("url") or "") for domain in ("twitter.com", "x.com", "instagram.com", "linkedin.com", "facebook.com", "youtube.com", "tiktok.com"))]} for column in summary.get("footer", {}).get("columns", [])],
                "socials": summary.get("footer", {}).get("socials", []),
                "legal": summary.get("footer", {}).get("legal"),
            },
        }
        navigation[lang]["footer"]["columns"] = [column for column in navigation[lang]["footer"]["columns"] if column["links"]]
    return navigation


def preserve_overrides(defaults: dict, overrides: dict):
    merged = dict(defaults)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = preserve_overrides(merged[key], value)
        else:
            merged[key] = value
    return merged


def theme_blueprint(title: str, languages: list[str]) -> str:
    nav_tabs = {}
    for lang in languages:
        nav_tabs[f"nav_{lang}"] = {
            "type": "tab",
            "title": f"Navigation ({lang})",
            "fields": {
                f"navigation.{lang}.main": {
                    "type": "list", "label": "Main menu", "collapsed": True,
                    "fields": {
                        ".label": {"type": "text", "label": "Label"},
                        ".url": {"type": "text", "label": "Link (leave empty for a dropdown)"},
                        ".children": {"type": "list", "label": "Dropdown items", "collapsed": True, "fields": {
                            ".label": {"type": "text", "label": "Label"}, ".url": {"type": "text", "label": "Link"},
                            ".description": {"type": "text", "label": "Description"},
                            ".icon": {"type": "media", "label": "Icon", "sources": ["site", "url"], "accept": ["image/*"]},
                        }},
                    },
                },
                f"navigation.{lang}.search": {"type": "toggle", "label": "Search box in header", "help": "Needs the simplesearch plugin", "highlight": 1, "options": {1: "Yes", 0: "No"}, "validate": {"type": "bool"}},
                f"navigation.{lang}.ctas": {"type": "list", "label": "Header buttons", "fields": {
                    ".label": {"type": "text", "label": "Label"}, ".url": {"type": "text", "label": "Link"},
                    ".modal": {"type": "text", "label": "Opens modal (shared section name)"},
                }},
                f"navigation.{lang}.footer.columns": {"type": "list", "label": "Footer columns", "fields": {
                    ".heading": {"type": "text", "label": "Heading"},
                    ".links": {"type": "list", "label": "Links", "fields": {".label": {"type": "text", "label": "Label"}, ".url": {"type": "text", "label": "Link"}}},
                }},
                f"navigation.{lang}.footer.socials": {"type": "list", "label": "Social profiles", "fields": {
                    ".network": {"type": "select", "label": "Network", "options": {name: name for name in ("x", "linkedin", "instagram", "facebook", "youtube", "tiktok", "github")}},
                    ".url": {"type": "text", "label": "Profile URL"},
                }},
                f"navigation.{lang}.footer.legal": {"type": "text", "label": "Legal line"},
            },
        }
    blueprint = {
        "name": title,
        "slug": slugify(title),
        "type": "theme",
        "version": "1.0.0",
        "description": f"{title} theme generated by anysite2grav",
        "license": "MIT",
        "dependencies": [{"name": "grav", "version": ">=2.0.0"}],
        "form": {"validation": "loose", "fields": {"tabs": {"type": "tabs", "active": 1, "fields": {
            "general": {"type": "tab", "title": "General", "fields": {
                "logo": {"type": "media", "label": "Logo", "sources": ["site", "url"], "accept": ["image/*"]},
                "favicon": {"type": "text", "label": "Favicon (theme:// or media:// path)"},
                "noindex_hosts": {"type": "array", "label": "Never index these hosts", "value_only": True, "help": "Local and preview hostnames. Sends noindex meta + X-Robots-Tag; crawlers must still be allowed to fetch."},
                "shared_form_routes": {"type": "array", "label": "Shared form pages", "value_only": True, "help": "Form pages embedded on other pages, e.g. /forms/newsletter"},
                "global_modals": {"type": "array", "label": "Modals on every page", "value_only": True},
            }},
            "analytics": {"type": "tab", "title": "Analytics", "fields": {
                "analytics.enabled": {"type": "toggle", "label": "Enable analytics", "highlight": 1, "default": 0, "options": {1: "Enabled", 0: "Disabled"}, "validate": {"type": "bool"}},
                "analytics.hosts": {"type": "array", "label": "Only on these hosts", "value_only": True, "help": "Production hostnames. Local/preview hosts never load analytics."},
                "analytics.gtm": {"type": "text", "label": "Google Tag Manager ID"},
                "analytics.ga4": {"type": "text", "label": "GA4 measurement ID"},
                "analytics.ga4_via_gtm": {"type": "toggle", "label": "GA4 is loaded by GTM", "highlight": 1, "options": {1: "Yes", 0: "No"}, "validate": {"type": "bool"}},
                "analytics.head_snippets": {"type": "editor", "label": "Extra <head> snippets", "codemirror": {"mode": "htmlmixed"}},
                "analytics.body_snippets": {"type": "editor", "label": "Extra <body> snippets", "codemirror": {"mode": "htmlmixed"}},
            }},
            **nav_tabs,
        }}}},
    }
    return yaml_dump(blueprint) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("migration", nargs="?", default="migration")
    parser.add_argument("--grav", required=True)
    parser.add_argument("--name", required=True, help="theme slug, e.g. acme")
    parser.add_argument("--title", help="human title (defaults to site title)")
    parser.add_argument("--tailwind", action="store_true", help="build CSS with the Tailwind 4 CLI")
    parser.add_argument("--no-build", action="store_true", help="skip npm install/build in Tailwind mode")
    parser.add_argument("--fonts", choices=["download", "link", "skip"], default="download")
    parser.add_argument("--force", action="store_true", help="regenerate tokens and seed missing settings, preserving site config")
    parser.add_argument("--reset-config", action="store_true", help="replace site config from the audit (requires --force)")
    parser.add_argument("--force-templates", action="store_true", help="overwrite skeleton files and the theme blueprint")
    args = parser.parse_args()
    if args.reset_config and not args.force:
        parser.error("--reset-config requires --force")

    migration, grav = Path(args.migration), Path(args.grav)
    slug = slugify(args.name)
    class_name = "".join(part.capitalize() for part in slug.split("-"))
    routes = read_json(migration / "routes.json")
    site = site_key(urlsplit(routes["source"]).hostname or "")
    title = args.title or get_config(grav, "user/config/site.yaml").get("title") or site.split(".")[0].capitalize()
    theme = grav / "user" / "themes" / slug
    fresh = not theme.exists()
    if not fresh and not (args.force or args.force_templates):
        print(f"{theme} exists; pass --force to regenerate config/tokens", file=sys.stderr)
        return 1

    for source in SKELETON.rglob("*"):
        if source.is_dir():
            continue
        relative = source.relative_to(SKELETON)
        target = theme / str(relative).replace("__THEME_SLUG__", slug)
        if target.exists() and not fresh and not args.force_templates:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        text = source.read_text(encoding="utf-8")
        target.write_text(text.replace("__THEME_SLUG__", slug).replace("__ThemeClass__", class_name).replace("__THEME_TITLE__", title), encoding="utf-8")
    for directory in ("images", "fonts", "css"):
        (theme / directory).mkdir(exist_ok=True)

    page_map = read_json(migration / "page-map.json") if (migration / "page-map.json").exists() else {"languages": [], "default_lang": "en"}
    languages = page_map.get("languages") or [page_map.get("default_lang", "en")]
    chrome = read_json(migration / "chrome.json") if (migration / "chrome.json").exists() else {}
    manifest = read_json(migration / "media-manifest.json") if (migration / "media-manifest.json").exists() else {}
    audit = read_json(migration / "audit.json") if (migration / "audit.json").exists() else {}
    theme_asset.migration = str(migration)

    blueprint_path = theme / "blueprints.yaml"
    if not blueprint_path.exists() or args.force_templates:
        blueprint_path.write_text(theme_blueprint(title, languages), encoding="utf-8")
    defaults_path = theme / f"{slug}.yaml"
    if not defaults_path.exists() or args.force_templates:
        defaults_path.write_text(yaml_dump({"enabled": True, "noindex_hosts": ["localhost", "127.0.0.1"], "analytics": {"enabled": False, "hosts": []}}) + "\n", encoding="utf-8")

    default_chrome = chrome.get(page_map.get("default_lang", "en")) or next(iter(chrome.values()), {})
    source_logo = default_chrome.get("logo") or {}
    if source_logo.get("svg"):
        (theme / "images").mkdir(parents=True, exist_ok=True)
        (theme / "images" / "logo.svg").write_text(source_logo["svg"] + "\n", encoding="utf-8")
        logo = "theme://images/logo.svg"
    else:
        logo = theme_asset(source_logo.get("src"), manifest, theme) if source_logo.get("src") else None
    labels = {}
    for summary in chrome.values():
        for entry in summary.get("languages", []):
            code = (entry.get("hreflang") or route_of(entry.get("url") or "/").strip("/") or page_map.get("default_lang", "en")).split("-")[0]
            labels.setdefault(code, entry.get("label"))
    trackers = audit.get("trackers", {})
    gtm = next(iter(trackers.get("Google Tag Manager", {}).get("ids", [])), None)
    ga4 = next(iter(trackers.get("Google Analytics 4", {}).get("ids", [])), None)
    forms = [f"/forms/{name}" for name in sorted(set((page_map.get("forms") or {}).values()))]
    config = {
        "logo": logo,
        "language_labels": labels or None,
        "noindex_hosts": ["localhost", "127.0.0.1"],
        "shared_form_routes": forms,
        "analytics": {
            "enabled": False,
            "hosts": sorted({site, f"www.{site}"}),
            "gtm": gtm,
            "ga4": ga4,
            "ga4_via_gtm": bool(gtm and ga4),
        },
        "navigation": navigation_config(chrome, site, manifest, theme),
    }
    # Builders open popups from href="#" CTAs via custom JS. With exactly one form-bearing modal,
    # wire those CTAs to it; otherwise leave modal: "" for the agent to map by clicking the source.
    shared = read_json(migration / "shared-sections.json") if (migration / "shared-sections.json").exists() else {}
    shared_names = page_map.get("shared", {})
    form_modals = sorted({shared_names.get(key, key) for key, section in shared.items() if section.get("modal") and any(block["type"] == "form" for block in section["blocks"])})
    unwired = 0
    for lang_nav in config["navigation"].values():
        for cta in lang_nav.get("ctas", []):
            if cta.get("modal") == "":
                if len(form_modals) == 1:
                    cta["modal"] = form_modals[0]
                else:
                    unwired += 1
    if len(form_modals) == 1:
        config["global_modals"] = form_modals
    config = {key: value for key, value in config.items() if value is not None}
    config["analytics"] = {key: value for key, value in config["analytics"].items() if value is not None}
    user_config = f"user/config/themes/{slug}.yaml"
    if args.reset_config and (grav / user_config).exists():
        (grav / user_config).unlink()
    else:
        config = preserve_overrides(config, get_config(grav, user_config))
    merge_config(grav, user_config, config)

    tokens_file = migration / "design-tokens.json"
    tokens = tokens_from_digest(audit)
    if tokens_file.exists():
        tokens.update(read_json(tokens_file).get("tokens", {}))
    tokens.update(tone_tokens(migration, tokens))
    # Measured layout (measure_layout.mjs): type scale steps, font roles, alternate header colors.
    tokens.update(layoutkit.tokens(layoutkit.load(migration)))
    # A transparent source header (over a hero image/video) measures as "no background": fall back to
    # page colors so the generated header is legible, then style the overlay variant by hand.
    light_logo = bool(re.search(r"white|light|inverse|reverse", logo or "", re.I))
    for area in ("header", "footer"):
        background, text = tokens.get(f"color-{area}-bg"), tokens.get(f"color-{area}-text")
        if not background or (text and background.lower() == text.lower()):
            dark = area == "footer" or light_logo
            tokens[f"color-{area}-bg"] = tokens["color-text"] if dark else tokens["color-background"]
            tokens[f"color-{area}-text"] = tokens["color-background"] if dark else tokens["color-text"]
    fonts_css, notes = font_faces(migration, theme, args.fonts)
    src = theme / "css" / "src"
    (src / "tokens.css").write_text(tokens_css(tokens, args.tailwind), encoding="utf-8")
    source_css, ported = port_source_css(migration, theme, section_classes(migration), reserved=set(tokens))
    (src / "source.css").write_text(source_css or "/* No source stylesheet captured. */\n", encoding="utf-8")
    (src / "fonts.css").write_text(fonts_css or "/* No source @font-face rules found. */\n", encoding="utf-8")
    write_json(theme / "design-tokens.json", tokens)

    if args.tailwind:
        (src / "site.css").write_text(
            '@import "tailwindcss";\n@import "./fonts.css";\n@import "./tokens.css";\n@import "./components.css";\n@import "./source.css";\n\n'
            '@source "../../templates";\n\n/* Source-variant hooks: style .src-<class> here with @apply or plain CSS. */\n',
            encoding="utf-8",
        )
        package = {
            "name": f"grav-theme-{slug}", "private": True, "type": "module",
            "scripts": {"build": "tailwindcss -i css/src/site.css -o css/site.css --minify", "watch": "tailwindcss -i css/src/site.css -o css/site.css --watch"},
            "devDependencies": {"tailwindcss": TAILWIND_VERSION, "@tailwindcss/cli": TAILWIND_VERSION},
        }
        (theme / "package.json").write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
        (theme / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
        if not args.no_build and shutil.which("npm"):
            subprocess.run(["npm", "install", "--no-audit", "--no-fund"], cwd=theme, check=True, stdout=subprocess.DEVNULL)
            subprocess.run(["npm", "run", "build"], cwd=theme, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        parts = [(src / name).read_text(encoding="utf-8") for name in ("fonts.css", "tokens.css", "components.css", "source.css")]
        (theme / "css" / "site.css").write_text("\n".join(parts), encoding="utf-8")

    design = (theme / "DESIGN.md")
    if fresh or args.force or not design.exists():
        design.write_text(design_doc(title, tokens, audit, args.tailwind), encoding="utf-8")
    merge_config(grav, "user/config/system.yaml", {"pages": {"theme": slug}})
    print("DRAFT THEME: exact source layouts, responsive/state styles and dedicated content types still require implementation and verification.")
    print(f"theme '{slug}' at {theme} ({'Tailwind 4' if args.tailwind else 'plain CSS'}); {ported} source CSS rules ported to .src-* hooks; activated; config → {user_config}")
    for note in notes:
        print(f"NOTE: {note}")
    if unwired:
        print(f"NOTE: {unwired} header CTA(s) open a popup on the source (href=\"#\"); set navigation.<lang>.ctas[].modal to the right /shared section (click-test the source to map them).")
    if gtm or ga4:
        print(f"Analytics IDs found (GTM={gtm}, GA4={ga4}). New settings start disabled; existing site choices are preserved. Confirm production hosts before enabling.")
    return 0


def design_doc(title: str, tokens: dict, audit: dict, tailwind: bool) -> str:
    rows = "\n".join(f"| `--{key}` | `{value}` |" for key, value in tokens.items())
    families = ", ".join(family for family, _ in audit.get("style", {}).get("font_families", [])[:6])
    return f"""# {title} design system

The single source of truth for new sections, components and animations in this theme. Update it
when a rule changes; agents read it before styling.

## Fidelity rule

This is a generated draft. Tone/space presets and generic blocks are initial guesses, not a final
design contract. Build source-specific templates and matching blueprints with named fields, preserve
exact/asymmetric spacing, colors and typography, and measure desktop/tablet/mobile plus hover, focus
and open/selected states. Override plugin output in the theme to match the source and test its behavior.
A grayscale similarity score or passing text coverage is not visual acceptance.

This theme reproduces {audit.get('source', 'the source site')}. Until the owner approves a redesign, match
the source: compare desktop (1440px) and mobile (390px) screenshots section by section before
calling a page done. Record intentional deviations here.

## Tokens

Generated from the source CSS/computed styles into `css/src/tokens.css`{' (Tailwind `@theme`)' if tailwind else ''}.

| Token | Value |
| --- | --- |
{rows}

Source font families by usage: {families or 'n/a'}.

## Structure

- Pages render `sections` (frontmatter) through `templates/partials/sections.html.twig` and
  `blocks.html.twig`. Each section keeps its source classes as `.src-<class>` hooks: style source
  variants there (e.g. `.src-dark {{ background: var(--color-text); color: var(--color-background) }}`).
- Pages with more than three sections are modular: `modular.html.twig` renders child modules
  (`NN._name/<kind>.md`) through `templates/modular/<kind>.html.twig`, which reuse the same partial
  and add a `.module--<kind>` class (hero, section, cards, gallery, form, shared). To give a kind
  named fields, change its template and `blueprints/pages/modular/<kind>.yaml` together.
- When several routes share one layout, promote them to a dedicated page type: a template in
  `templates/<type>.html.twig` and a matching blueprint in `blueprints/pages/<type>.yaml` with
  named fields. Keep the blueprint and template in step.
- Header, footer, menus, CTAs and socials come from theme config (`navigation.<lang>`), editable in
  Admin → Themes. Shared sections live under `/shared`, forms under `/forms`.
- Keep site settings in `user/config/themes/<name>.yaml`. Ordinary `--force` reruns preserve
  those values and theme blueprints; `--reset-config --force` explicitly replaces site settings.
- Put project overrides in `css/custom.css`, loaded after the generated CSS. Extend small Twig
  blocks and call `parent()` when adding assets. Keep deferred head assets and the head (default)
  and bottom asset groups so embedded plugins can register their assets while rendering.
- Import `blueprints/pages/partials/page-fields.yaml` into new page types for browser title,
  body classes and noindex; keep named fields synchronized with their Twig templates.

## Rules

- Reuse tokens; no new hard-coded colors or font sizes outside `tokens.css`.
- Body text ≥ 16px, nothing below 13px; no horizontal overflow at 320px.
- Animations: subtle, paused offscreen, disabled for `prefers-reduced-motion`, with a static fallback.
- Accessibility: visible focus, semantic headings in order, alt text on informative images,
  keyboard-operable menus and dialogs.
- Every UI string in every language the site supports.
"""


if __name__ == "__main__":
    sys.exit(main())
