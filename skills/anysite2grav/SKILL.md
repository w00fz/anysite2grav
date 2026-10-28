---
name: anysite2grav
description: Converts a live website (Webflow, WordPress, Squarespace, Wix, Framer or hand-built) into a local Grav 2 site with Admin2, the REST API and an MCP server wired for agents. It recreates every route as Grav pages with frontmatter and blueprints (modular pages for long composed pages), imports media, converts forms, ports analytics and builds a theme that mimics the source as closely as possible. Use when asked to migrate, clone, rebuild or port an existing site to Grav, or to scaffold a Grav copy of a URL.
---

# anysite2grav

Turn a live site into a local, editable Grav 2 copy that is as close to 1:1 as possible: same URLs and sitemap, same content and media, equivalent forms and analytics, a theme that looks the same, and an Admin + API + MCP setup so the user's agent can keep editing.

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
- [ ] 6. Decisions asked: theme name, Tailwind, language mode, forms, analytics
- [ ] 7. Content extracted + media imported (extract_content.py, import_media.py)
- [ ] 8. Pages built (build_pages.py), YAML lint clean, every route 200
- [ ] 9. Theme scaffolded with source tokens (capture_pages.mjs, scaffold_theme.py)
- [ ] 10. Forms converted and test-submitted (build_forms.py)
- [ ] 11. Analytics ported per the user's choice
- [ ] 12. Fidelity loop per layout cluster until parity + visual sign-off
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

It seeds from `robots.txt` and sitemaps, then crawls same-site links: hosted builders often publish no sitemap or an incomplete one. A random-path probe detects soft-404 pages that answer 200. Report the route count, how many came only from crawling, languages, redirects, broken links and PDFs. If the output says TRUNCATED, raise `--max-pages`. If pages render client-side (empty HTML), see [references/platforms.md](references/platforms.md).

### 5. Audit

```bash
python3 $S/audit_site.py migration      # → migration/audit.md
```

Show the user `audit.md`: third-party tags with IDs (GTM, GA4, Meta, HubSpot, Hotjar, Heap…), every distinct form with its fields and where it appears (including modals), embeds (Calendly, YouTube, Typeform), inline custom code, fonts and palette.

### 6. Decisions to ask (after the audit, before building)

Ask together, with a recommended default for each:

