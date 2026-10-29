"""Extraction, styling and crawl regressions. Stdlib only: python3 -m unittest discover -s <this-dir> -v."""

import http.server
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from csskit import SourceStyles, css_pixels, tone_of  # noqa: E402

GLOBAL_STYLES = """
:root { --wp--preset--color--charcoal-1: #1e1e1e; --wp--preset--color--light-grey-2: #f6f6f6;
        --wp--preset--color--blueberry-1: #3858e9; --wp--preset--spacing--60: clamp(40px, 5vw, 80px); }
.has-charcoal-1-background-color { background-color: var(--wp--preset--color--charcoal-1) !important; }
.has-light-grey-2-background-color { background-color: var(--wp--preset--color--light-grey-2) !important; }
.has-blueberry-1-background-color { background-color: var(--wp--preset--color--blueberry-1) !important; }
.has-heading-1-font-size { font-size: 70px; }
"""

BAND = """<div class="wp-block-group alignfull {cls}" style="padding-top:var(--wp--preset--spacing--60)">
  <h2 class="wp-block-heading has-heading-1-font-size">{title}</h2>
  <div class="wp-block-columns">
    <div class="wp-block-column"><p>{title} left column text that explains the feature.</p></div>
    <div class="wp-block-column"><figure><img src="/img/{slug}.png" alt="{title}"></figure></div>
  </div>
</div>"""


def block_theme_page(route: str) -> str:
    bands = "\n".join(
        BAND.format(cls=cls, title=title, slug=title.lower().replace(" ", "-"))
        for cls, title in [
            ("has-charcoal-1-background-color", "Design"), ("has-light-grey-2-background-color", "Build"),
            ("has-blueberry-1-background-color", "Extend"), ("", "Learn"), ("has-charcoal-1-background-color", "Community"),
        ]
    )
    return f"""<!doctype html><html lang="en"><head><title>Page {route}</title><style>{GLOBAL_STYLES}</style></head>
<body><a class="skip-link screen-reader-text" href="#wp--skip-link--target">Skip to content</a>
<div class="wp-site-blocks">
<header class="global-header wp-block-group">
  <figure class="wp-block-image"><a href="https://example.org/"><svg viewBox="0 0 28 28" role="img"><title>Example</title><path fill="currentColor" d="M0 0h28v28z"/></svg></a></figure>
  <nav class="wp-block-navigation"><ul class="wp-block-navigation__container">
    <li class="wp-block-navigation-item"><a href="/showcase/">Showcase</a></li>
    <li class="wp-block-navigation-item"><a href="/plugins/">Plugins</a></li>
    <li class="wp-block-navigation-item"><a href="https://shop.example.com/">Swag</a></li>
    <li class="wp-block-navigation-item has-child wp-block-navigation-submenu"><a href="/about/">About</a>
      <ul class="wp-block-navigation__submenu-container"><li><a href="/about/team/">Team</a></li><li><a href="/about/license/">License</a></li></ul></li>
  </ul></nav>
  <a class="global-header__get-wordpress" href="/download/">Get WordPress</a>
</header>
<main class="wp-block-group entry-content is-layout-constrained"><div class="wp-block-group alignfull">{bands}</div></main>
<footer class="global-footer"><ul><li><a href="/about/">About</a></li><li><a href="/news/">News</a></li></ul>
  <a href="https://github.com/example">GitHub</a></footer>
</div></body></html>"""


PROSE_PAGE = """<!doctype html><html lang="en"><head><title>Privacy</title></head><body>
<a class="skip-link screen-reader-text" href="#main">Skip</a>
<div class="wp-site-blocks"><header class="global-header"><nav><a href="/">Home</a><a href="/a/">A</a><a href="/b/">B</a></nav></header>
<main class="entry-content"><div class="wp-block-group">""" + "".join(
    f"<h2>Heading {index}</h2><p>{'Paragraph text about privacy and data. ' * 6}</p><p>{'More policy text. ' * 8}</p>" for index in range(6)
) + """</div></main><footer class="global-footer"><a href="/about/">About</a></footer></div></body></html>"""

