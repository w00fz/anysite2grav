# Theme

## Contents
- Anatomy of the scaffolded theme
- Why standalone (no parent theme)
- Configuration, extension blocks and rebuilds
- Tokens and Tailwind
- Styling source variants
- Interactions and animation
- Icons, logos, fonts
- Accessibility and performance floor

## Anatomy of the scaffolded theme

```
user/themes/<name>/
  <name>.php                 theme class: noindex hosts, analytics gate, form registration, Twig helpers
  <name>.yaml                defaults; site values live in user/config/themes/<name>.yaml
  blueprints.yaml            Admin → Themes: logo, analytics, noindex hosts, navigation per language
  blueprints/pages/          sections.yaml, modular.yaml, form.yaml (+ your page types)
  blueprints/pages/modular/  section, hero, cards, gallery, form, shared module blueprints
  blueprints/pages/partials/ block-fields.yaml, page-fields.yaml (shared editors)
  templates/
    partials/base.html.twig  document shell (head, header, main, footer, modals, assets)
    partials/seo.html.twig   title, meta, robots, canonical, hreflang
    partials/header|footer|language-switcher|social-icon.html.twig
    partials/sections.html.twig, blocks.html.twig, modals.html.twig, form-embed.html.twig
    partials/analytics-head|analytics-body.html.twig
    sections.html.twig, modular.html.twig, default.html.twig, form.html.twig, error.html.twig
    modular/section|hero|cards|gallery|form|shared.html.twig   one template per module kind
  css/src/                   fonts.css, tokens.css, components.css, source.css (+ site.css entry for Tailwind)
  css/site.css               the built stylesheet the shell loads
  css/custom.css             project overrides, loaded last and kept on ordinary reruns
  js/site.js                 dropdowns, mobile nav, dialogs (vanilla, no dependencies)
  DESIGN.md                  design rules agents read before styling
  design-tokens.json         tokens used for this build
```

Twig helpers from the theme class: `theme_media(value, page)` resolves page files, `media://`, `theme://` and URLs to `{url, medium}`; `shared_section_page(name)`; `theme_noindex()`; `theme_analytics_allowed()`. Theme settings are `config.theme.*` in Twig (there is no `theme_config` global in Grav 2).

**Do not use Twig's `only` on includes that may render forms.** Grav passes `assets` as a context variable, so `only` silently drops plugin JS (Form XHR, CAPTCHA) and forms fall back to full-page posts.

## Why standalone (no parent theme)

Inheriting Quark/Quark2 seems cheaper, but its resets, font stack and header/dropdown CSS fight the source look, and overriding them costs more than owning a small shell. The scaffold keeps the document shell, CSS and JS in the theme. Re-add a parent only if the user explicitly wants one.

The [Quark2 conventions reference](quark2-conventions.md) records the official theme revision reviewed, source links, patterns worth adopting and features that stay conditional. Use its structure as a reference when extending a layout; preserve the migrated site's appearance and behavior.

## Configuration, extension blocks and rebuilds

Keep shipped defaults in `<name>.yaml`; keep the site's editable values in `user/config/themes/<name>.yaml`. The scaffold seeds missing keys on `--force` and preserves existing values, including empty lists, false toggles, navigation, preview hosts and analytics choices. Theme defaults and `blueprints.yaml` are also kept. `--force-templates` replaces skeleton files, defaults and the theme blueprint; `--reset-config --force` replaces site values from the audit. Inspect changes and clear the cache after either operation.

When adding a language or a new setting to an existing project, update its preserved blueprint deliberately so the new field is editable. Use `theme_var()` only for visual options intended to inherit from page headers and ancestors; keep preview-host indexing and analytics policy in site theme configuration.

The base template exposes `head`, `stylesheets`, `javascripts`, `assets`, `body_classes`, `header`, `body`/`content`, `footer`, `modals` and `bottom`. Extend a small block rather than copying the whole shell. Call `parent()` when adding styles, scripts or bottom markup:

```twig
{% extends 'partials/base.html.twig' %}
{% block javascripts %}
  {{ parent() }}
  {% do assets.addJs('theme://js/product.js', {group: 'bottom', loading: 'defer'}) %}
{% endblock %}
```

`head` and `assets` are deferred, so metadata and plugin assets registered while rendering page/module/form content are available before the head is emitted. The asset block emits default `head` group through `assets.all()`; `bottom` emits its own group. Keep both when customizing the shell. Test an embedded Form/CAPTCHA after changes, with a warm page cache as well as a cold one.

`partials/page-fields.yaml` shares browser title, body classes and per-page noindex fields across sections, modular and form pages. Import it into new page types with `context: blueprints://pages`, then add only the fields the layout needs. Continue extending Grav's modular blueprint so collection order and module selection remain editable. Confirm these imports in Admin, not just with a YAML parser.

