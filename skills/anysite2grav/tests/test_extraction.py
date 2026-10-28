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


if __name__ == "__main__":
    unittest.main()
