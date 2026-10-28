"""Dependency-free CSS helpers shared by the anysite2grav scripts.

Parses the source stylesheets the audit caches in <migration>/css (index.json maps file → URL),
resolves custom properties and colors, and classifies a section's background into a theme
**tone** (light, muted, dark, accent) so pages carry a semantic style instead of raw builder classes.
"""

from __future__ import annotations

import colorsys
import re
from pathlib import Path

NAMED_COLORS = {
    "white": (255, 255, 255), "black": (0, 0, 0), "transparent": None,
    "gray": (128, 128, 128), "grey": (128, 128, 128), "silver": (192, 192, 192),
    "red": (255, 0, 0), "blue": (0, 0, 255), "green": (0, 128, 0), "navy": (0, 0, 128),
}
TONES = ("light", "muted", "dark", "accent")
# Per-page generated class names (Webflow w-node-*, WordPress wp-container-*/wp-elements-*): never design hooks.
GENERATED_CLASS = re.compile(r"^(w-node-|wp-container-|wp-elements-|wp-duotone-)|-[0-9a-f]{8,}$")
BACKGROUND_PROPERTY = re.compile(r"(?:^|;)\s*background(?:-color)?\s*:\s*([^;]+)", re.I)
CLASS_SELECTOR = re.compile(r"^((?:\.[A-Za-z_][\w-]*)+)$")