CLASSIC_PAGE = """<!doctype html><html lang="en"><head><title>Hosting</title></head><body>
<header class="global-header"><nav><a href="/">Home</a><a href="/a/">A</a><a href="/b/">B</a></nav></header>
<div class="site"><main class="site-main"><article class="page"><div class="entry-content row">
  <section class="col-8"><h1>Hosting</h1><p>Choose a host.</p></section>
  <section><h2>Recommended</h2><ul><li>Host one</li><li>Host two</li></ul><img src="/a.png" alt="a"></section>
  <section class="col-8"><h2>Requirements</h2><p>PHP and MySQL.</p></section>
</div></article></main></div>
<footer class="global-footer"><a href="/about/">About</a></footer></body></html>"""


def run_extract(pages: dict[str, str]) -> Path:
    from extract_content import main as extract_main

    root = Path(tempfile.mkdtemp(prefix="extract-test-"))
    (root / "html").mkdir()
    entries = []
    for index, (route, markup) in enumerate(pages.items()):
        name = f"page-{index}.html"
        (root / "html" / name).write_text(markup, encoding="utf-8")
        entries.append({"route": route, "url": "https://example.org" + route, "html_file": f"html/{name}", "lang": "en", "title": route})
    (root / "routes.json").write_text(json.dumps({"source": "https://example.org/", "pages": entries}))
    argv = sys.argv
    sys.argv = ["extract_content.py", str(root)]
    try:
        extract_main()
    finally:
        sys.argv = argv
    return root


class ExtractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = run_extract({"/": block_theme_page("/"), "/features": block_theme_page("/features"), "/privacy": PROSE_PAGE, "/hosting": CLASSIC_PAGE})
        cls.index = {page["route"]: page for page in json.loads((cls.root / "content-index.json").read_text())["pages"]}

    def record(self, route):
        return json.loads((self.root / self.index[route]["file"]).read_text())

    def test_block_theme_page_splits_into_bands_not_one_html_blob(self):
        record = self.record("/")
        self.assertEqual(record["kind"], "sections", "entry-content on <main> must not make a composed page an article")
        self.assertEqual(len(record["sections"]), 5)
        self.assertEqual(json.loads((self.root / "content-index.json").read_text())["quality"]["monolith_pages"], [])

    def test_sections_carry_semantic_tone_space_and_columns(self):
        sections = self.record("/")["sections"]
        self.assertEqual([section.get("tone") for section in sections], ["dark", "muted", "accent", None, "dark"])
        self.assertTrue(all(section.get("space") == "l" for section in sections))
        columns = sections[0]["blocks"][1]
        self.assertEqual(columns["type"], "columns")
        self.assertEqual(len(columns["columns"]), 2)
        self.assertEqual(sections[0]["blocks"][0]["classes"], ["has-heading-1-font-size"], "only classes the source CSS styles are kept")

    def test_block_navigation_header_becomes_chrome(self):
        chrome = json.loads((self.root / "chrome.json").read_text())["en"]
        self.assertEqual([item["label"] for item in chrome["menu"]], ["Showcase", "Plugins", "Swag", "About"])
        self.assertEqual([cta["label"] for cta in chrome["ctas"]], ["Get WordPress"])
        self.assertIn("viewBox", chrome["logo"]["svg"], "inline SVG logos keep SVG attribute case")
        self.assertNotIn("Skip to content", json.dumps(self.record("/")))

    def test_prose_page_is_one_article(self):
        record = self.record("/privacy")
        self.assertEqual(record["kind"], "article")
        self.assertIn("## Heading 0", record["body_markdown"])

    def test_classic_theme_descends_into_wrapper_holding_main(self):
        self.assertEqual(len(self.record("/hosting")["sections"]), 3)


