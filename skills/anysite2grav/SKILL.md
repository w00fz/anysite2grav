---
name: anysite2grav
description: Converts a live website (Webflow, WordPress, Squarespace, Wix, Framer or hand-built) into a local Grav 2 site with Admin2, the REST API and an MCP server wired for agents. It recreates every route as Grav pages with frontmatter and blueprints (modular pages for long composed pages), imports media, converts forms, ports analytics and builds a theme that mimics the source as closely as possible. Use when asked to migrate, clone, rebuild or port an existing site to Grav, or to scaffold a Grav copy of a URL.
---

# anysite2grav

Turn a live site into a local, editable Grav 2 copy that is as close to 1:1 as possible: same URLs and sitemap, same content and media, equivalent forms and analytics, a theme that looks the same, and an Admin + API + MCP setup so the user's agent can keep editing.

**Fidelity contract:** the deliverable is a new Grav site with a new theme and source-specific page/module templates, matching blueprints, Markdown content, and equivalent working features. The import scripts and generic theme produce a draft. Exact layout, responsive rules, typography, spacing, colors, highlights, borders and interaction states must survive the conversion. Read [references/fidelity.md](references/fidelity.md) before designing the content types or styling. Do not call the scaffold a finished migration.

All helpers live in `scripts/` (Python 3.9+ stdlib, PHP 8.3+, Node 18+). Run them from the project folder. Every script has `--help` and is safe to rerun.

## Project layout

```
<project>/            e.g. ~/Sites/acme-grav (ask; never inside the skill folder)
  grav/               Grav webroot: core + Admin2 + API + Login + Form + Email
  grav/user/          the site's source of truth (pages, config, theme) — the git repo
  migration/          crawl/extract artifacts, reports, screenshots (outside the webroot)
  .local/             credentials + server state (0600/0700, never commit, never print)
  bin/grav-mcp        MCP launcher (reads the key at start; client configs hold no secret)
  .mcp.json           Claude Code project MCP config
```

## Workflow

Copy this checklist into your progress notes and tick it off. Each phase ends with a check; don't start the next one until it passes.

```
- [ ] 1. Intake: confirm URL, project folder, runtime, agent clients
- [ ] 2. Grav + Admin2 installed, server running, admin login works
- [ ] 3. API key + MCP launcher; agent connected; list_pages works
- [ ] 4. Routes discovered (crawl_site.py) and reviewed with the user
- [ ] 5. Audit reviewed: analytics, forms, embeds, fonts, languages (audit_site.py)
- [ ] 6. STOP: decisions asked and answered (theme name, Tailwind or built-in CSS, languages, forms, analytics)
- [ ] 7. Source compositions and interactions inventoried at desktop/tablet/mobile; page/module types and blueprint fields mapped; content extracted and media imported
- [ ] 8. Draft content imported as native Markdown/frontmatter; omissions recorded; specialized type transforms are reproducible
- [ ] 9. New theme and one representative page finished with dedicated templates/blueprints, exact responsive styling and working plugins before expanding layouts
- [ ] 10. Forms converted and test-submitted (build_forms.py)
- [ ] 11. Analytics ported per the user's choice
- [ ] 12. Every route and design family checked; component/state measurements, full-color screenshots, interactions and CMS edits pass; no unapproved omissions
- [ ] 13. Final verification, git commit, handoff summary
```

### 1. Intake

Ask only what you can't infer, in one batch (use the structured question tool if available):

- **Project folder** (suggest `~/Sites/<domain>-grav`) and whether to `git init` `grav/user`.
- **Runtime**: PHP's built-in server via `scripts/serve_grav.sh` (default, zero setup), Docker, or an existing local stack (Valet, Herd, MAMP, Apache). See [references/setup.md](references/setup.md).
- **Which agent clients** to connect to MCP (Claude Code, Codex, Cursor, other).

### 2–3. Grav, Admin2, API and MCP first

Set up agent access before any content work so the user can follow along in Admin and their agent can help.

```bash
S=<skill-dir>/scripts
$S/install_grav.sh <project>                    # latest grav-admin; checks PHP + extensions
$S/serve_grav.sh <project> start --port 8000    # prints site/admin/api URLs
$S/bootstrap_access.sh <project>                # admin account, API key, bin/grav-mcp, .mcp.json
```

`bootstrap_access.sh` is idempotent: it creates credentials once in `.local/credentials.json` and reuses them, so connected agents keep working after restarts. Use `--rotate-key` only on request. Register the launcher with each chosen client (the script prints the exact command). Writing project files like `.mcp.json` is fine; **ask before editing global client config** (`~/.codex/config.toml`, `~/.claude.json`). Tell the user where the Admin password lives; never echo the key or password.

