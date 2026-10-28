"""Grav-side helpers: a conservative YAML emitter, page files, and config merges."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

PLAIN_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]*$")
SCRIPTS = Path(__file__).resolve().parent


def _scalar(value) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    # JSON escapes are valid in YAML double-quoted scalars (Symfony YAML parses them).
    return json.dumps(str(value), ensure_ascii=False)


def _key(key) -> str:
    key = str(key)
    return key if PLAIN_KEY.match(key) and key.lower() not in ("true", "false", "null", "yes", "no", "on", "off") else json.dumps(key, ensure_ascii=False)


def yaml_dump(value, indent: int = 0) -> str:
    pad = "  " * indent
    if isinstance(value, dict):
        if not value:
            return "{}"
        lines = []
        for key, inner in value.items():
            if isinstance(inner, (dict, list)) and inner:
                lines.append(f"{pad}{_key(key)}:\n{yaml_dump(inner, indent + 1)}")
            elif isinstance(inner, str) and "\n" in inner:
                body = "\n".join(f"{pad}  {line}" if line else "" for line in inner.split("\n"))
                lines.append(f"{pad}{_key(key)}: |-\n{body}")
            else:
                lines.append(f"{pad}{_key(key)}: {yaml_dump(inner, indent + 1) if isinstance(inner, (dict, list)) else _scalar(inner)}")
        return "\n".join(lines)
    if isinstance(value, list):
        if not value:
            return "[]"
        lines = []
        for item in value:
            if isinstance(item, dict) and item:
                rendered = yaml_dump(item, indent + 1)
                first, _, rest = rendered.lstrip().partition("\n")
                lines.append(f"{pad}- {first}" + (f"\n{rest}" if rest else ""))
            elif isinstance(item, list) and item:
                lines.append(f"{pad}-\n{yaml_dump(item, indent + 1)}")
            elif isinstance(item, str) and "\n" in item:
                body = "\n".join(f"{pad}    {line}" if line else "" for line in item.split("\n"))
                lines.append(f"{pad}- |-\n{body}")
            else:
                lines.append(f"{pad}- {_scalar(item) if not isinstance(item, (dict, list)) else yaml_dump(item)}")
        return "\n".join(lines)
    return _scalar(value)


def write_page(path: Path, header: dict, body: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{yaml_dump(header)}\n---\n" + (f"\n{body.strip()}\n" if body and body.strip() else ""), encoding="utf-8")


def merge_config(grav_root: Path, relative: str, patch: dict) -> None:
    """Deep-merge a JSON patch into a Grav YAML file via Grav's Symfony YAML (lists replace)."""
    subprocess.run(
        ["php", str(SCRIPTS / "grav_config.php"), str(grav_root), "merge", relative, "-"],
        input=json.dumps(patch).encode(), check=True, stdout=subprocess.DEVNULL,
    )


def get_config(grav_root: Path, relative: str) -> dict:
    output = subprocess.run(["php", str(SCRIPTS / "grav_config.php"), str(grav_root), "get", relative], check=True, capture_output=True).stdout
    return json.loads(output or b"{}") or {}