class CssTests(unittest.TestCase):
    def test_compound_selectors_and_variables_resolve(self):
        styles = SourceStyles(Path("/nonexistent"))
        styles.add_css(".section.black { background-color: var(--dark); } :root { --dark: rgb(17 17 17); } .section { background: #fff; }")
        self.assertEqual(styles.tone(["section", "black"]), "dark")
        self.assertEqual(styles.tone(["section"]), "light")
        self.assertIsNone(styles.tone(["plain"]))

    def test_tones_and_lengths(self):
        self.assertEqual(tone_of((56, 88, 233)), "accent")
        self.assertEqual(tone_of((255, 255, 255)), "light")
        self.assertEqual(tone_of((240, 237, 231)), "muted")
        self.assertEqual(tone_of((200, 200, 200)), "muted")
        self.assertEqual(css_pixels("5rem"), 80)
        self.assertEqual(css_pixels("clamp(40px, 5vw, 80px)"), 72)

    def test_ported_source_css_is_deduplicated(self):
        from scaffold_theme import port_source_css

        with tempfile.TemporaryDirectory() as directory:
            migration, theme = Path(directory) / "migration", Path(directory) / "theme"
            (migration / "css").mkdir(parents=True)
            theme.mkdir()
            rule = ".hero { padding: 4rem; } @media (max-width: 600px) { .hero { padding: 1rem; } } .wp-container-core-group-is-layout-1a2b3c4d { gap: 1rem; }"
            index = {}
            for number in range(5):
                (migration / "css" / f"{number}.css").write_text(rule)
                index[f"{number}.css"] = f"https://example.org/page-{number}.css"
            (migration / "css" / "index.json").write_text(json.dumps(index))
            css, ported = port_source_css(migration, theme, {"hero"})
        self.assertEqual(ported, 2)
        self.assertEqual(css.count(".src-hero {"), 2, "once at top level, once inside the merged @media")
        self.assertEqual(css.count("@media"), 1)
        self.assertNotIn("wp-container", css)


class CrawlTests(unittest.TestCase):
    def test_trailing_slash_redirect_does_not_loop(self):
        from crawl_site import fetch

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - http.server API
                if self.path == "/about":
                    self.send_response(301)
                    self.send_header("Location", "/about/")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><body>about</body></html>")

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        result = fetch(f"http://127.0.0.1:{server.server_port}/about")
        self.assertEqual(result["status"], 200)
        self.assertTrue(result["url"].endswith("/about/"))


POST = """<li class="wp-block-post post type-post"><header class="entry-header">
  <h3 class="wp-block-post-title"><a href="/news/2026/10/{slug}/">{title}</a></h3>
  <div class="wp-block-post-terms"><a href="/news/category/releases/">Releases</a>, <a href="/news/category/security/">Security</a></div>
  <div class="wp-block-post-date"><time datetime="2026-10-{day}T10:00:00+00:00">October {day}, 2026</time></div></header>
  <p>Excerpt for {title}, with enough words to count as a summary.</p></li>"""


