# anysite2grav

An agent skill that turns a live website into a local [Grav 2](https://getgrav.org) site as close to 1:1 as it can get, then hands your agent the keys.

**Overview:** open [`docs/index.html`](docs/index.html) in a browser for a visual walkthrough.

**Website:** [anysite2grav.djamil.dev](https://anysite2grav.djamil.dev).

Give it a URL and it will:

1. **Install the latest Grav + Admin2** in a new folder and start it (PHP's built-in server or Docker).
2. **Set up the API and MCP first.** It creates an admin account, an API key and an MCP launcher, and registers it with Claude Code, Codex or Cursor, so your agent can work in the site straight away.
3. **Discover every route.** It reads robots.txt and the sitemaps, then crawls the site, since many builders don't publish a complete sitemap. It also detects soft 404s, redirects, languages and PDFs.
4. **Audit the site.** It inventories analytics and third-party tags with their IDs, every form (including ones in modals), embeds, inline code, fonts and the palette.
5. **Ask what matters, then wait.** Theme name, Tailwind or built-in CSS, native multilang or per-language trees, how each form should deliver (save, email, webhook, keep the embed), the CAPTCHA provider (Grav's built-in Cap by default), and whether analytics are ported (production hosts only). Nothing is built until you answer.
6. **Recreate the content.** One Grav page per URL, with the exact title and meta, OG tags, provenance, structured `sections` (headings, text, lists, columns, images, galleries, card grids, background videos, buttons, embeds, forms, modals) or Markdown for articles. Pages are always Markdown + frontmatter, never copied source HTML. Pages with more than three horizontal sections become **modular pages**, one module per section (hero, cards, gallery, form, shared, section), each with its own Admin form and media. Shorter pages stay single pages. Shared sections are stored once, missing parents are created, source redirects are kept, and media is deduped by hash into page or site media.
7. **Build a standalone theme** from the source's measured styles, standardized: sections pick a `tone` (light, muted, dark, accent) and `space` step defined once as theme tokens, and the source's own CSS is ported once, deduplicated. The header, dropdown menus, CTAs, language switcher and footer are all editable in Admin, alongside reusable blueprints, preview-host `noindex`, host-gated analytics, a `DESIGN.md`, and an optional Tailwind 4 build. Selected official Quark2 conventions make templates and assets easier to extend while preserving your site's design.
8. **Convert forms** into Grav Form pages (XHR submit, Cap) embedded wherever the source showed them.
9. **Iterate to parity.** It captures source and local screenshots side by side and runs a route-by-route verifier (status, titles, text coverage, media, forms, leftover CDN assets, `lang`/hreflang, noindex, analytics leakage, redirects) until both agree.

## Install

### Codex

Paste this prompt into Codex (not your terminal):

```text
$skill-installer Install anysite2grav from https://github.com/w00fz/anysite2grav/tree/main/skills/anysite2grav
```

Codex's bundled installer can install skills from GitHub repositories. If the skill does not appear, restart Codex. See the [official installation guidance](https://learn.chatgpt.com/docs/build-skills#install-curated-skills-for-local-use).

<details>
<summary>Manual installation / development</summary>

Use a linked working copy when you want to edit the skill or update it with Git:

```bash
git clone https://github.com/w00fz/anysite2grav.git ~/Projects/anysite2grav
mkdir -p ~/.agents/skills
ln -s ~/Projects/anysite2grav/skills/anysite2grav ~/.agents/skills/anysite2grav
```

Update the working copy with `git pull`. Codex supports symlinked skill folders in its [documented local skill locations](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills).

</details>

### Claude Code

Install as a plugin:

```text
/plugin marketplace add w00fz/anysite2grav
/plugin install anysite2grav@anysite2grav
```

Or link a local working copy:

```bash
mkdir -p ~/.claude/skills
ln -s "$PWD/skills/anysite2grav" ~/.claude/skills/anysite2grav
```

Other agents that support the [Agent Skills](https://agentskills.io) format can load `skills/anysite2grav/`.

The repository is private; installation requires GitHub read access.

## Use

> Convert https://example.com to Grav.

> Use $anysite2grav to rebuild our Webflow site locally in ~/Sites/example-grav, with Tailwind.

The skill walks through 13 checkpoints and stops to ask before anything that is the user's call (global client config, form delivery, analytics, licenses).

## Theme conventions

The scaffold draws on a [source-linked review of official Quark2](skills/anysite2grav/references/quark2-conventions.md): deferred head assets for embedded plugins, focused Twig blocks, reusable page fields, translated navigation labels and current-page semantics. It remains a standalone theme built from the source site's styles.

Project CSS goes in `css/custom.css`, after the generated build. A forced scaffold rebuild preserves settings edited in Admin, custom CSS and theme blueprints. Use `--force --reset-config` to deliberately recreate site settings from the audit, or `--force-templates` to replace skeleton files and the theme blueprint. See the [theme guide](skills/anysite2grav/references/theme.md) before customizing.

## Requirements

- PHP 8.3+ with `curl ctype dom gd json mbstring openssl session simplexml xml zip` (recommended: `intl yaml apcu opcache`), or Docker
- Python 3.9+ (standard library only)
- Node 18+ (for `grav-mcp`, Tailwind and Playwright screenshots, installed on demand)

## Layout

```
skills/anysite2grav/
  SKILL.md                 workflow, decisions, invariants
  references/              setup, content model, theme, forms, analytics/SEO, platforms, verification
  scripts/                 crawl, audit, extract, media, pages, theme, forms, capture, verify, install, MCP
  assets/theme/            standalone Grav theme skeleton
  assets/docker/           optional Docker runtime (Grav + Admin2, Mailpit)
  agents/openai.yaml       Codex UI metadata
docs/                      static overview site
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

## Validate theme changes

Use PHP 8.3+ and an installed Grav 2 runtime for the regression suite. It creates temporary sites and leaves that runtime unchanged:

```bash
GRAV_TEST_ROOT=/path/to/grav python3 -m unittest discover -s skills/anysite2grav/tests -v
```

The checks cover configuration preservation and explicit resets, plain CSS/Tailwind scaffolds, blueprint imports and modular controls, deferred assets, and embedded Form/Cap rendering with cold and warm caches. Project acceptance still includes an Admin edit and browser form submission.

## Publish the overview

The existing `docs/` page is hosted with Cloudflare Workers Static Assets at [anysite2grav.djamil.dev](https://anysite2grav.djamil.dev). The configuration targets the personal Cloudflare account named **Djamil** and the `anysite2grav` Worker.

With Node.js 22.18 or later:

```bash
npm ci
npx cf auth login
npx cf deploy --dry-run
npm run deploy

# Publish the permanent redirect from the previous hostname
npm run deploy:legacy
```

The default deployment publishes `docs/`. Legacy mode publishes only `hosting/legacy/` to the previous `website2grav` Worker, permanently redirecting its custom-domain and workers.dev URLs to the canonical site while retaining paths and query strings. Cloudflare manages the custom domain's DNS and HTTPS certificate. Deployment is manual; pushing to GitHub does not publish the site.

## License

MIT
