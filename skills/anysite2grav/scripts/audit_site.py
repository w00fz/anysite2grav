#!/usr/bin/env python3
"""Audit crawled pages for analytics, third-party scripts, forms, embeds and style.

Usage:
  audit_site.py migration [--no-css]

Reads <migration>/routes.json + html/, writes:
  <migration>/audit.json   machine-readable findings
  <migration>/audit.md     summary to review with the user (analytics, forms, fonts, palette)
  <migration>/css/         downloaded stylesheets (unless --no-css)
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from htmlkit import normalize_space, normalize_url, parse_html, read_json, short_hash, write_json  # noqa: E402

# name -> (category, detection regex, id-capture regex or None)
TRACKERS = {
    "Google Tag Manager": ("analytics", r"googletagmanager\.com/gtm\.js|GTM-[A-Z0-9]{4,}", r"\b(GTM-[A-Z0-9]{4,})\b"),
    "Google Analytics 4": ("analytics", r"gtag/js\?id=G-|gtag\(\s*['\"]config['\"]\s*,\s*['\"]G-", r"\b(G-[A-Z0-9]{6,12})\b"),
    "Universal Analytics (retired)": ("analytics", r"UA-\d{4,}-\d+|google-analytics\.com/analytics\.js", r"\b(UA-\d{4,}-\d+)\b"),
    "Google Ads": ("ads", r"gtag\(\s*['\"]config['\"]\s*,\s*['\"]AW-|googleadservices", r"\b(AW-\d{6,})\b"),
    "Meta Pixel": ("ads", r"connect\.facebook\.net/[^'\"]*/fbevents\.js|fbq\(", r"fbq\(\s*['\"]init['\"]\s*,\s*['\"](\d+)"),
    "LinkedIn Insight": ("ads", r"snap\.licdn\.com|_linkedin_partner_id", r"_linkedin_partner_id\s*=\s*['\"]?(\d+)"),
    "X/Twitter Pixel": ("ads", r"static\.ads-twitter\.com|twq\(", r"twq\(\s*['\"]config['\"]\s*,\s*['\"](\w+)"),
    "TikTok Pixel": ("ads", r"analytics\.tiktok\.com|ttq\.load", r"ttq\.load\(\s*['\"](\w+)"),
    "Pinterest Tag": ("ads", r"s\.pinimg\.com/ct/core\.js|pintrk\(", r"pintrk\(\s*['\"]load['\"]\s*,\s*['\"](\d+)"),
    "Reddit Pixel": ("ads", r"redditstatic\.com/ads/pixel\.js|rdt\(", r"rdt\(\s*['\"]init['\"]\s*,\s*['\"]([\w-]+)"),
    "HubSpot tracking": ("marketing", r"js(?:-na\d)?\.hs-scripts\.com|js\.hs-analytics\.net", r"hs-scripts\.com/(\d+)\.js"),
    "HubSpot forms": ("forms", r"js\.hsforms\.net|hbspt\.forms\.create", r"portalId['\"]?\s*:\s*['\"]?(\d+)"),
    "Marketo": ("marketing", r"munchkin\.js|marketo\.com", r"Munchkin\.init\(\s*['\"]([\w-]+)"),
    "Pardot": ("marketing", r"pi\.pardot\.com|piAId", r"piAId\s*=\s*['\"](\d+)"),
    "Klaviyo": ("marketing", r"static\.klaviyo\.com", r"company_id=(\w+)"),
    "Mailchimp": ("marketing", r"list-manage\.com|chimpstatic\.com", None),
    "Intellimize": ("analytics", r"cdn\.intellimize\.co", r"intellimize\.co/snippet/(\d+)\.js"),
    "Mouseflow": ("analytics", r"cdn\.mouseflow\.com|window\._mfq", r"mouseflow\.com/projects/([\w-]+)\.js"),
    "Google Translate widget": ("ui", r"translate\.google\.com/translate_a|google\.translate\.TranslateElement", None),
    "Hotjar": ("analytics", r"static\.hotjar\.com|hjid", r"hjid\s*:\s*(\d+)"),
    "Microsoft Clarity": ("analytics", r"clarity\.ms/tag", r"clarity\.ms/tag/['\"]?\+?\s*['\"]?(\w+)|\(window,\s*document,\s*['\"]clarity['\"],\s*['\"]script['\"],\s*['\"](\w+)"),
    "Segment": ("analytics", r"cdn\.segment\.com", r"analytics\.load\(\s*['\"](\w+)"),
    "Mixpanel": ("analytics", r"cdn\.mxpnl\.com|mixpanel\.init", r"mixpanel\.init\(\s*['\"](\w+)"),
    "Heap": ("analytics", r"cdn\.heapanalytics\.com|heap\.load", r"heap\.load\(\s*['\"](\d+)"),
    "Amplitude": ("analytics", r"cdn\.amplitude\.com|amplitude\.getInstance", None),
    "PostHog": ("analytics", r"posthog\.init|i\.posthog\.com", r"posthog\.init\(\s*['\"](phc_\w+)"),
    "Plausible": ("analytics", r"plausible\.io/js", r"data-domain=['\"]([^'\"]+)"),
    "Fathom": ("analytics", r"cdn\.usefathom\.com", r"data-site=['\"](\w+)"),
    "Simple Analytics": ("analytics", r"scripts\.simpleanalyticscdn\.com", None),
    "Umami": ("analytics", r"umami\.(?:is|js)|data-website-id", r"data-website-id=['\"]([\w-]+)"),
    "Matomo": ("analytics", r"matomo\.js|piwik\.js|_paq\.push", r"setSiteId['\"]\s*,\s*['\"]?(\d+)"),
    "Cloudflare Web Analytics": ("analytics", r"static\.cloudflareinsights\.com/beacon", r"\"token\"\s*:\s*\"(\w+)\""),
    "Vercel Analytics": ("analytics", r"/_vercel/insights|va\.vercel-scripts\.com", None),
    "Intercom": ("chat", r"widget\.intercom\.io|intercomSettings", r"app_id['\"]?\s*:\s*['\"](\w+)"),
    "Drift": ("chat", r"js\.driftt\.com|drift\.load", r"drift\.load\(\s*['\"](\w+)"),
    "Crisp": ("chat", r"client\.crisp\.chat", r"CRISP_WEBSITE_ID\s*=\s*['\"]([\w-]+)"),
    "Tawk.to": ("chat", r"embed\.tawk\.to", None),
    "Zendesk": ("chat", r"static\.zdassets\.com", None),
    "Calendly": ("embed", r"assets\.calendly\.com|calendly\.com/[\w-]+", r"calendly\.com/([\w/-]+)"),
    "Typeform": ("forms", r"embed\.typeform\.com|form\.typeform\.com", None),
    "Jotform": ("forms", r"jotform\.com", None),
    "Google Forms": ("forms", r"docs\.google\.com/forms", None),
    "Google reCAPTCHA": ("captcha", r"google\.com/recaptcha|grecaptcha", r"data-sitekey=['\"]([\w-]+)"),
    "Cloudflare Turnstile": ("captcha", r"challenges\.cloudflare\.com/turnstile", None),
    "OneTrust": ("consent", r"cdn\.cookielaw\.org|optanon", None),
    "Cookiebot": ("consent", r"consent\.cookiebot\.com", None),
    "CookieYes": ("consent", r"cdn-cookieyes\.com", None),
    "Termly": ("consent", r"app\.termly\.io", None),
    "Osano": ("consent", r"cmp\.osano\.com", None),
    "YouTube embed": ("embed", r"youtube(?:-nocookie)?\.com/embed", None),
    "Vimeo embed": ("embed", r"player\.vimeo\.com", None),
    "Wistia": ("embed", r"fast\.wistia\.(?:com|net)", None),
    "Google Maps": ("embed", r"maps\.googleapis\.com|google\.com/maps/embed", None),
    "Lottie": ("ui", r"lottie(?:-web|files)?|bodymovin", None),
    "Webflow runtime": ("platform", r"webflow\.[\w.]*js|data-wf-page", None),
    "WordPress": ("platform", r"/wp-content/|/wp-includes/", None),
    "Squarespace": ("platform", r"static1\.squarespace\.com|squarespace-cdn", None),
    "Wix": ("platform", r"static\.wixstatic\.com|wix-code", None),
    "Framer": ("platform", r"framerusercontent\.com|framer\.com/m/", None),
    "Shopify": ("platform", r"cdn\.shopify\.com", None),
    "Google Fonts": ("fonts", r"fonts\.googleapis\.com|fonts\.gstatic\.com", None),
    "Adobe Fonts (Typekit)": ("fonts", r"use\.typekit\.net", r"use\.typekit\.net/(\w+)\.css"),
    "Font Awesome": ("fonts", r"fontawesome|font-awesome", None),
}
SEARCH_SCRIPT_LIMIT = 400_000


def classify_form(form, inline_text: str) -> str:
    action = form.get("action").lower()
    if "w-form" in " ".join(node.get("class") for node in [form, *form.ancestors()]) or form.get("data-name"):
        return "webflow"
    if "hsforms" in action or "hubspot" in action:
        return "hubspot"
    if "list-manage.com" in action:
        return "mailchimp"
    for marker, provider in (("formspree", "formspree"), ("getform", "getform"), ("usebasin", "basin"), ("formsubmit", "formsubmit"), ("netlify", "netlify"), ("klaviyo", "klaviyo"), ("pardot", "pardot"), ("marketo", "marketo")):
        if marker in action:
            return provider
    if form.get("data-netlify") or form.get("netlify") is not None and "netlify" in form.attrs:
        return "netlify"
    if form.get("role") == "search" or any(field.get("type") == "search" for field in form.find_all("input")) or re.search(r"/search\b", action):
        return "search"
    if "wpcf7" in form.get("class") or "gform" in form.get("id"):
        return "wordpress-plugin"
    return "custom" if action else "javascript-handled"


def label_for(field, form, labels_by_id) -> str:
    if field.get("id") and field.get("id") in labels_by_id:
        return labels_by_id[field.get("id")]
    for ancestor in field.ancestors():
        if ancestor.tag == "label":
            return normalize_space(ancestor.text())
        if ancestor is form:
            break
    return field.get("aria-label") or field.get("placeholder") or field.get("data-name") or ""


def extract_forms(document, page_url: str, lang: str | None = None):
    """Forms on a page. The signature includes the page language so each translation keeps its labels."""
    forms = []
    for form in document.find_all("form"):
        labels_by_id = {label.get("for"): normalize_space(label.text()) for label in form.find_all("label") if label.get("for")}
        fields = []
        for field in form.find_all("input", "select", "textarea", "button"):
            kind = field.get("type", "text").lower() if field.tag == "input" else field.tag
            if field.tag == "button" or kind in ("submit", "button", "image", "reset"):
                continue
            entry = {
                "name": field.get("name") or field.get("data-name") or field.get("id"),
                "type": kind,
                "label": label_for(field, form, labels_by_id),
                "required": "required" in field.attrs or field.get("aria-required") == "true",
            }
            if field.get("placeholder"):
                entry["placeholder"] = field.get("placeholder")
            if kind == "hidden":
                entry["value"] = field.get("value")
            if field.tag == "select":
                entry["options"] = [{"value": option.get("value", normalize_space(option.text())), "label": normalize_space(option.text())} for option in field.find_all("option")]
            if kind in ("checkbox", "radio") and field.get("value"):
                entry["value"] = field.get("value")
            for attribute in ("pattern", "maxlength", "minlength", "min", "max", "autocomplete"):
                if field.get(attribute):
                    entry[attribute] = field.get(attribute)
            fields.append(entry)
        submit = next((node for node in form.find_all("input", "button") if node.get("type", "submit" if node.tag == "button" else "").lower() == "submit"), None)
        container = form.parent
        success = failure = None
        success_links = []
        if container is not None:
            for sibling in container.element_children():
                if sibling.has_class("w-form-done") or "success" in sibling.get("class").lower():
                    success = normalize_space(sibling.text())
                    # Download-gated forms reveal the file in the success block.
                    success_links = [{"label": normalize_space(anchor.text()), "url": normalize_url(anchor.get("href"), page_url, keep_query=True)} for anchor in sibling.find_all("a") if anchor.get("href")]
                if sibling.has_class("w-form-fail") or "error" in sibling.get("class").lower():
                    failure = normalize_space(sibling.text())
        provider = classify_form(form, "")
        if provider == "search":
            continue
        names = sorted(field["name"] or "" for field in fields if field["type"] != "hidden")
        forms.append({
            "signature": short_hash(provider + "|" + (form.get("action") or "") + "|" + ",".join(names) + "|" + (lang or "")),
            "lang": lang,
            "provider": provider,
            "name": form.get("data-name") or form.get("name") or form.get("id") or form.get("aria-label") or None,
            "action": normalize_url(form.get("action"), page_url, keep_query=True) if form.get("action") else None,
            "method": (form.get("method") or "get").lower(),
            "fields": fields,
            "submit_label": (submit.get("value") or normalize_space(submit.text())) if submit else None,
            "success_message": success,
            "success_links": [link for link in success_links if link["url"]],
            "heading": next((normalize_space(node.text()) for node in form.find_all("h1", "h2", "h3", "h4", "h5") if node.text()), None),
            # Copy inside the form that isn't a label (consent lines, helper text).
            "notes": [text for text in (normalize_space(node.text()) for node in form.find_all("p") if not any(ancestor.tag == "label" for ancestor in node.ancestors())) if text],
            "error_message": failure,
            "in_dialog": any(ancestor.tag == "dialog" or "modal" in ancestor.get("class").lower() or "popup" in ancestor.get("class").lower() for ancestor in form.ancestors()),
        })
    return forms


def css_digest(css_texts: list[str]):
    fonts, families, colors, variables, breakpoints, widths = [], Counter(), Counter(), {}, Counter(), Counter()
    for css in css_texts:
        for block in re.findall(r"@font-face\s*{([^}]*)}", css, re.I):
            family = re.search(r"font-family\s*:\s*['\"]?([^;'\"]+)", block, re.I)
            weight = re.search(r"font-weight\s*:\s*([^;]+)", block, re.I)
            style = re.search(r"font-style\s*:\s*([^;]+)", block, re.I)
            sources = re.findall(r"url\(\s*['\"]?([^'\")]+)", block)
            fonts.append({"family": family and family.group(1).strip(), "weight": weight and weight.group(1).strip(), "style": style and style.group(1).strip(), "src": sources[:3]})
        for value in re.findall(r"font-family\s*:\s*([^;}{]+)", css, re.I):
            families[value.strip().split(",")[0].strip("'\" ")] += 1
        for value in re.findall(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b|rgba?\([^)]+\)|hsla?\([^)]+\)", css):
            colors[value.lower().replace(" ", "")] += 1
        for name, value in re.findall(r"(--[\w-]+)\s*:\s*([^;}{]+)", css):
            variables.setdefault(name, value.strip())
        for value in re.findall(r"@media[^{]*?(?:max|min)-width\s*:\s*(\d+(?:\.\d+)?)px", css, re.I):
            breakpoints[float(value)] += 1
        for value in re.findall(r"max-width\s*:\s*(\d{3,4})px", css, re.I):
            widths[int(value)] += 1
    unique_fonts = list({(font["family"], font["weight"], font["style"]): font for font in fonts}.values())
    return {
        "font_faces": unique_fonts,
        "font_families": families.most_common(12),
        "colors": colors.most_common(40),
        "custom_properties": dict(list(variables.items())[:200]),
        "breakpoints": sorted(breakpoints, key=lambda width: -breakpoints[width])[:8],
        "container_widths": widths.most_common(6),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("migration", nargs="?", default="migration")
    parser.add_argument("--no-css", action="store_true", help="skip downloading stylesheets")
    args = parser.parse_args()
    root = Path(args.migration)
    routes = read_json(root / "routes.json")
    pages = routes["pages"]

    tracker_hits: dict[str, dict] = {}
    inline_scripts: dict[str, dict] = {}
    external_scripts: Counter = Counter()
    stylesheets: Counter = Counter()
    forms: dict[str, dict] = {}
    iframes: Counter = Counter()
    head_meta: Counter = Counter()
    for page in pages:
        markup = (root / page["html_file"]).read_text(encoding="utf-8")
        document = parse_html(markup)
        scripts = document.find_all("script")
        haystack = markup[:SEARCH_SCRIPT_LIMIT * 4]
        for name, (category, detect, capture) in TRACKERS.items():
            if re.search(detect, haystack, re.I):
                entry = tracker_hits.setdefault(name, {"category": category, "ids": set(), "pages": 0})
                entry["pages"] += 1
                if capture:
                    for match in re.finditer(capture, haystack):
                        value = next((group for group in match.groups() if group), None)
                        if value:
                            entry["ids"].add(value)
        for script in scripts:
            if script.get("src"):
                external_scripts[normalize_url(script.get("src"), page["url"], keep_query=True) or script.get("src")] += 1
                continue
            body = "".join(child for child in script.children if isinstance(child, str)).strip()
            kind = script.get("type") or "text/javascript"
            if not body or kind in ("application/ld+json", "application/json", "text/template", "text/x-template"):
                if kind == "application/ld+json" and body:
                    head_meta["json-ld"] += 1
                continue
            key = short_hash(body)
            entry = inline_scripts.setdefault(key, {"preview": body[:240], "length": len(body), "pages": 0, "in_head": any(a.tag == "head" for a in script.ancestors())})
            entry["pages"] += 1
        for link in document.find_all("link"):
            rel = link.get("rel").lower()
            if "stylesheet" in rel:
                stylesheets[normalize_url(link.get("href"), page["url"], keep_query=True)] += 1
            elif rel in ("icon", "shortcut icon", "apple-touch-icon", "manifest"):
                head_meta[f"{rel}: {link.get('href')}"] += 1
        for frame in document.find_all("iframe"):
            source = frame.get("src") or frame.get("data-src")
            if source:
                iframes[urlsplit(normalize_url(source, page["url"], keep_query=True) or source).netloc] += 1
        for form in extract_forms(document, page["url"], (page.get("lang") or "").split("-")[0].lower() or None):
            entry = forms.setdefault(form["signature"], {**form, "pages": []})
            entry["pages"].append(page["route"])

    css_texts = []
    css_index: dict[str, str] = {}
    if not args.no_css:
        (root / "css").mkdir(exist_ok=True)
        for index, url in enumerate(sorted(url for url in stylesheets if url)):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 anysite2grav"})
                css = urllib.request.urlopen(request, timeout=30).read().decode("utf-8", errors="replace")
            except Exception as error:  # noqa: BLE001 - best effort, recorded below
                print(f"stylesheet failed {url}: {error}", file=sys.stderr)
                continue
            name = f"{index:02d}-{short_hash(url, 8)}.css"
            (root / "css" / name).write_text(css, encoding="utf-8")
            css_index[name] = url
            css_texts.append(css)
    if css_index:
        write_json(root / "css" / "index.json", css_index)
    for page in pages[:1]:
        markup = (root / page["html_file"]).read_text(encoding="utf-8")
        css_texts.extend(re.findall(r"<style[^>]*>(.*?)</style>", markup, re.S | re.I))

    trackers = {name: {**entry, "ids": sorted(entry["ids"])} for name, entry in sorted(tracker_hits.items(), key=lambda item: (item[1]["category"], item[0]))}
    audit = {
        "source": routes["source"],
        "page_count": len(pages),
        "trackers": trackers,
        "external_scripts": external_scripts.most_common(),
        "inline_scripts": sorted(inline_scripts.values(), key=lambda entry: -entry["pages"]),
        "stylesheets": stylesheets.most_common(),
        "iframes": iframes.most_common(),
        "forms": sorted(forms.values(), key=lambda form: -len(form["pages"])),
        "head": head_meta.most_common(30),
        "style": css_digest(css_texts),
    }
    write_json(root / "audit.json", audit)
    (root / "audit.md").write_text(render_markdown(audit), encoding="utf-8")
    print(f"{len(trackers)} third-party technologies, {len(forms)} distinct forms, {len(inline_scripts)} inline scripts. See {root / 'audit.md'}")
    return 0


def render_markdown(audit: dict) -> str:
    lines = [f"# Audit of {audit['source']} ({audit['page_count']} pages)", ""]
    by_category = defaultdict(list)
    for name, entry in audit["trackers"].items():
        by_category[entry["category"]].append((name, entry))
    lines += ["## Third-party technologies", "", "| Category | Technology | IDs | Pages |", "| --- | --- | --- | --- |"]
    for category in sorted(by_category):
        for name, entry in by_category[category]:
            lines.append(f"| {category} | {name} | {', '.join(entry['ids']) or '—'} | {entry['pages']} |")
    lines += ["", "## Forms", ""]
    if not audit["forms"]:
        lines.append("No HTML forms found (check for JS-injected or iframe forms above).")
    for index, form in enumerate(audit["forms"], 1):
        fields = ", ".join(f"{field['name']}:{field['type']}{'*' if field['required'] else ''}" for field in form["fields"] if field["type"] != "hidden")
        lines.append(f"{index}. **{form['name'] or 'unnamed'}** — provider `{form['provider']}`, {form['method'].upper()} {form['action'] or '(no action)'}; fields {fields}; submit “{form['submit_label']}”; on {len(form['pages'])} page(s) e.g. `{form['pages'][0]}`" + (" — inside a modal" if form["in_dialog"] else ""))
        if form.get("success_message"):
            lines.append(f"   - success: “{form['success_message'][:140]}”")
    lines += ["", "## Inline scripts (custom code to port or drop)", ""]
    for script in audit["inline_scripts"][:15]:
        preview = script["preview"].replace("\n", " ")[:160].replace("|", "\\|")
        lines.append(f"- {script['pages']} page(s), {script['length']} chars{' (head)' if script['in_head'] else ''}: `{preview}`")
    style = audit["style"]
    lines += ["", "## Style digest", "", "Font families (by usage): " + ", ".join(f"{family} ({count})" for family, count in style["font_families"]), ""]
    lines.append("Font faces: " + ", ".join(sorted({f"{face['family']} {face['weight'] or ''}".strip() for face in style["font_faces"] if face["family"]})))
    lines += ["", "Top colors: " + ", ".join(f"`{color}`×{count}" for color, count in style["colors"][:20]), ""]
    lines.append("Breakpoints: " + ", ".join(f"{int(width)}px" for width in style["breakpoints"]))
    lines.append("Container widths: " + ", ".join(f"{width}px" for width, _ in style["container_widths"]))
    lines += ["", "## External scripts", ""] + [f"- {count}× {url}" for url, count in audit["external_scripts"][:25]]
    lines += ["", "## Iframes", ""] + [f"- {count}× {host}" for host, count in audit["iframes"]]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