**Check:** `GET /api/v1/pages` returns 200 (the script reports it), the user can sign in at `/admin`, and after the client reconnects the agent can call `list_pages`. Setup details, Docker, HTTPS and least-privilege keys: [references/setup.md](references/setup.md).

### 4. Discover routes

```bash
python3 $S/crawl_site.py https://example.com --out migration [--alias www.example.com] [--keep-query page]
```

It seeds from `robots.txt` and sitemaps, then crawls same-site links: hosted builders often publish no sitemap or an incomplete one. For a scoped copy (only menu landing pages, one section), pass `--no-sitemaps` with `--include '<route regex>'` and/or `--max-depth N` instead of wrapping the script. A random-path probe detects soft-404 pages that answer 200. Report the route count, how many came only from crawling, languages, redirects, broken links and PDFs. If the output says TRUNCATED, raise `--max-pages`. If pages render client-side (empty HTML), see [references/platforms.md](references/platforms.md).

### 5. Audit

```bash
python3 $S/audit_site.py migration      # → migration/audit.md
```

Show the user `audit.md`: third-party tags with IDs (GTM, GA4, Meta, HubSpot, Hotjar, Heap…), every distinct form with its fields and where it appears (including modals), embeds (Calendly, YouTube, Typeform), inline custom code, fonts and palette.

### 6. Decisions to ask (after the audit, before building): a hard stop

**Stop here and ask; don't extract, build or scaffold until the user answers.** This holds in auto/unattended modes too: these choices shape every file you write, and defaulting silently is how a run ends up with a theme nobody asked for. Use the structured question tool if available; otherwise ask in chat and end your turn. Only skip a question the user already answered in their request, and say which answer you took from it.

Ask together, with a recommended default for each:

