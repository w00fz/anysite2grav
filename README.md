# website-to-grav

An agent skill that turns a live website into a local [Grav 2](https://getgrav.org) site as close to 1:1 as it can get, then hands your agent the keys.

**Overview:** open [`docs/index.html`](docs/index.html) in a browser for a visual walkthrough.

Give it a URL and it will:

1. **Install the latest Grav + Admin2** in a new folder and start it (PHP's built-in server or Docker).
2. **Set up the API and MCP first.** It creates an admin account, an API key and an MCP launcher, and registers it with Claude Code, Codex or Cursor, so your agent can work in the site straight away.
3. **Discover every route.** It reads robots.txt and the sitemaps, then crawls the site, since many builders don't publish a complete sitemap. It also detects soft 404s, redirects, languages and PDFs.
4. **Audit the site.** It inventories analytics and third-party tags with their IDs, every form (including ones in modals), embeds, inline code, fonts and the palette.
5. **Ask what matters.** Theme name, Tailwind or plain CSS, native multilang or per-language trees, how each form should deliver (save, email, webhook, keep the embed), the CAPTCHA provider (Grav's built-in Cap by default), and whether analytics are ported (production hosts only).
6. **Recreate the content.** One Grav page per URL, with the exact title and meta, OG tags, provenance, structured `sections` (headings, text, lists, images, galleries, card grids, background videos, buttons, embeds, forms, modals) or Markdown for articles. Pages with more than three horizontal sections become **modular pages**, one module per section (hero, cards, gallery, form, shared, section), each with its own Admin form and media. Shorter pages stay single pages. Shared sections are stored once, missing parents are created, source redirects are kept, and media is deduped by hash into page or site media.
7. **Build a standalone theme** from the source's measured styles. The header, dropdown menus, CTAs, language switcher and footer are all editable in Admin, alongside Admin2 blueprints, preview-host `noindex`, host-gated analytics, a `DESIGN.md`, and an optional Tailwind 4 build.
8. **Convert forms** into Grav Form pages (XHR submit, Cap) embedded wherever the source showed them.
9. **Iterate to parity.** It captures source and local screenshots side by side and runs a route-by-route verifier (status, titles, text coverage, media, forms, leftover CDN assets, `lang`/hreflang, noindex, analytics leakage, redirects) until both agree.

## Install

**Claude Code** (as a plugin):

```
/plugin marketplace add w00fz/grav-skills
/plugin install website-to-grav@grav-skills
```

Or copy (or symlink) the skill folder into your personal skills directory:

```bash
ln -s "$PWD/skills/website-to-grav" ~/.claude/skills/website-to-grav
```

**Codex**:

```bash
ln -s "$PWD/skills/website-to-grav" ~/.codex/skills/website-to-grav
```

Other agents that support the [Agent Skills](https://agentskills.io) format can load `skills/website-to-grav/` the same way.

## Use

> Convert https://example.com to Grav.

> Use $website-to-grav to rebuild our Webflow site locally in ~/Sites/example-grav, with Tailwind.

The skill walks through 13 checkpoints and stops to ask before anything that is the user's call (global client config, form delivery, analytics, licenses).

## Requirements

- PHP 8.3+ with `curl ctype dom gd json mbstring openssl session simplexml xml zip` (recommended: `intl yaml apcu opcache`), or Docker
- Python 3.9+ (standard library only)
- Node 18+ (for `grav-mcp`, Tailwind and Playwright screenshots, installed on demand)

## Layout

```
skills/website-to-grav/
  SKILL.md                 workflow, decisions, invariants
  references/              setup, content model, theme, forms, analytics/SEO, platforms, verification
  scripts/                 crawl, audit, extract, media, pages, theme, forms, capture, verify, install, MCP
  assets/theme/            standalone Grav theme skeleton
  assets/docker/           optional Docker runtime (Grav + Admin2, Mailpit)
  agents/openai.yaml       Codex UI metadata
docs/                      GitHub Pages overview site
```

## Scripts at a glance

| Script | Does |
| --- | --- |
| `install_grav.sh` | latest grav-admin into `<project>/grav`, PHP checks |
| `serve_grav.sh` | PHP built-in server start/stop/status |
| `bootstrap_access.sh` | admin user, API key, `bin/grav-mcp`, `.mcp.json` (idempotent, `--rotate-key`) |
| `crawl_site.py` | sitemap + crawl → `routes.json`, cached HTML, redirects |
| `audit_site.py` | trackers, forms, embeds, inline code, fonts, palette → `audit.md` |
| `extract_content.py` | sections/blocks, chrome (menus/footer), shared sections, layout clusters |
| `import_media.py` | download once, SHA-256 dedupe, assign page/shared/theme/document scope |
| `build_pages.py` | Grav page tree (modular pages above 3 sections), frontmatter, media placement, languages, redirects |
| `scaffold_theme.py` | theme from skeleton + tokens + navigation config, optional Tailwind |
| `build_forms.py` | forms plan → `/forms/<name>` Grav Form pages + CAPTCHA config |
| `capture_pages.mjs` | Playwright screenshots (source vs local) and computed design tokens |
| `verify_parity.py` | route-by-route parity report |
| `grav_config.php` | merge JSON into Grav YAML / lint frontmatter with Grav's own parser |

## License

MIT
