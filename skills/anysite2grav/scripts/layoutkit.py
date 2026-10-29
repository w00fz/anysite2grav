"""Turn measured source layout (measure_layout.mjs → migration/layout.json) into the theme's design
vocabulary: a few semantic frontmatter fields per section/block plus site-wide tokens.

Shared by build_pages.py (frontmatter) and scaffold_theme.py (tokens), so the type scale and font
roles a page refers to are the ones the theme defines.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

from csskit import parse_color, to_hex, tone_of

SIZE_NAMES = ("display", "xl", "l", "m", "s", "xs")
IMAGE_RATIOS = {"1/1": 1.0, "4/3": 4 / 3, "3/2": 1.5, "16/9": 16 / 9, "21/9": 21 / 9, "3/4": 0.75, "2/3": 2 / 3}


def load(migration: Path) -> dict:
    path = migration / "layout.json"
    return json.loads(path.read_text(encoding="utf-8")).get("routes", {}) if path.exists() else {}


def rgb_of(value: str | None):
    if not value:
        return None
    match = re.search(r"rgba?\(([^)]*)\)", value)
    rgb, alpha = parse_color(match.group(0) if match else value)
    return rgb if rgb and alpha >= 0.6 else None


def space_step(pixels: float) -> str:
    return "none" if pixels < 4 else "s" if pixels <= 28 else "m" if pixels <= 56 else "l" if pixels <= 100 else "xl"


def plain(text: str | None) -> str:
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text or "")
    return re.sub(r"\s+", " ", re.sub(r"[*_`#>]", "", text)).strip().lower()


def first_family(stack: str | None) -> str | None:
    if not stack:
        return None
    return stack.split(",")[0].strip().strip("\"'") or None


# --- site-wide: type scale, font roles, header variants -----------------------------------

def type_scale(routes: dict) -> list[tuple[str, int]]:
    """Up to six heading sizes the source actually uses, largest first, named display…xs."""
    sizes = Counter()
    for data in routes.values():
        for section in data.get("sections", {}).values():
            for heading in section.get("headings", []):
                sizes[round(heading["size"])] += 1
        for block in data.get("blocks", {}).values():
            if block.get("title"):
                sizes[round(block["title"]["size"])] += 1
    clusters: list[list[int]] = []
    for size in sorted(sizes, reverse=True):
        if clusters and size >= clusters[-1][0] * 0.9:
            clusters[-1].append(size)
        else:
            clusters.append([size])
    if not clusters:
        return []
    # Pick steps that cover the range: the largest (a hero number shows once), the most used, then
    # repeatedly the size worst served by the current steps, weighted by how often it appears.
    representatives = {max(group, key=lambda size: sizes[size]): sum(sizes[size] for size in group) for group in clusters}
    selected = {max(representatives), max(representatives, key=representatives.get)}
    while len(selected) < min(len(SIZE_NAMES), len(representatives)):
        def cost(size):
            nearest = min(selected, key=lambda step: abs(math.log(step / size)))
            return representatives[size] ** 0.5 * abs(math.log(nearest / size))
        selected.add(max((size for size in representatives if size not in selected), key=cost))
    steps = sorted(selected, reverse=True)
    return list(zip(SIZE_NAMES, steps))


def size_step(pixels: float, scale: list[tuple[str, int]]) -> str | None:
    if not scale:
        return None
    return min(scale, key=lambda step: abs(step[1] - pixels) / step[1])[0]


def font_roles(routes: dict) -> dict:
    """body: paragraph family; heading: most used heading family; alt: a second heading family."""
    body, headings = Counter(), Counter()
    for data in routes.values():
        if data.get("body"):
            body[first_family(data["body"]["family"])] += 3
        for section in data.get("sections", {}).values():
            for paragraph in section.get("paragraphs", []):
                body[first_family(paragraph["family"])] += 1
            for heading in section.get("headings", []):
                headings[first_family(heading["family"])] += 1
    roles = {"body": body.most_common(1)[0][0] if body else None}
    ranked = headings.most_common()
    roles["heading"] = ranked[0][0] if ranked else roles["body"]
    total = sum(headings.values()) or 1
    roles["alt"] = next((family for family, count in ranked[1:] if family != roles["body"] and count >= 0.1 * total), None)
    return roles


def family_role(family: str | None, roles: dict) -> str | None:
    name = first_family(family)
    for role in ("heading", "body", "alt"):
        if name and name == roles.get(role):
            return role
    return None


def header_variants(routes: dict) -> dict:
    """Header color per page, grouped by tone: the site default (home, else the most common tone)
    and an alternate tone (e.g. dark headers on inner sections). Near-identical shades count as one."""
    keyed = {}
    for route, data in routes.items():
        header = (data.get("chrome") or {}).get("header") or {}
        background = rgb_of(header.get("background"))
        if background:
            keyed[route] = ("dark" if tone_of(background) in ("dark", "accent") else "light", header.get("background"), header.get("color"))
    if not keyed:
        return {}
    default_tone = keyed["/"][0] if "/" in keyed else Counter(value[0] for value in keyed.values()).most_common(1)[0][0]
    alternates = [value for value in keyed.values() if value[0] != default_tone]
    result = {"default": default_tone, "routes": {}}
    if alternates:
        _, background, color = Counter(alternates).most_common(1)[0][0]
        result["alt"] = (background, color)
        result["routes"] = {route: "alt" for route, value in keyed.items() if value[0] != default_tone}
    return result


def header_tokens(routes: dict) -> dict:
    """Header anatomy and controls measured on the home page (else the first page measured)."""
    data = routes.get("/") or next(iter(routes.values()), {})
    header = (data.get("chrome") or {}).get("header") or {}
    result = {}
    if header.get("height"):
        result["header-height"] = f"{round(header['height'])}px"
    logo, nav, cta = header.get("logo"), header.get("nav"), header.get("cta")
    if logo:
        result["logo-height"] = f"{round(logo['height'])}px"
        if logo["left"] < 48:
            # Full-width header bar: the logo sits near the window edge, not in the content column.
            result["header-width"] = "100%"
            result["header-gutter"] = f"{max(12, round(logo['left']))}px"
        if nav and nav["left"] - logo["right"] < 140:
            result["nav-start"] = "0"  # the menu starts right after the logo instead of centered
    if nav:
        result["nav-font-size"] = f"{round(nav['size'])}px"
        result["nav-font-weight"] = str(nav["weight"])
        result["nav-link-padding-x"] = f"{round(nav['paddingX'])}px"
    if cta:
        result["button-font-size"] = f"{round(cta['size'])}px"
        result["button-font-weight"] = str(cta["weight"])
        result["button-padding"] = f"{round(cta['padding'][0])}px {round(cta['padding'][1])}px"
        result["radius-button"] = cta["radius"]
    field = next((value["input"] for value in routes.values() if value.get("input")), None)
    if field:
        background = rgb_of(field.get("background"))
        if background:
            result["input-bg"] = to_hex(background)
        result["input-border"] = f"{field['border']['width']:g}px solid {field['border']['color']}" if field.get("border") else "0"
        result["input-radius"] = field.get("radius") or "0px"
        result["input-height"] = f"{round(field['height'])}px"
    return result


def tokens(routes: dict) -> dict:
    """Theme tokens derived from the measurements: type scale steps, font roles, header variant."""
    result = {}
    for name, pixels in type_scale(routes):
        # Fluid down to ~60% on small screens; exact at the 1440px capture width.
        result[f"text-{name}"] = f"clamp({max(14, round(pixels * 0.6))}px, {round(pixels / 14.4, 2)}vw, {pixels}px)" if pixels > 28 else f"{pixels}px"
    roles = font_roles(routes)
    for role, family in roles.items():
        if family:
            result[f"font-{role}"] = f'"{family}", system-ui, sans-serif' if role == "body" else f'"{family}", serif' if re.search(r"garamond|serif|georgia|times|playfair|lora|merriweather", family, re.I) else f'"{family}", system-ui, sans-serif'
    result.update(header_tokens(routes))
    variants = header_variants(routes)
    if variants.get("alt"):
        background, color = (rgb_of(value) for value in variants["alt"])
        if background:
            result["color-header-alt-bg"] = to_hex(background)
        if color:
            result["color-header-alt-text"] = to_hex(color)
    return result


# --- per section / block --------------------------------------------------------------------

def ratio_of(widths: list[float]) -> list[float] | None:
    widths = [width for width in widths if width > 0]
    if len(widths) < 2:
        return None
    smallest = min(widths)
    ratio = [round(width / smallest * 4) / 4 for width in widths]
    return None if max(ratio) - min(ratio) < 0.15 else ratio


def image_ratio(value: float | None) -> str | None:
    if not value:
        return None
    return min(IMAGE_RATIOS, key=lambda name: abs(IMAGE_RATIOS[name] - value) / IMAGE_RATIOS[name])


def section_style(metrics: dict | None) -> dict:
    if not metrics:
        return {}
    style: dict = {}
    background = rgb_of(metrics.get("background"))
    if background:
        style["tone"] = tone_of(background)
        style["background_color"] = to_hex(background)
    top = (metrics.get("padding") or [0, 0])[0]
    if top < 4 and metrics.get("inset"):
        top = min(metrics["inset"])  # the visible gap, wherever the source put the spacing
    style["space"] = space_step(top)
    divider = [side for side, key in (("top", "borderTop"), ("bottom", "borderBottom")) if metrics.get(key)]
    if divider:
        style["divider"] = "both" if len(divider) == 2 else divider[0]
    if metrics.get("align") == "center":
        style["align"] = "center"
    grid = metrics.get("grid") or {}
    tracks = grid.get("tracks") or []
    if len(tracks) == 2 and grid.get("headingColumn") == 0:
        style["layout"] = "split"
        style["ratio"] = ratio_of(tracks) or [1, 1]
        if grid.get("divider"):
            style["split_divider"] = True
    return style


def block_style(metrics: dict | None, block_type: str) -> dict:
    if not metrics:
        return {}
    style: dict = {}
    if block_type == "list":
        if metrics.get("inline"):
            style["style"] = "tabs" if metrics.get("activeBackground") else "inline"
        if metrics.get("size") and metrics["size"] < 15:
            style["size"] = "small"
        return style
    if block_type == "columns":
        ratio = ratio_of(metrics.get("rowWidths") or [])
        if ratio:
            style["ratio"] = ratio
        if (metrics.get("child") or {}).get("dividers"):
            style["divider"] = True
        align = metrics.get("align") or ""
        if align in ("start", "flex-start", "normal", "stretch"):
            style["valign"] = "top"
        elif align in ("end", "flex-end"):
            style["valign"] = "bottom"
        return style
    # Repeated items: cards, collections, listings, galleries.
    per_row = metrics.get("perRow") or 0
    if per_row >= 2:
        style["per_row"] = per_row
    child = metrics.get("child") or {}
    if child.get("shadow"):
        style["card"] = "shadow"
    elif child.get("border"):
        style["card"] = "bordered"
    elif child.get("background"):
        style["card"] = "filled"
    else:
        style["card"] = "plain"
    if child.get("dividers") and style["card"] == "plain":
        style["card"] = "divided"
    image = metrics.get("image") or {}
    if image.get("ratio"):
        style["image_ratio"] = image_ratio(image["ratio"])
    if "grayscale" in (image.get("filter") or ""):
        style["image_filter"] = "grayscale"
    if metrics.get("width") and metrics.get("viewport") and metrics["width"] >= 0.97 * metrics["viewport"]:
        style["bleed"] = True
    if (metrics.get("gap") or [1, 1])[0] == 0 and per_row >= 2:
        style["gap"] = "none"
    return style


def text_styles(metrics: dict | None, scale: list[tuple[str, int]], roles: dict) -> tuple[dict, dict]:
    """Measured headings and paragraphs keyed by plain text → {size, font} for matching blocks."""
    headings, paragraphs = {}, {}
    if not metrics:
        return headings, paragraphs
    for heading in metrics.get("headings", []):
        style = {"size": size_step(heading["size"], scale)}
        role = family_role(heading["family"], roles)
        if role and role != "heading":
            style["font"] = role
        if heading.get("transform") == "uppercase":
            style["transform"] = "uppercase"
        headings.setdefault(plain(heading["text"])[:60], style)
    body_sizes = sorted(paragraph["size"] for paragraph in metrics.get("paragraphs", []))
    base = body_sizes[len(body_sizes) // 2] if body_sizes else None
    for paragraph in metrics.get("paragraphs", []):
        if base and paragraph["size"] >= base * 1.18:
            paragraphs.setdefault(plain(paragraph["text"])[:60], {"size": "lead"})
    return headings, paragraphs