1. **Theme name** (slug) and **Tailwind?** Tailwind 4 CLI build (recommended when the user will keep iterating on design), or plain CSS with tokens. Decide before styling starts.
2. **Languages** (only if more than one): native Grav multilang (`page.<lang>.md`, one tree; recommended when hreflang maps the pages) or separate trees per language prefix (`--languages trees`).
3. **Forms**: per form or as a default: delivery (save to `user/data`, email via SMTP, webhook, or keep a third-party embed), CAPTCHA (Grav's built-in **Cap**: invisible, self-hosted, no keys; Turnstile; reCAPTCHA; basic; none), success behavior (inline message, redirect, thank-you page). Options and trade-offs: [references/forms.md](references/forms.md).
4. **Analytics**: port as-is but load **only on the production hostname** (recommended), add consent gating, keep only some tags, or drop them. Details: [references/analytics-seo.md](references/analytics-seo.md).

Record the answers (and the rejected options) in the project notes; later phases depend on them.

### 7–8. Content, media, pages

```bash
python3 $S/extract_content.py migration          # sections → blocks, chrome, clusters
python3 $S/import_media.py migration             # download once, dedupe by hash
python3 $S/build_pages.py migration --grav grav [--languages native|trees] [--template-map map.json] [--modular-threshold 3]
php $S/grav_config.php grav lint user            # every frontmatter + YAML parses
```

- `extract_content.py` keeps **every text block**, including the leaf `<div>`/`<span>` text that builders use instead of `<p>`, and repeated card grids, galleries, background videos and modals. It splits site chrome (header/footer) and sections repeated across pages (`shared-sections.json`). It clusters routes by layout (`content-index.json → clusters`).
- `build_pages.py` preserves every URL. It writes exact source `<title>` (`head_title`), descriptions and OG tags, provenance (`source.url`), `sections` for composed pages and a Markdown body for articles.
- **Modular rule:** a composed page with more than three distinct horizontal sections (shared sections count, popups don't) becomes a Grav **modular page**: `modular.md` plus one module per section (`01._hero/hero.md`, `02._<heading>/cards.md`, …), each with its own media and Admin form. Three or fewer stay one page with a larger `sections` frontmatter. Articles and template-mapped pages are never modular. If the user wants a different cut-off, pass `--modular-threshold N` or `--modular off`. Shared sections become non-routable pages under `/shared`, missing parents become non-routable folders, and source redirects go to `system.yaml`. Images used on one page sit beside it; repeated ones go to `user/media/images` (`media://images/…`); PDFs go to `user/media/files`.
- Rerun after improving extraction. Pass `--template-map` to assign cluster ids or route regexes to page types (see phase 12).

**Check:** lint clean, `bin/grav clearcache`, every route returns 200, and `list_pages` over MCP shows the new tree. Content model, frontmatter schema and multilang: [references/content-model.md](references/content-model.md).

### 9. Theme

```bash
node $S/capture_pages.mjs --migration migration --source https://example.com --tokens-only   # computed styles
python3 $S/scaffold_theme.py migration --grav grav --name acme [--tailwind] [--fonts download|link|skip]
```

This creates a standalone theme with no parent. It **ports the source's own CSS rules for section/card classes onto `.src-*` hooks** (`css/src/source.css`), which carries most backgrounds, spacing and colors that builders keep in CSS rather than markup. It also includes a document shell, a `sections`/`blocks` renderer, header/footer/menus/CTAs/socials from theme config (Admin-editable per language), a language switcher with hreflang, noindex on local/preview hosts, host-gated analytics partials, `/forms` embedding, modals as `<dialog>`, Admin blueprints for `sections` and `form`, `DESIGN.md`, and design tokens from the source. Fonts copied from the source need license confirmation before production: say so. If it reports header CTAs that open a popup (`href="#"`), click each one on the source to see which dialog opens, then set `navigation.<lang>.ctas[].modal` to that `/shared` section name. Theme structure, Tailwind and styling: [references/theme.md](references/theme.md).

Use the [Quark2 conventions reference](references/quark2-conventions.md) when extending the shell, Admin fields or modules. The scaffold adopts deferred asset output and reusable blueprint fields while keeping source styling. Add project CSS in `css/custom.css`; extend Twig blocks with `parent()` when adding assets. `--force` preserves site settings and theme blueprints; `--reset-config --force` explicitly replaces site settings from the audit, and `--force-templates` replaces skeleton files. Check the diff before either replacement flag.

### 10. Forms

```bash
python3 $S/build_forms.py migration --grav grav --init   # writes migration/forms-plan.json
# put the user's answers from phase 6 into the plan, then:
python3 $S/build_forms.py migration --grav grav
```

Each form becomes `/forms/<name>` (posts to itself, XHR submit, noindex) and is embedded wherever the source showed it. **Check:** submit each form in a real browser (Cap runs a proof-of-work in the browser; curl can't pass it). Confirm the inline success message and the saved record or captured email. See [references/forms.md](references/forms.md).

### 11. Analytics

Put the IDs in `user/config/themes/<theme>.yaml → analytics` (GTM/GA4 are pre-filled, disabled). Paste other vendors' snippets into `head_snippets`/`body_snippets` after the user approves each one. Set `analytics.hosts` to the production hostnames and `enabled: true` only if the user chose to port. **Check:** the local page source contains no tracker requests.

### 12. Fidelity loop (the part that makes it 1:1)

Work cluster by cluster, largest first (`content-index.json → clusters`):

1. `node $S/capture_pages.mjs --migration migration --source <url> --local <local-url> --routes <example routes> --metrics` and open `migration/screens/report.html` (or view the `-fold.png` images) at 1440px and 390px. While iterating, add `--only local` to reuse the source shots. `--metrics` lists each section's height, padding, background and heading size/weight/line-height for source and local side by side: fix measured differences rather than eyeballing.
2. Fix the biggest visual gap first. Style source variants through the `.src-<class>` hooks, adjust tokens, and add interactions the source has (tabs, carousels, accordions, sticky header, hover states), keeping them accessible and reduced-motion aware.
3. When a section design recurs across pages (every hero, every feature grid), **specialize its module kind**: named fields in `templates/modular/<kind>.html.twig` + `blueprints/pages/modular/<kind>.yaml`, filled by a fixup script. When a whole cluster of pages needs named fields, **promote it to a page type**: `templates/<type>.html.twig` + `blueprints/pages/<type>.yaml` with real fields. Derive the fields by reading the source HTML of two or three routes in the cluster (cleaner than the flattened blocks). Fill them with a rerunnable project script that runs **after** `build_pages.py`. Keep blueprint and template in step.
   Keep every project-specific fix (page-type transforms, modal wiring, extra imports) as a rerunnable script in `migration/fixups/`, and list the rebuild order (`build_pages` → fixups → `build_forms` → clear cache) in `migration/notes.md`, so reruns of the generic scripts never lose hand work.
4. `python3 $S/verify_parity.py migration --local <local-url> --expect-noindex` until every route passes.

Iterate until the screenshots match and the verifier is green. Then show the user the side-by-side report and ask for sign-off. Visual review guidance: [references/verification.md](references/verification.md).

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
- **Prefer Grav's built-ins** (Form + Cap, Email, page media, `media://`, native multilang) over custom code.
- Write the why of each choice, including rejected options, where the user keeps project notes (default `migration/notes.md`).
- Theme JS stays dependency-free; don't enable Form options that need jQuery (`keep_alive` loads `form.min.js`).

## References

- [references/setup.md](references/setup.md): install, runtimes (PHP server, Docker, Valet/Herd), API/MCP auth, clients, HTTPS, tunnels, `.gitignore`, production profile, troubleshooting
- [references/content-model.md](references/content-model.md): route→folder rules, frontmatter/`sections` schema, page types, multilang, shared sections, media, redirects, MCP editing
- [references/theme.md](references/theme.md): theme anatomy, tokens, Tailwind, `.src-*` hooks, interactions, icons, fonts, accessibility
- [references/quark2-conventions.md](references/quark2-conventions.md): official theme patterns, pinned sources, adoption criteria and source-fidelity boundaries
- [references/forms.md](references/forms.md): form decisions, Grav Form YAML, CAPTCHA providers, email/SMTP, testing
- [references/analytics-seo.md](references/analytics-seo.md): tracker porting, consent, SEO parity, sitemap, robots, llms.txt
- [references/platforms.md](references/platforms.md): Webflow, WordPress, Squarespace, Wix, Framer, Shopify, SPAs
- [references/verification.md](references/verification.md): acceptance checklist, verifier output, visual review, handoff template