1. **Theme name** (slug) and **styling: Tailwind or built-in CSS?** Tailwind 4 CLI build (recommended when the user will keep iterating on design), or the built-in plain CSS (tokens + components, no build step). Always ask; never pick one silently.
2. **Languages** (only if more than one): native Grav multilang (`page.<lang>.md`, one tree; recommended when hreflang maps the pages) or separate trees per language prefix (`--languages trees`).
3. **Forms**: per form or as a default: delivery (save to `user/data`, email via SMTP, webhook, or keep a third-party embed), CAPTCHA (Grav's built-in **Cap**: invisible, self-hosted, no keys; Turnstile; reCAPTCHA; basic; none), success behavior (inline message, redirect, thank-you page). Options and trade-offs: [references/forms.md](references/forms.md).
4. **Analytics**: port as-is but load **only on the production hostname** (recommended), add consent gating, keep only some tags, or drop them. Details: [references/analytics-seo.md](references/analytics-seo.md).
5. **Site features** the audit and crawl found: inventory header search, pagination, filters, sorting, feeds, code, galleries and comments. A requested 1:1 copy already calls for reproducing these. Propose compatible core/plugin implementations and ask only about provider, paid-license or scope choices that need the user. A smaller crawl does not authorize removing features. Map: [references/grav-features.md](references/grav-features.md).

Record the answers (and the rejected options) in the project notes; later phases depend on them.

### 7–8. Source model, content and draft import

Before bulk implementation, inspect the rendered source and its CSS at multiple widths and applicable hover/focus/open/selected states. Use [references/fidelity.md](references/fidelity.md) to map each distinct composition to a named page or module kind, its blueprint fields, Markdown body, media and plugins. Recover exact responsive rules from source CSS; a desktop measurement alone is insufficient. Use extracted blocks as import data, not as a ceiling on the new theme's design.

The following imports a draft tree. Finish one representative page per design family before expanding its specialized templates across the site.

```bash
python3 $S/extract_content.py migration          # sections → blocks, chrome, listings, clusters
node $S/measure_layout.mjs --migration migration --source https://example.com   # computed layout per section/block
python3 $S/import_media.py migration             # download once, dedupe by hash
python3 $S/build_pages.py migration --grav grav --allow-incomplete [--languages native|trees] [--template-map map.json] [--modular-threshold 3] [--collections auto|off]
(cd grav && bin/gpm install <plugins chosen in phase 6> -y)
php $S/grav_config.php grav lint user            # every frontmatter + YAML parses
```

- `extract_content.py` keeps **every text block**, including the leaf `<div>`/`<span>` text that builders use instead of `<p>`, and repeated card grids, side-by-side `columns`, galleries, background videos and modals. It splits site chrome (header/footer, section menus), skips skip-links and screen-reader text, and stores sections repeated across pages (`shared-sections.json`). Each section gets a semantic **`tone`** (light, muted, dark, accent) and **`space`** (none–xl) resolved from the source CSS, instead of builder classes. It clusters routes by layout (`content-index.json → clusters`).
- **Listings → collections.** Repeated items with collection signals (post or CMS-item markup, dates, pagination, a page-scoped search) become a `listing`, and `build_pages.py` writes a Grav **collection**: real item pages with `date`, `taxonomy`, `image` and `summary`, plus pagination, `/category:x` filters and search through Grav. Ordinary navigation cards stay cards. Details: [references/grav-features.md](references/grav-features.md).
- **`measure_layout.mjs` provides initial layout hints.** It opens each source page and measures every extracted section and layout block:
  - **Sections:** background, spacing (padding or the visible inset), dividers, alignment, and split layouts (heading beside content, with its ratio and rule).
  - **Blocks:** column ratios, cards per row, card style, image shape and filters, full-bleed rows, and inline link lists and tabs (with the active item).
  - **Type:** each heading's size and font.
  - **Chrome:** the header's anatomy (height, full-width bar, nav type, logo, CTA button), its color per page, and form inputs. `build_pages.py` writes these as semantic frontmatter (`tone`, `space`, `divider`, `layout: split`, `ratio`, `per_row`, `card`, `image_ratio`, heading `size`/`font`, `header_variant`). `scaffold_theme.py` turns the site-wide values into tokens (type scale, font roles, header variant colors). Without it the theme falls back to generic layouts, so run it before `build_pages.py`, and rerun both after changing the extraction.
- **Unimplemented controls keep the draft incomplete.** The builder records route, label, action and source path in `unresolved-controls.json`, and exits nonzero unless `--allow-incomplete` was explicitly used for a draft import. Rebuild every required control with real content/data, plugin integration and source-matching styling. The draft flag permits iteration; it never approves removing functionality. Pagination and page-scoped search belong to their collection. Verify them with enough imported records to exercise next/previous, filters and empty states.
- **Gate:** if it warns that composed pages came out as a single section (`content-index.json → quality.monolith_pages`), the splitter missed the page structure. Open one page in `html/`, find the element that wraps each horizontal band, and rerun with `--section-selector` (or `--main-selector`). Never work around it by writing pages as raw HTML. If no selector fixes it, report it as a skill bug with the route.
- `build_pages.py` preserves every URL. It writes exact source `<title>` (`head_title`), descriptions and OG tags, provenance (`source.url`), `sections` for composed pages and a Markdown body for articles.
- **Modular rule:** a composed page with more than three distinct horizontal sections (shared sections count, popups don't) becomes a Grav **modular page**: `modular.md` plus one module per section (`01._hero/hero.md`, `02._<heading>/cards.md`, …), each with its own media and Admin form. Three or fewer stay one page with a larger `sections` frontmatter. Articles and template-mapped pages are never modular. If the user wants a different cut-off, pass `--modular-threshold N` or `--modular off`. Shared sections become non-routable pages under `/shared`, missing parents become non-routable folders, and source redirects go to `system.yaml`. Images used on one page sit beside it; repeated ones go to `user/media/images` (`media://images/…`); PDFs go to `user/media/files`.
- Rerun after improving extraction. Pass `--template-map` to assign cluster ids or route regexes to page types (see phase 12).

**Draft check:** lint clean, `bin/grav clearcache`, every route returns 200, `list_pages` over MCP shows the new tree, page files contain frontmatter + Markdown only, and omissions are visible in the report. These checks establish an import, not visual or functional completion. Content model, frontmatter schema and multilang: [references/content-model.md](references/content-model.md).

### 9. New theme and a finished representative page

```bash
node $S/capture_pages.mjs --migration migration --source https://example.com --tokens-only   # computed styles
python3 $S/scaffold_theme.py migration --grav grav --name acme [--tailwind] [--fonts download|link|skip]
```

Run `capture_pages.mjs --tokens-only` first so the scaffold reads measured tokens. This is a starting shell: its inferred tokens, four tones and spacing steps are lossy. Preserve exact source values and build dedicated layout CSS/Twig where needed, following [references/fidelity.md](references/fidelity.md). Pass `--tailwind` only if the user chose Tailwind in phase 6. This creates a standalone theme with no parent. Shared design is standardized in the theme: tone backgrounds and spacing steps come from the source's most used values (`--tone-*`, `--space-*`), and the source's own rules for the classes pages still use are **ported once, deduplicated, onto `.src-*` hooks** (`css/src/source.css`); per-page generated classes (`wp-container-*`, `w-node-*`) are dropped. It also includes a document shell, a `sections`/`blocks` renderer, header/footer/menus/CTAs/socials from theme config (Admin-editable per language), a language switcher with hreflang, noindex on local/preview hosts, host-gated analytics partials, `/forms` embedding, modals as `<dialog>`, Admin blueprints for `sections` and `form`, `DESIGN.md`, and design tokens from the source. Fonts copied from the source need license confirmation before production: say so. If it reports header CTAs that open a popup (`href="#"`), click each one on the source to see which dialog opens, then set `navigation.<lang>.ctas[].modal` to that `/shared` section name. Theme structure, Tailwind and styling: [references/theme.md](references/theme.md).

Use the [Quark2 conventions reference](references/quark2-conventions.md) when extending the shell, Admin fields or modules. The scaffold adopts deferred asset output and reusable blueprint fields while keeping source styling. Add project CSS in `css/custom.css`; extend Twig blocks with `parent()` when adding assets. `--force` preserves site settings and theme blueprints; `--reset-config --force` explicitly replaces site settings from the audit, and `--force-templates` replaces skeleton files. Check the diff before either replacement flag.

Complete the shared chrome and a difficult representative page with its actual page/module types, named blueprint fields, Markdown, plugins and responsive/state styles. Test an inner-page header variant too. Edit representative fields in Admin/API and inspect the rendered changes. Only then propagate that design family. Keep shared content in data and source-specific layout in theme templates; do not hardcode page copy in Twig.

### 10. Forms

```bash
python3 $S/build_forms.py migration --grav grav --init   # writes migration/forms-plan.json
# put the user's answers from phase 6 into the plan, then:
python3 $S/build_forms.py migration --grav grav
```

Each form becomes `/forms/<name>` (posts to itself, XHR submit, noindex) and is embedded wherever the source showed it. **Check:** submit each form in a real browser (Cap runs a proof-of-work in the browser; curl can't pass it). Confirm the inline success message and the saved record or captured email. See [references/forms.md](references/forms.md).

### 11. Analytics

Put the IDs in `user/config/themes/<theme>.yaml → analytics` (GTM/GA4 are pre-filled, disabled). Paste other vendors' snippets into `head_snippets`/`body_snippets` after the user approves each one. Set `analytics.hosts` to the production hostnames and `enabled: true` only if the user chose to port. **Check:** the local page source contains no tracker requests.

### 12. Finish every design family and prove fidelity

Follow [references/fidelity.md](references/fidelity.md) for the component-plan format, responsive/state coverage, specialized templates and plugin styling.

1. Expand the proven representative layouts using source-specific Twig templates, matching blueprints and rerunnable content transforms. Generic blocks may remain where they express the design accurately. Give new modules/page types named fields instead of forcing every composition through the generic renderer. Build functionality with [Grav core and compatible plugins](references/grav-features.md), overriding plugin templates in the theme to match the source.
2. Pair source and local selectors in a component plan. Measure outer sections and their inner headings, paragraphs, images, controls and repeated items at desktop/tablet/mobile and source breakpoints. Include hover, keyboard focus, selected/open/error states where applicable:

   ```bash
   node $S/compare_components.mjs --plan <plan.json> --source <url> --local <local-url> --out migration/components --tools migration/.tools
   node $S/capture_pages.mjs --migration migration --source <url> --local <local-url> --routes <routes> --metrics
   python3 $S/verify_parity.py migration --local <local-url> --expect-noindex
   ```

3. Fix actual differences in geometry, typography/wrapping, padding/margins/gaps, color/highlights, borders/radii/shadows, image crops and interaction states. Preserve exact source values in reusable theme components; do not round away a visible difference to fit a preset. The screenshot tool's grayscale score is only a triage hint, never a fidelity percentage or acceptance threshold.
4. Check every route for content/order/header-variant drift and every design family with full-color fold/full-page screenshots. Exercise search, filters, sorting, pagination and forms; confirm result contents, empty/error states and URLs. Reconcile every draft omission against a working implementation or an explicit user-approved scope change. No control may simply disappear because extraction failed.
5. Resolve the rendered blueprints and round-trip representative content, media and repeated fields in the running Admin/API. Reorder/hide a module and confirm the parent still works; test translated pages and plugin assets with cold/warm caches. Rerun affected routes after shared CSS changes.

Keep project import transforms rerunnable and record their rebuild order in the user's working-doc store. `build_pages` → project transforms → `build_forms` → clear cache must reproduce the chosen content types and not silently overwrite editorial work.

A passing text verifier or selected component comparison does not establish whole-site completion. Finish visible and functional differences, then present the actual result for user review. Unapproved missing features or visible layout drift remain incomplete work.

### 13. Finish

- Final `verify_parity.py`, YAML lint, `bin/grav clearcache`, Grav log free of errors, an Admin edit round-trip (change a field through MCP/Admin and see it rendered).
- If requested, `git init` in `grav/user` with the `.gitignore` from [references/setup.md](references/setup.md). It excludes accounts, `data/` submissions and API key registry, `env/`, caches and `node_modules`. Commit locally; push only when asked.
- Handoff summary: URLs, where credentials live, the MCP connection, decisions made, parity numbers, known gaps (e.g. items needing a provider, licenses to confirm, intentional deviations).

## Invariants (learned the hard way)

- **Preserve every source URL.** Rename nothing without a redirect. Hosted-builder slugs can be ugly; ask before "cleaning" them and add 301s when you do.
- **Bulk writes go through files, edits through MCP.** The scripts write the page tree directly: fast, deterministic and rerunnable. For later edits use MCP/API sequentially: concurrent creates under the same parent can silently lose sibling pages, and updates need the page's ETag (`If-Match`); on 409, re-read and merge. Clear Grav's cache after direct file or config edits.
- **Never print, log or commit secrets** (API key, admin password, SMTP credentials). SMTP passwords go in env (`GRAV_CONFIG__plugins__email__mailer__smtp__password`), not YAML.
- **Keep preview copies out of search** with `noindex` meta + `X-Robots-Tag` on local/preview hosts (`noindex_hosts`), not `robots.txt Disallow` (crawlers must fetch a page to see noindex).
- **Analytics never fire off production hosts.** Don't send test traffic into the client's analytics.
- **Don't fake integrations.** A form must store or send what it collects, and its success copy must say so. Never post to a guessed third-party endpoint.
- **Admin2/API/MCP are local/authoring tools.** Production should not expose them (see setup.md for a deploy profile).
- **Pages are Markdown + YAML frontmatter, never copied HTML.** Prose goes in the Markdown body; composed pages are `sections` frontmatter or modular pages (one module per horizontal section). An `html` block is a last resort for one widget (a third-party embed); report every one in the handoff.
- **One theme, exact source design.** Reuse tokens for genuinely shared values; preserve distinct colors, exact/asymmetric spacing and responsive states in dedicated component CSS instead of forcing them into presets. Shared design lives in the theme: `tokens.css` (palette, type and measured shared values) → `components.css` → deduplicated `source.css` hooks → `custom.css`. Never ship per-page copies of source stylesheets or a builder's framework CSS wholesale. A theme whose CSS (fonts aside) grows past a few hundred KB has stopped being standardized.
- **Prefer Grav's built-ins** (Form + Cap, Email, page media, `media://`, native multilang, collections, taxonomy) and official GPM plugins over custom code. Read the Grav Learn 2.x page for a feature before building it; 1.7 docs and memory are often out of date.
- Write the why of each choice, including rejected options, where the user keeps project notes (default `migration/notes.md`).
- Theme JS stays dependency-free; don't enable Form options that need jQuery (`keep_alive` loads `form.min.js`).

## References

- [references/setup.md](references/setup.md): install, runtimes (PHP server, Docker, Valet/Herd), API/MCP auth, clients, HTTPS, tunnels, `.gitignore`, production profile, troubleshooting
- [references/content-model.md](references/content-model.md): route→folder rules, frontmatter/`sections` schema, page types, multilang, shared sections, media, redirects, MCP editing
- [references/fidelity.md](references/fidelity.md): source inventory, dedicated native content types, exact responsive/state styling, plugin output, component measurements and completion criteria
- [references/theme.md](references/theme.md): scaffold anatomy, tokens, Tailwind, `.src-*` hooks, interactions, icons, fonts, accessibility
- [references/quark2-conventions.md](references/quark2-conventions.md): official theme patterns, pinned sources, adoption criteria and source-fidelity boundaries
- [references/forms.md](references/forms.md): form decisions, Grav Form YAML, CAPTCHA providers, email/SMTP, testing
- [references/analytics-seo.md](references/analytics-seo.md): tracker porting, consent, SEO parity, sitemap, robots, llms.txt
- [references/platforms.md](references/platforms.md): Webflow, WordPress, Squarespace, Wix, Framer, Shopify, SPAs
- [references/grav-features.md](references/grav-features.md): source features → Grav core or official plugins (collections, pagination, filters, search, feeds, TOC, code, galleries), Grav Learn links, GPM
- [references/verification.md](references/verification.md): acceptance checklist, verifier output, visual review, handoff template
