#!/usr/bin/env python3
"""Convert the source site's forms into Grav Form pages, driven by an editable plan.

Usage:
  build_forms.py migration --grav grav --init        write migration/forms-plan.json (review it!)
  build_forms.py migration --grav grav               apply the plan → user/pages/forms/<name>/

The plan holds one entry per distinct source form with its fields, and the choices the user
makes (ask them; don't guess):
  delivery  any of "email", "save", "webhook:<url>" (custom action, needs a small plugin),
            or "embed" to keep a third-party embed (HubSpot/Typeform…) instead of a Grav form
  captcha   "cap" (Grav Form 9 built-in, invisible, no keys), "turnstile", "recaptcha",
            "basic", or "none"
  success   "message" (inline text), "redirect:<route>", or "display:<route>"
  email     {to, from, subject} — SMTP credentials go in env, never in YAML
Each form becomes /forms/<name> (template `form`, noindex, out of the sitemap) whose `action`
is its own route; pages embed it with a `form` block. Submissions use xhr_submit so modals and
footers show the result inline.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gravkit import get_config, merge_config, write_page  # noqa: E402
from htmlkit import read_json, site_key, slugify, write_json  # noqa: E402

FIELD_TYPES = {"text", "email", "tel", "url", "number", "date", "time", "textarea", "select", "checkbox", "radio", "hidden", "password", "file"}


def field_name(raw: str | None, used: set[str]) -> str:
    name = re.sub(r"[^a-z0-9_]+", "_", (raw or "field").lower()).strip("_") or "field"
    base, counter = name, 2
    while name in used:
        name, counter = f"{base}_{counter}", counter + 1
    used.add(name)
    return name


def grav_fields(source_fields: list[dict]) -> dict:
    """Map extracted HTML fields to a Grav Form `fields:` map, merging radio/checkbox groups."""
    groups: dict[str, list[dict]] = defaultdict(list)
    order: list[str] = []
    for field in source_fields:
        key = field.get("name") or field.get("label") or f"field{len(order)}"
        if key not in groups:
            order.append(key)
        groups[key].append(field)
    fields, used = {}, set()
    for key in order:
        members = groups[key]
        first = members[0]
        kind = first["type"] if first["type"] in FIELD_TYPES else "text"
        name = field_name(key, used)
        label = (first.get("label") or key).strip().rstrip("*").strip()
        entry: dict = {"type": kind, "label": label}
        if kind == "radio" or (kind == "checkbox" and len(members) > 1):
            entry = {"type": "radio" if kind == "radio" else "checkboxes", "label": label,
                     "options": {member.get("value") or slugify(member.get("label") or "option"): member.get("label") or member.get("value") for member in members}}
        elif kind == "select":
            options = {option["value"]: option["label"] for option in first.get("options", []) if option.get("value")}
            placeholder = next((option["label"] for option in first.get("options", []) if not option.get("value")), None)
            entry["options"] = options
            if placeholder:
                entry["placeholder"] = placeholder
        elif kind == "hidden":
            # Label only appears in saved/emailed submissions.
            entry = {"type": "hidden", "label": key.replace("-", " ").replace("_", " ").strip().capitalize(), "default": first.get("value") or ""}
        elif kind == "checkbox":
            entry["label"] = label
        if first.get("placeholder") and kind not in ("select", "hidden"):
            entry["placeholder"] = first["placeholder"]
        if first.get("autocomplete"):
            entry["autocomplete"] = first["autocomplete"]
        validate = {}
        if first.get("required"):
            validate["required"] = True
        if kind == "email":
            validate["type"] = "email"
        for attribute, key_name in (("pattern", "pattern"), ("maxlength", "max"), ("minlength", "min")):
            if first.get(attribute):
                validate[key_name] = first[attribute]
        if validate:
            entry["validate"] = validate
        fields[name] = entry
    return fields


def init_plan(migration: Path) -> dict:
    audit = read_json(migration / "audit.json")
    page_map = read_json(migration / "page-map.json")
    names = page_map.get("forms", {})
    languages = {route: info["lang"] for route, info in page_map["pages"].items()}
    trackers = audit.get("trackers", {})
    embeds = [name for name, entry in trackers.items() if entry["category"] == "forms"]
    forms = []
    for form in audit.get("forms", []):
        langs = [form["lang"]] if form.get("lang") else sorted({languages.get(route, page_map.get("default_lang")) for route in form["pages"]})
        forms.append({
            "name": names.get(form["signature"], slugify(form.get("name") or "form")),
            "signature": form["signature"],
            "source_name": form.get("name"),
            "provider": form["provider"],
            "languages": langs,
            "used_on": form["pages"][:20],
            "in_modal": form.get("in_dialog", False),
            "enabled": True,
            "delivery": None,
            "captcha": None,
            "success": None,
            "submit_label": form.get("submit_label") or "Submit",
            "success_message": form.get("success_message") or "Thank you! Your submission has been received.",
            "success_links": form.get("success_links", []),
            "heading": form.get("heading"),
            "notes": form.get("notes", []),
            "error_message": form.get("error_message"),
            "fields": grav_fields(form["fields"]),
        })
    return {
        "_instructions": "Ask the user, then fill defaults (or per-form overrides). delivery: email|save|webhook:<url>|embed; captcha: cap|turnstile|recaptcha|basic|none; success: message|redirect:<route>|display:<route>.",
        "defaults": {
            "delivery": ["save"],
            "captcha": "cap",
            "success": "message",
            "email": {"to": "{{ config.plugins.email.to }}", "from": "{{ config.plugins.email.from }}", "subject": "[{{ site.title }}] {{ form.name }} submission"},
        },
        "third_party_embeds_detected": embeds,
        "forms": forms,
    }


def process_actions(form: dict, settings: dict) -> list:
    actions: list = []
    for delivery in settings["delivery"]:
        if delivery == "email":
            email = settings["email"]
            actions.append({"email": {"from": email["from"], "to": email["to"], "subject": email["subject"].replace("{{ form.name }}", form["name"]), "body": "{% include 'forms/data.html.twig' %}"}})
        elif delivery == "save":
            actions.append({"save": {"fileprefix": f"{form['name']}-", "dateformat": "Ymd-His-u", "extension": "txt", "body": "{% include 'forms/data.txt.twig' %}"}})
        elif delivery.startswith("webhook:"):
            actions.append({"webhook": {"url": delivery.split(":", 1)[1]}})
    success = settings["success"]
    if success.startswith("redirect:"):
        actions.append({"redirect": success.split(":", 1)[1]})
    elif success.startswith("display:"):
        actions.append({"display": success.split(":", 1)[1]})
    else:
        message = form["success_message"]
        links = [link for link in form.get("success_links", []) if link.get("url")]
        if links:
            # Download-gated forms: show the file links the source revealed after submit.
            message = f"<p>{message}</p>" + "".join(f'<p><a class="btn btn--primary" href="{link["url"]}">{link["label"] or "Download"}</a></p>' for link in links)
        actions.append({"message": message})
    actions.append({"reset": True})
    return actions


def captcha_field(provider: str):
    if provider in (None, "none"):
        return None
    if provider == "basic":
        return {"type": "basic-captcha", "label": "Are you human?"}
    return {"type": "captcha", "provider": provider}


def local_document(url: str, manifest: dict, site: str) -> str:
    entry = manifest.get(url)
    if entry and entry.get("file") and entry.get("scope") == "document":
        return "/user/media/files/" + re.sub(r"^[0-9a-f]{12}-", "", entry["file"])
    parts = urlsplit(url)
    return parts.path or "/" if site_key(parts.hostname or "") == site else url


def apply_plan(migration: Path, grav: Path) -> None:
    plan = read_json(migration / "forms-plan.json")
    manifest = read_json(migration / "media-manifest.json") if (migration / "media-manifest.json").exists() else {}
    site = site_key(urlsplit(read_json(migration / "routes.json")["source"]).hostname or "")
    for form in plan["forms"]:
        for link in form.get("success_links", []):
            link["url"] = local_document(link["url"], manifest, site)
    page_map = read_json(migration / "page-map.json")
    native = page_map["mode"] == "native"
    default_lang = page_map.get("default_lang", "en")
    defaults = plan["defaults"]
    wants_email = any("email" in ((form.get("delivery") or defaults["delivery"]) or []) for form in plan["forms"] if form.get("enabled", True))
    email_config = get_config(grav, "user/config/plugins/email.yaml")
    if wants_email and not (email_config.get("to") and email_config.get("from")):
        # Grav's email action throws (HTTP 500 on submit) when no recipient is configured.
        raise SystemExit("email delivery chosen but user/config/plugins/email.yaml has no from/to. Configure the Email plugin "
                         "(SMTP host via config, password via env), or use Mailpit locally, then rerun.")
    written, embeds, providers = 0, 0, set()
    for form in plan["forms"]:
        if not form.get("enabled", True):
            continue
        settings = {key: form.get(key) if form.get(key) is not None else defaults.get(key) for key in ("delivery", "captcha", "success", "email")}
        if "embed" in (settings["delivery"] or []):
            embeds += 1
            continue
        fields = {}
        if form.get("heading"):
            fields["form_heading"] = {"type": "display", "markdown": True, "content": f"### {form['heading']}"}
        fields.update(form["fields"])
        for index, note in enumerate(form.get("notes") or [], 1):
            fields[f"form_note_{index}"] = {"type": "display", "markdown": True, "content": note}
        captcha = captcha_field(settings["captcha"])
        if captcha:
            fields["captcha"] = captcha
            providers.add(settings["captcha"])
        route = f"/forms/{form['name']}"
        header = {
            "title": form.get("source_name") or form["name"].replace("-", " ").title(),
            "visible": False,
            "noindex": True,
            "cache_enable": False,
            "sitemap": {"ignore": True},
            "form": {
                "name": form["name"],
                "action": route,
                # keep_alive loads Form's jQuery-based form.min.js; the theme ships no jQuery.
                "xhr_submit": True,
                "fields": fields,
                "buttons": [{"type": "submit", "value": form["submit_label"]}],
                "process": process_actions(form, settings),
            },
        }
        folder = grav / "user" / "pages" / "forms" / form["name"]
        for lang in form["languages"] or [default_lang]:
            write_page(folder / (f"form.{lang}.md" if native else "form.md"), header)
            written += 1
            if not native:
                break
    stub = grav / "user" / "pages" / "forms" / (f"default.{default_lang}.md" if native else "default.md")
    if not stub.exists():
        write_page(stub, {"title": "Forms", "routable": False, "visible": False})
    form_config: dict = {}
    if "cap" in providers:
        form_config["cap"] = {"mode": "invisible", "storage": "grav-cache", "challenge_difficulty": 4}
    if "turnstile" in providers:
        form_config["turnstile"] = {"site_key": "", "secret_key": ""}
    if "recaptcha" in providers:
        form_config["recaptcha"] = {"version": "3", "site_key": "", "secret_key": ""}
    if form_config:
        merge_config(grav, "user/config/plugins/form.yaml", form_config)
    print(f"{written} form page files; {embeds} kept as third-party embeds; captcha providers: {sorted(providers) or 'none'}")
    if {"turnstile", "recaptcha"} & providers:
        print("Set CAPTCHA keys in user/config/plugins/form.yaml (site key) and env (secret) before testing.")
    if not wants_email:
        print("Submissions are saved to user/data/<form>/ only. Add \"email\" to delivery once the Email plugin is configured.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("migration", nargs="?", default="migration")
    parser.add_argument("--grav", required=True)
    parser.add_argument("--init", action="store_true", help="write forms-plan.json with defaults for review")
    args = parser.parse_args()
    migration, grav = Path(args.migration), Path(args.grav)
    if args.init or not (migration / "forms-plan.json").exists():
        plan = init_plan(migration)
        write_json(migration / "forms-plan.json", plan)
        print(f"wrote {migration / 'forms-plan.json'} with {len(plan['forms'])} forms; review choices with the user, then rerun without --init")
        for form in plan["forms"]:
            print(f"  - {form['name']}: {len(form['fields'])} fields, {form['languages']}, used on {len(form['used_on'])} page(s){' (modal)' if form['in_modal'] else ''}")
        return 0
    apply_plan(migration, grav)
    return 0


if __name__ == "__main__":
    sys.exit(main())
