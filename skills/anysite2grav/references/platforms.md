# Platform notes

Identify the platform from `audit.md` ("platform" rows) or the `generator` meta in `routes.json`.

## Webflow

- Often no or incomplete `sitemap.xml`; the crawl finds the rest. Unknown paths can return a branded 404 page; the random-path probe catches soft 404s.
- Assets on `cdn.prod.website-files.com` / `assets.website-files.com`; file names start with a 24-hex asset id (stripped on import). `srcset` holds the full-size original: the importer takes the largest candidate.
- Text often sits in bare `<div>`s (`text-block-7`), not `<p>`: the extractor keeps leaf text.
- Dropdowns: `.w-dropdown` / custom `nav-link` + `drop-down-menu`. Locales: `.w-locales-list` (subdirectory locales `/es`, `/fr` with hreflang).
- Forms: `.w-form` with `data-name`. Webflow processes submissions itself (and may forward to integrations configured in Site settings → Forms). Success/fail blocks `.w-form-done` / `.w-form-fail`. Export past submissions from the Webflow dashboard (CSV) if the user needs history.
- Interactions (IX2) are runtime JS (`data-w-id`): reimplement what matters.
- CMS collections paginate with `?<hash>_page=2`. Crawl with `--keep-query _page` to reach every item, then drop the query from routes.
- Popups are hidden sections (`popup-wrapper`, `modal`) opened by `href="#"` buttons plus custom code: wire CTAs to the generated `<dialog>`s.

## WordPress

- `wp-sitemap.xml` or Yoast/RankMath `sitemap_index.xml` (robots.txt lists it). Content in `.entry-content`/`.wp-block-*`: mostly articles → Markdown bodies.
- The REST API (`/wp-json/wp/v2/posts?per_page=100`) can supply clean post bodies, dates, authors, categories and tags. Prefer it for blogs, and map taxonomies to Grav `taxonomy:` (`category`, `tag`) with a blog listing page (`content.items: '@self.children'`, pagination).
- Forms: Contact Form 7 (`.wpcf7`), Gravity Forms (`gform_`), WPForms, Elementor forms: all server-side, so rebuild them with Grav Form.
- Shortcode leftovers (`[gallery]`) and page builders (Elementor, Divi) produce deep wrapper markup; pass `--main-selector` if sections come out empty.

## Squarespace

- `sitemap.xml` is reliable. Images on `images.squarespace-cdn.com`: add `?format=2500w` for originals (the importer keeps the query).
- Blocks: `.sqs-block` (`html`, `image`, `gallery`, `form`). Forms post to Squarespace's own handler; newsletter blocks connect to Mailchimp or Squarespace email.

## Wix

- Content is mostly rendered by JS. If `routes.json` pages have little text, render with a headless browser first (below). Images on `static.wixstatic.com` with transform segments; strip `/v1/fill/...` to get originals.

## Framer

- Static HTML with generated class names (`framer-xyz`); layout clusters still work. Assets on `framerusercontent.com`. Animations are runtime: reimplement the important ones. Forms post to Framer's handler.

## Shopify

- Migrating a storefront to Grav usually means content pages only; keep commerce on Shopify (Buy Button / links) unless the user asks otherwise. `/products/*.json` exposes product data.

## JavaScript-rendered sites (SPAs)

When the cached HTML lacks the visible content (empty `<div id="root">`), render each route in a headless browser and overwrite `migration/html/<file>` with `document.documentElement.outerHTML` after the network settles. Keep the file names from `routes.json` (`html_file`). Then run `extract_content.py` as usual. `capture_pages.mjs` already drives Playwright and can be adapted for this. Watch for content that only appears after interaction (tabs, accordions) and expand it before dumping.