class ListingTests(unittest.TestCase):
    def blocks(self, markup):
        from extract_content import extract_blocks
        from htmlkit import parse_html

        return extract_blocks(parse_html(markup).find("body"), "https://example.org/news/", {})

    def test_post_list_becomes_listing_with_terms_dates_and_full_text(self):
        posts = "".join(POST.format(slug=f"post-{day}", title=f"Release {day}", day=day) for day in (10, 11, 12, 13))
        blocks = self.blocks(f"<html><body><ul class='wp-block-post-template'>{posts}</ul></body></html>")
        listing = blocks[0]
        self.assertEqual(listing["type"], "listing")
        self.assertEqual(len(listing["items"]), 4)
        item = listing["items"][0]
        self.assertEqual((item["title"], item["date"][:10]), ("Release 10", "2026-10-10"))
        self.assertEqual([term["label"] for term in item["terms"]], ["Releases", "Security"], "the entry header must not be mistaken for the site menu")
        self.assertEqual(listing["taxonomy"], "category")
        self.assertTrue(any("Excerpt for Release 10" in block.get("text", "") for block in item["blocks"]))

    def test_navigation_and_plain_cards_are_not_listings(self):
        menu = "<nav><ul>" + "".join(f"<li class='wp-block-navigation-item'><a href='/a{index}/'>Item {index}</a></li>" for index in range(5)) + "</ul></nav>"
        cards = "<div class='grid'>" + "".join(f"<div class='feature'><h3>Feature {index}</h3><p>Text {index}</p><a href='/f{index}/'>More</a></div>" for index in range(4)) + "</div>"
        for markup in (menu, cards):
            types = [block["type"] for block in self.blocks(f"<html><body>{markup}</body></html>")]
            self.assertNotIn("listing", types, markup[:40])

    def test_slides_in_a_list_keep_their_structure(self):
        slide = "<ul><li><h1>Showcase</h1><p>The best websites, built with WordPress.</p><img src='/s.png' alt='site'></li></ul>"
        types = [block["type"] for block in self.blocks(f"<html><body>{slide}</body></html>")]
        self.assertEqual(types[:3], ["heading", "text", "image"])


class LayoutTests(unittest.TestCase):
    def test_section_split_and_dividers(self):
        import layoutkit

        style = layoutkit.section_style({
            "background": "rgb(35, 40, 45)", "padding": [80, 80], "borderTop": None, "borderBottom": {"width": 1, "color": "rgb(0,0,0)"},
            "align": "start", "grid": {"tracks": [358, 1002], "headingColumn": 0, "divider": True},
        })
        self.assertEqual((style["tone"], style["space"], style["divider"]), ("dark", "l", "bottom"))
        self.assertEqual((style["layout"], style["ratio"], style["split_divider"]), ("split", [1.0, 2.75], True))

    def test_item_grid_style(self):
        import layoutkit

        style = layoutkit.block_style({
            "perRow": 5, "rowWidths": [288] * 5, "gap": [0, 0], "width": 1440, "viewport": 1440,
            "child": {"background": None, "border": None, "shadow": False, "dividers": False},
            "image": {"ratio": 1.0, "filter": "grayscale(1)"},
        }, "collection")
        self.assertEqual(style, {"per_row": 5, "card": "plain", "image_ratio": "1/1", "image_filter": "grayscale", "bleed": True, "gap": "none"})

    def test_type_scale_covers_rare_large_sizes(self):
        import layoutkit

        headings = [{"size": size, "family": "Inter", "text": "x"} for size in [160] + [90] + [50] * 20 + [36] * 10 + [24] * 8 + [18] * 6 + [14] * 4]
        scale = layoutkit.type_scale({"/": {"sections": {"a": {"headings": headings, "paragraphs": []}}, "blocks": {}}})
        self.assertEqual(scale[0], ("display", 160))
        self.assertEqual(layoutkit.size_step(90, scale) in ("xl", "display"), True)
        self.assertEqual(layoutkit.size_step(50, scale), next(name for name, size in scale if size == 50))

    def test_header_variants_group_by_tone(self):
        import layoutkit

        routes = {
            "/": {"chrome": {"header": {"background": "rgb(255, 255, 255)", "color": "rgb(0, 0, 0)"}}},
            "/news": {"chrome": {"header": {"background": "rgb(35, 40, 45)", "color": "rgb(255, 255, 255)"}}},
            "/showcase": {"chrome": {"header": {"background": "rgb(30, 30, 30)", "color": "rgb(255, 255, 255)"}}},
        }
        variants = layoutkit.header_variants(routes)
        self.assertEqual(variants["routes"], {"/news": "alt", "/showcase": "alt"})

    def test_root_variables_are_scoped_and_never_override_tokens(self):
        from scaffold_theme import port_source_css

        with tempfile.TemporaryDirectory() as directory:
            migration, theme = Path(directory) / "migration", Path(directory) / "theme"
            (migration / "css").mkdir(parents=True)
            theme.mkdir()
            (migration / "css" / "0.css").write_text(":root { --font-body: 16px; --brand: var(--brand-base); --brand-base: #3858e9; --unused: 1px; } .hero { color: var(--brand); font-size: var(--font-body); }")
            (migration / "css" / "index.json").write_text(json.dumps({"0.css": "https://example.org/a.css"}))
            css, _ = port_source_css(migration, theme, {"hero"}, reserved={"font-body"})
        self.assertIn("--brand: var(--brand-base)", css)
        self.assertIn("--brand-base: #3858e9", css)
        self.assertNotIn("--unused", css)
        self.assertNotIn("--font-body: 16px", css)


