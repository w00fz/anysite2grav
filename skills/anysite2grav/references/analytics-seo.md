# Analytics and SEO

## Contents
- Porting analytics
- SEO parity checklist
- Preview hosts
- Sitemap, robots.txt, llms.txt

## Porting analytics

`audit_site.py` lists every tag with its IDs and page counts, plus inline scripts. Ask the user which to keep, then:

| Source | In Grav |
| --- | --- |
| Google Tag Manager | `analytics.gtm: GTM-XXXX` (head script + body `<noscript>`). If GA4 also appears and is configured inside GTM, set `ga4_via_gtm: true` to avoid double counting. |
| GA4 without GTM | `analytics.ga4: G-XXXX` |
| Meta Pixel, LinkedIn, HubSpot tracking, Hotjar, Heap, Clarity, Segment, Mouseflow… | Paste the vendor's current snippet into `analytics.head_snippets` / `body_snippets`. Copy from the source page, then check it against the vendor's docs. |
| Consent manager (OneTrust, Cookiebot…) | Port it first in `head_snippets` and confirm the other tags respect it. If the source had none but serves regulated regions, raise it with the user. |
| Builder-specific tags (Webflow analytics, Squarespace/Wix stats, A/B tools such as Intellimize) | Usually drop: they belong to the old platform. Confirm. |
| Google Translate widget, chat widgets, Calendly | Not analytics. Port as features if wanted. |

Always set `analytics.hosts` to the production hostnames. The theme loads nothing on other hosts or on `noindex_hosts`, so local and preview traffic never pollutes the client's data. Leave `enabled: false` until the user confirms. Verify with the page source (no `googletagmanager.com`, `fbevents.js`…) locally, and with the vendor's debugger on production.

## SEO parity checklist

- Same URLs (or 301s for every change), same `<title>` (`head_title`), same meta description, OG/Twitter tags, canonical pointing at the page itself.
- `<html lang>` per language; hreflang alternates plus `x-default` for translated pages.
- Headings: one H1 per page, same text as the source.
- Structured data: if the source has JSON-LD (`audit.json → head: json-ld`), port it to the matching template. Use only markup that describes real content, never fake reviews, FAQs or authors.
- Images: alt text preserved; sized derivatives; `width`/`height` to avoid layout shift.
- Performance: enable `system.cache.allow_webserver_gzip: true` when Apache/nginx compress responses (Grav otherwise disables compression of dynamic HTML). Long cache headers for CSS/JS/fonts/images, small JS, subset fonts.

## Preview hosts

Development and preview copies must not be indexed. The theme sends `noindex, nofollow` (meta + `X-Robots-Tag`) for hosts in `noindex_hosts`. Add every local and tunnel hostname. Do **not** add `Disallow: /` to robots.txt: crawlers need to fetch a page to see its noindex, and disallowed URLs can still be listed. For static files (PDFs, images) on a preview host, add the header at the web server too.

## Sitemap, robots.txt, llms.txt

- Sitemap: `php bin/gpm install sitemap -y`. Exclude `/forms/*`, `/shared/*` and other non-content pages (`sitemap: ignore: true` in their frontmatter; the form pages already have it). For multilang, enable the plugin's language alternates.
- robots.txt: port the source rules, but point `Sitemap:` at the new site's sitemap URL. Grav serves `robots.txt` from the webroot.
- llms.txt: if the source had one, port it. If the user wants one, keep it curated: an H1, a summary, links to canonical pages. It doesn't affect Google ranking.
