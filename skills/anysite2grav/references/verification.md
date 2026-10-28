# Verification and handoff

## Acceptance checklist

- [ ] Every source route returns 200 locally; no unexpected extra public routes
- [ ] `verify_parity.py --expect-noindex` passes: exact titles, ≥ 95% source text per page, forms rendered, no assets loading from the old CDN, `lang`/hreflang correct, noindex present, no analytics locally
- [ ] Source redirects replay correctly
- [ ] Side-by-side screenshots reviewed for every layout cluster at 1440px and 390px; differences fixed or recorded in `DESIGN.md`
- [ ] Menus, dropdowns, language switcher, modals and mobile nav work with mouse, keyboard and touch widths
- [ ] Each form submitted in a browser: inline success, record saved or email captured, validation errors shown
- [ ] `php <skill>/scripts/grav_config.php grav lint user` clean; `grav/logs/grav.log` has no new errors
- [ ] Admin: blueprints load for each page type; editing a field and saving round-trips without losing other frontmatter
- [ ] Theme: inherited asset blocks keep head/bottom groups; embedded Form/CAPTCHA assets reach the rendered document with cold and warm caches
- [ ] Rebuild: `scaffold_theme.py --force` retains edited site settings, theme blueprints and `css/custom.css`; replacement flags are used only intentionally
- [ ] New page types import shared page fields; modular collection controls still load; current navigation links expose `aria-current="page"`
- [ ] MCP: `list_pages` shows the tree; an `update_page` (with ETag) appears on the site after cache clear
- [ ] No secrets in `grav/user` git status (`accounts/`, `data/`, `*-private.php`, `env/` ignored)

## Reading `parity-report.md`

| Signal | Usual cause | Fix |
| --- | --- | --- |
| Title mismatch | `head_title` missing or edited | Rebuild pages, or set `head_title` |
| Low text coverage | extractor missed a region (slider, tab panel, custom element), or the theme doesn't render a block type | Check `content/<page>.json` for the missing text. If absent, adjust extraction (`--main-selector`, new block rule). If present, fix the renderer. |
| "source forms … not rendered" | form page missing or the embed name changed | `build_forms.py` again; check `page-map.json → forms` |
| Assets from the old CDN | a reference the importer didn't see (CSS `url()`, inline style, JS-set image) | Import it manually into media and replace the reference |
| Fewer images than source | gallery/slider images in JS, CSS backgrounds | Same as above; add the images to the right block |
| Indexable locally | host missing from `noindex_hosts` | Add it and clear the cache |

Coverage is a floor, not the goal: a page can have all its text and still look wrong. The screenshots decide.

## Visual review

- Compare the fold first (`*-fold.png`), then the full page: section order, spacing rhythm, type scale and weights, colors, image crops, alignment, hover states.
- Check mobile separately. Builders often have distinct mobile layouts (stacked collages, hidden elements, a different hero crop).
- Settle exact numbers with `capture_pages.mjs --metrics` (per-section height, padding, background, heading size/weight/line-height for source vs local), `design-tokens.json`, or devtools.
- Source screenshots force scroll-reveal content visible (builders animate it in on scroll). Compare the final state, then decide whether to port the animation.
- When the user wants improvements beyond 1:1, finish parity first, commit, then iterate on a branch so the faithful baseline stays recoverable.

## Handoff template

```
Site:        http://127.0.0.1:8000  (Admin /admin, API /api/v1)
Login:       <user> — password in <project>/.local/credentials.json
MCP:         <project>/bin/grav-mcp (registered in: Claude Code .mcp.json, Codex …)
Routes:      N source routes → N pages (languages: …); redirects: R
Parity:      N/N pass, avg text coverage X%; screenshots migration/screens/report.html
Forms:       <name> → save|email (captcha: cap) … tested ✓
Analytics:   GTM-… / G-… ported, enabled only on <prod hosts> | disabled pending confirmation
Decisions:   theme <name> (Tailwind yes/no), multilang native|trees, …
Open items:  font license, SMTP provider, items needing a provider, known deviations
```