class ControlsAndChromeTests(unittest.TestCase):
    def blocks(self, markup):
        from extract_content import extract_blocks
        from htmlkit import parse_html

        return extract_blocks(parse_html(markup).find("body"), "https://example.org/themes/", {})

    def test_pagination_is_left_to_the_collection_and_tabs_keep_the_active_item(self):
        markup = """<html><body><ul><li class="current-menu-item"><a href="/themes/">Popular</a></li><li><a href="/themes/browse/new/">Latest</a></li></ul>
          <nav class="wp-block-query-pagination"><a href="/themes/page/2/">2</a><a href="/themes/page/49/">49</a></nav></body></html>"""
        blocks = self.blocks(markup)
        self.assertEqual([block["type"] for block in blocks], ["list"])
        self.assertEqual(blocks[0]["active"], 0)

    def test_control_targets(self):
        markup = """<html><body><button aria-controls="filters">Layout 0</button><div class="dropdown" id="filters"><p>x</p></div>
          <button aria-controls="pane-2">Tab two</button><div id="pane-2"><p>Pane</p></div><button aria-controls="gone">Ghost</button></body></html>"""
        targets = {block["label"]: block.get("_target") for block in self.blocks(markup) if block["type"] == "button"}
        self.assertEqual(targets, {"Layout 0": "dialog", "Tab two": "content", "Ghost": "missing"})

    def test_ported_rules_keep_visual_properties_only(self):
        from scaffold_theme import visual_declarations

        kept = visual_declarations("display: contents; background-color: #23282d !important; color: #fff; grid-template-columns: 1fr 1fr; margin: 0 auto; border-bottom: 1px solid #ccc")
        self.assertEqual(kept, "background-color:#23282d;color:#fff;border-bottom:1px solid #ccc")

    def test_header_and_list_tokens(self):
        import layoutkit

        routes = {"/": {"chrome": {"header": {"background": "rgb(255,255,255)", "color": "rgb(0,0,0)", "height": 70,
            "logo": {"left": 20, "right": 50, "height": 30}, "nav": {"left": 80, "size": 14, "weight": "400", "paddingX": 10, "gap": 20},
            "cta": {"size": 14, "weight": "700", "padding": [10, 19], "radius": "2px", "right": 20}}},
            "input": {"background": "rgb(246, 246, 246)", "border": None, "radius": "2px", "height": 40, "size": 14}}}
        tokens = layoutkit.header_tokens(routes)
        self.assertEqual((tokens["header-width"], tokens["header-gutter"], tokens["nav-start"]), ("100%", "20px", "0"))
        self.assertEqual((tokens["input-bg"], tokens["input-border"], tokens["button-padding"]), ("#f6f6f6", "0", "10px 19px"))
        self.assertEqual(layoutkit.block_style({"list": True, "inline": True, "activeBackground": "rgb(30,30,30)", "size": 14}, "list"), {"style": "tabs", "size": "small"})


if __name__ == "__main__":
    unittest.main()