## Tokens and Tailwind

Tokens come from two places, merged in this order:

1. `audit_site.py` CSS digest: most frequent colors, font families, container widths.
2. `capture_pages.mjs --tokens-only`: computed styles of visible body/h1/h2/h3/p/button/header/footer on the source. These are more accurate; run it before scaffolding.

`--tailwind` writes `css/src/site.css`:

```css
@import "tailwindcss";
@import "./fonts.css";
@import "./tokens.css";      /* @theme static { --color-*, --font-*, --text-*, --radius-* } + :root { layout vars } */
@import "./components.css";  /* plain CSS using the tokens */
@source "../../templates";
```

Build with `npm run build` (or `npm run watch` while iterating) in the theme folder. The output `css/site.css` is committed, so production needs no Node. Tailwind's theme variables are real CSS variables, so components and utilities share one palette. Without Tailwind, the scaffold concatenates fonts, tokens, components and source rules into `css/site.css`. To switch later, rerun `scaffold_theme.py --force --tailwind`. `css/custom.css` loads after the build in either mode and needs no Node build.

Bump a version query or use Grav's asset pipeline when CSS changes but browsers keep a cached copy.

## Styling source variants

`css/src/source.css` is generated: every source rule whose selector is built only from section/card classes (e.g. `.section.dark`, `.hero-banner`, `.feature-card:hover`), including those inside `@media`, rewritten to `.src-*` and with `url()` assets downloaded to `images/source/`. It loads after `components.css`, so the source wins. It's regenerated by `scaffold_theme.py --force`; put project overrides in `css/custom.css` so they load after source rules and survive ordinary rebuilds. Inner elements don't keep source classes, so rules like `.hero-banner .heading` aren't ported: restyle those with the hooks below.

Every section carries its source classes as `.src-<class>` (e.g. `.src-dark`, `.src-hero-banner`, `.src-logo-strip`). Style variants there rather than in templates:

```css
.src-dark { background: var(--color-text); color: var(--color-background); }
.src-hero-banner .block-heading { font-size: clamp(2.5rem, 5vw, 4.5rem); max-width: 14ch; }
.src-logo-strip .gallery--logos img { filter: grayscale(1) brightness(3); }
```

Modules of modular pages also carry `.module--<kind>` (`.module--hero`, `.module--cards`, …), which styles every section of one kind at once.

Work section by section against the source screenshot at 1440px and 390px. Measure with the browser instead of guessing: compare computed font sizes, line heights, paddings and container widths in source vs local. Note any intentional deviation in `DESIGN.md`.

## Interactions and animation

Builders ship interactions through their runtime (Webflow IX2 `data-w-id`, Framer motion), so the crawl only captures the end state. For each interaction the user cares about (tabs, sliders, accordions, marquee logos, counters, sticky/transparent header, hover lifts):

- Reimplement it in `js/site.js` or a small per-feature script with no framework (no jQuery: Grav plugins that need it will break). `site.js` uses explicit semicolons and a leading `;` so appended code can't merge into its IIFE. Keep that when extending it. Use semantic markup (`<details>` for accordions, `role="tablist"` + arrow keys for tabs, `<dialog>` for modals).
- Pause offscreen (IntersectionObserver), respect `prefers-reduced-motion`, keep a readable no-JS state.
- Ask before adding effects the source doesn't have.

## Icons, logos, fonts

- Logos, partner marks and product lockups are identity assets: keep the source files (prefer SVG; look for higher-resolution originals if the source serves blurry rasters).
- Generic UI icons (chevrons, arrows, checkmarks) can stay as source SVGs or be swapped for one consistent set, e.g. Lucide rendered server-side from `lucide-static` at build time (no runtime icon JS). Ask first; it changes the look.
- Fonts: `--fonts download` self-hosts the files referenced by the source `@font-face`; `link` keeps the source URLs (they break when the old site goes away); `skip` uses fallbacks. Commercial fonts (Gotham, Proxima, etc.) need a license that allows self-hosting. Tell the user. Check for inflated glyph metrics and missing weights after switching.
- Favicons: export SVG + PNG + ICO + Apple touch from the source mark, check each renders (converters drop SVG clip paths), and give the browser-chrome icon enough contrast on light and dark tabs.

## Accessibility and performance floor

- Visible focus, skip link, semantic heading order (one H1), alt text on informative images, labels on every form field, keyboard-operable menus/dialogs, no text under 13px, no horizontal overflow at 320px.
- Lazy-load below-the-fold media, serve sized derivatives, preload the hero image or video poster, keep JS small. Lighthouse should not regress from the source. Don't chase 100 by removing intentional `noindex` on preview hosts.