def css_blocks(css: str):
    """Yield (prelude, body) for top-level CSS blocks; @media bodies come back whole for a second pass."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    position, length = 0, len(css)
    while position < length:
        brace = css.find("{", position)
        if brace == -1:
            return
        prelude = css[position:brace].strip()
        depth, cursor = 1, brace + 1
        while cursor < length and depth:
            depth += {"{": 1, "}": -1}.get(css[cursor], 0)
            cursor += 1
        yield prelude, css[brace + 1:cursor - 1]
        position = cursor


def parse_color(value: str):
    """Return ((r, g, b), alpha) or (None, 0) for hex, rgb()/rgba() (comma or space syntax) and a few names."""
    value = value.strip().lower().replace("!important", "").strip()
    if value in NAMED_COLORS:
        rgb = NAMED_COLORS[value]
        return (rgb, 1.0) if rgb else (None, 0)
    match = re.fullmatch(r"#([0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})", value)
    if match:
        digits = match.group(1)
        if len(digits) in (3, 4):
            digits = "".join(character * 2 for character in digits)
        alpha = int(digits[6:8], 16) / 255 if len(digits) == 8 else 1.0
        return tuple(int(digits[index:index + 2], 16) for index in (0, 2, 4)), alpha
    match = re.fullmatch(r"rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:\s*[,/]\s*([\d.]+%?))?\s*\)", value)
    if match:
        alpha = match.group(4) or "1"
        alpha_value = float(alpha[:-1]) / 100 if alpha.endswith("%") else float(alpha)
        return tuple(int(float(match.group(index))) for index in (1, 2, 3)), alpha_value
    return None, 0


def to_hex(rgb) -> str:
    return "#" + "".join(f"{channel:02x}" for channel in rgb)


def luminance(rgb) -> float:
    def channel(value):
        value /= 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
    red, green, blue = (channel(value) for value in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def tone_of(rgb) -> str:
    """Semantic tone of a background color. Saturated colors are accents; greys sort by lightness."""
    _, lightness, saturation = colorsys.rgb_to_hls(*(channel / 255 for channel in rgb))
    if saturation > 0.35 and max(rgb) - min(rgb) > 48 and 0.12 < lightness < 0.92:
        return "accent"
    light = luminance(rgb)
    # Near-white only: an off-white band next to a white page is a visible step, so it's muted.
    if light >= 0.95:
        return "light"
    if light >= 0.45:
        return "muted"
    return "dark"


def css_pixels(value: str, viewport: float = 1440) -> float | None:
    """Approximate px for a length (px, rem/em, vw, %) or the middle term of clamp()/min()/max()."""
    lengths = []
    for number, unit in re.findall(r"(-?[\d.]+)(px|rem|em|vw|vh|%)?", value):
        try:
            amount = float(number)
        except ValueError:
            continue
        scale = {"px": 1, "rem": 16, "em": 16, "vw": viewport / 100, "vh": 9, "%": viewport / 100}.get(unit, 1 if amount == 0 else None)
        if scale is not None:
            lengths.append(amount * scale)
    if not lengths:
        return None
    return sorted(lengths)[len(lengths) // 2]


class SourceStyles:
    """Class → background lookups over the cached source CSS, with custom properties resolved."""

    def __init__(self, migration: Path):
        self.variables: dict[str, str] = {}
        # (class set, value) in source order; compound selectors like .section.black included.
        self.backgrounds: list[tuple[frozenset, str]] = []
        # Classes the source stylesheets actually style: the only ones worth keeping as hooks.
        self.styled: set[str] = set()
        self._seen: set[int] = set()
        index = migration / "css" / "index.json"
        if not index.exists():
            return
        import json
        for file_name in json.loads(index.read_text(encoding="utf-8")):
            path = migration / "css" / file_name
            if path.exists():
                self._load(path.read_text(encoding="utf-8", errors="replace"))

    def add_css(self, css: str):
        """Add inline <style> CSS (WordPress global styles, Webflow embeds). Identical blocks load once."""
        key = hash(css)
        if css.strip() and key not in self._seen:
            self._seen.add(key)
            self._load(css)

    def _load(self, css: str, responsive: bool = False):
        for prelude, body in css_blocks(css):
            if prelude.startswith(("@media", "@supports", "@layer")):
                # Variables inside at-rules still count; breakpoint-specific backgrounds don't set the tone.
                self._load(body, responsive=responsive or prelude.startswith("@media"))
                continue
            if prelude.startswith("@"):
                continue
            for declaration in body.split(";"):
                name, _, value = declaration.partition(":")
                name = name.strip()
                if name.startswith("--") and value.strip():
                    self.variables.setdefault(name, value.strip())
            if body.strip():
                for selector in prelude.split(","):
                    self.styled.update(re.findall(r"\.([A-Za-z_][\w-]*)", selector))
            match = BACKGROUND_PROPERTY.search(";" + body)
            if not match or responsive:
                continue
            for selector in (part.strip() for part in prelude.split(",")):
                compound = CLASS_SELECTOR.match(selector)
                if compound:
                    self.backgrounds.append((frozenset(compound.group(1).strip(".").split(".")), match.group(1).strip()))

    def resolve(self, value: str, depth: int = 0) -> str:
        if depth > 8:
            return value
        match = re.search(r"var\(\s*(--[\w-]+)\s*(?:,\s*([^)]+))?\)", value)
        if not match:
            return value
        replacement = self.variables.get(match.group(1)) or (match.group(2) or "")
        return self.resolve(value[:match.start()] + replacement + value[match.end():], depth + 1)

    def background_color(self, classes: list[str], inline_style: str = "") -> tuple | None:
        candidates = []
        inline = BACKGROUND_PROPERTY.search(";" + (inline_style or ""))
        if inline:
            candidates.append(inline.group(1))
        present = set(classes)
        # Most specific selector first; among equals, the later rule wins, as in the cascade.
        ranked = sorted(
            ((len(names), order, value) for order, (names, value) in enumerate(self.backgrounds) if names <= present),
            reverse=True,
        )
        candidates += [value for _, _, value in ranked]
        for candidate in candidates:
            resolved = self.resolve(candidate)
            for token in re.findall(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|\b[a-z]+\b", resolved):
                rgb, alpha = parse_color(token)
                if rgb and alpha >= 0.6:
                    return rgb
        return None

    def space(self, inline_style: str = "") -> str | None:
        """Semantic vertical padding (none|s|m|l|xl) from a section's inline padding.

        Block editors and builders write section spacing inline (style="padding-top:var(--…)"), which
        extraction would otherwise drop; a step on the theme's space scale keeps the rhythm editable.
        """
        style = inline_style or ""
        top = re.search(r"padding-(?:top|block-start)\s*:\s*([^;]+)", style)
        shorthand = re.search(r"(?:^|;)\s*padding(?:-block)?\s*:\s*([^;]+)", style)
        value = top.group(1) if top else (shorthand.group(1) if shorthand else None)
        if not value:
            return None
        resolved = self.resolve(value)
        if not resolved.strip().startswith(("clamp", "min", "max", "calc")):
            resolved = resolved.split()[0] if resolved.split() else resolved
        pixels = css_pixels(resolved)
        if pixels is None:
            return None
        return "none" if pixels < 4 else "s" if pixels <= 28 else "m" if pixels <= 56 else "l" if pixels <= 100 else "xl"

    def tone(self, classes: list[str], inline_style: str = "") -> str | None:
        rgb = self.background_color(classes, inline_style)
        return tone_of(rgb) if rgb else None
