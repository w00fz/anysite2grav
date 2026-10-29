# Content model

## Contents
- Route → folder rules
- Frontmatter written by `build_pages.py`
- The `sections` schema
- Single page or modular page
- Promoting a layout cluster to a page type
- Languages
- Shared sections, forms and modals
- Media
- Redirects
- Editing through MCP/API

## Route → folder rules

| Source | Grav |
| --- | --- |
| `/` | `pages/01.home/` (Grav's default `home.alias: /home`) |
| `/about-us` in the main menu | `pages/NN.about-us/`, where `NN` follows the source menu order |
| `/privacy-policy` not in the menu | `pages/privacy-policy/` (no prefix → not in Grav's page menu) |
| `/resources/report-2024` without a `/resources` page | `pages/resources/` gets `default.md` with `routable: false`, so children keep their URLs |
| `/es/about-us` (native multilang) | `pages/NN.about-us/sections.es.md` beside `sections.en.md` |
| `/es/about-us` (trees) | `pages/es/about-us/sections.md` with `language: es` |
| a composed page with 4+ visible sections | `pages/NN.about-us/modular.en.md` plus `01._hero/hero.en.md`, `02._features/cards.en.md`, … |

The folder name (minus prefix) is the slug, so URLs stay identical, ugly builder slugs included. When the user wants cleaner URLs, rename folders and add 301s (`system.yaml → pages.redirects`). Never silently.

The theme renders the header menu from theme config, not from the page tree, because builder menus group flat URLs into dropdowns that don't match the folder hierarchy.

## Frontmatter written by `build_pages.py`

```yaml
title: "About us"                 # source <title> minus " | Brand"; shown in Admin
head_title: "About us"            # exact source <title> (theme prints it verbatim)
menu: "About us"                  # label used in the source menu
metadata:                         # Grav prints these as <meta>; og:* become property=
  description: "…"
  og:title: "…"
  og:image: "media://images/cover.jpg"
source:                           # provenance; keep for audits and reruns
  url: "https://example.com/about-us"
  crawled_at: "2026-10-27T22:45:30+00:00"
  layout: "layout-04"             # cluster id from content-index.json
forms: ["newsletter-form"]
sections: [ … ]                   # composed pages; articles use the Markdown body instead
```

The template comes from the file name (`sections.md`, `modular.md`, `default.md`, `<type>.md`); Admin blueprints resolve by the same name.

## The `sections` schema

```yaml
sections:
  - type: shared                  # render /shared/<name> here
    shared: newsletter
  - type: section
    id: pricing                   # optional anchor
    tone: dark                    # light | muted | dark | accent → theme --tone-* colors
    space: l                      # none | s | m | l | xl → theme --space-* padding
    role: subnav                  # optional: a section menu bar under the header
    divider: bottom               # top | bottom | both: a rule like the source's
    align: center
    layout: split                 # heading beside the content…
    ratio: [1, 2.75]              # …at the source's measured column widths
    split_divider: true           # …with a vertical rule between them
    classes: [section, black]     # source classes → .src-section .src-black hooks
    background: hero.jpg          # page file, media://, theme:// or URL
    background_video: {sources: [hero.mp4], poster: hero.jpg}
    modal: true                   # render as <dialog id="modal-<id>"> instead of inline
    blocks:
      - {type: heading, level: 1, text: "Markdown **inline**", classes: [has-xl-font-size]}
      - {type: text, text: "Paragraph markdown with [links](/x)"}
      - {type: list, ordered: false, items: ["one", "two"]}
      - {type: list, title: "The details", items: ["[License](/license)"]}  # a menu group
      - {type: list, style: tabs, active: 0, size: small, items: ["[Popular](/themes)", "[Latest](/themes/latest)"]}
      - {type: columns, columns: [{blocks: [ … ]}, {blocks: [ … ]}], ratio: [1, 2], divider: true, valign: top}
      - {type: collection, from: /news/latest-posts, style: list, limit: 5, pagination: true,
         taxonomy: category, url_taxonomy_filters: true, search: true, per_row: 3, card: plain,
         image_ratio: 4/3, title_size: l, title_font: alt}            # Grav page collection
      - {type: code, code: "<?php echo 1;", language: php}
      - {type: quote, text: "…"}
      - {type: image, src: photo.jpg, alt: "…", href: /optional-link}
      - {type: video, sources: [clip.mp4], poster: still.jpg, autoplay: false}
      - {type: embed, src: "https://www.youtube.com/embed/…", title: "…"}
      - {type: button, label: "Book a demo", href: /demo}        # or modal: demo-request
      - {type: gallery, style: logos, images: [{src: a.svg, alt: A}]}
      - {type: cards, cards: [{href: /x, blocks: [ …same block types… ]}]}
      - {type: table, rows: [["h1","h2"],["a","b"]]}
      - {type: form, form: newsletter-form}
      - {type: html, html: "<div>…</div>"}                       # last resort
```

Articles (pages with one dominant rich-text region) keep their surrounding sections (hero, related cards, CTAs, modals). Only the rich-text element is replaced, by a `{type: body}` block (`body_slot: true` in the header), and the Markdown body renders in that slot; editors edit the article as normal page content.

Headings carry `size` (a step of the site's type scale: display, xl, l, m, s, xs) and `font` (heading, body, alt) when the source differs from the default, and paragraphs can be `size: lead`. Cards and collections carry `per_row`, `card` (plain, bordered, filled, shadow, divided), `image_ratio`, `image_filter`, `bleed` and `gap`. Pages whose source header uses other colors get `header_variant: alt`. All of these come from `measure_layout.mjs` (`migration/layout.json`). These are lossy draft options, not the final design contract. Preserve additional source values and responsive/state behavior through purpose-built theme components; see [fidelity.md](fidelity.md).

`tone` and `space` are the standardized style: the extractor resolves them from the source's computed background and inline padding, the theme defines each step once, and editors pick from a short list in Admin. `classes` stay as `.src-*` hooks for what tokens can't express. Block `classes` are kept only when the source CSS styles them (typography presets, for example).

Pages never carry the source's HTML. If extraction can't express a layout, improve the extractor or the theme; don't paste markup.

`templates/partials/blocks.html.twig` renders each type; `blueprints/pages/sections.yaml` edits them in Admin. When you add a block type, update the extractor (if it can emit it), the renderer and the blueprint together.

## Single page or modular page

Rule of thumb: **a page with more than three distinct horizontal sections is a modular page; three or fewer stay one page** with a bigger chunk of frontmatter. `build_pages.py` applies it to every composed page (`--modular auto`, the default):

- It counts the sections a visitor scrolls through: inline sections and shared sections. Popups don't count; they stay in the parent's `sections` and render as dialogs.
- Articles (a Markdown body), pages with a `{type: body}` slot, and pages you mapped to a page type with `--template-map` are never made modular.
- The decision is made on the default-language page, so every translation shares one module tree (`hero.en.md`, `hero.es.md` in the same module folder).
- Change the cut-off with `--modular-threshold N` (pages with more than N sections become modular) or turn it off with `--modular off`. Reruns convert pages both ways and delete stale module files.

A modular page is a parent plus one child module per section, in source order:

```
pages/01.home/
  modular.en.md                  # title, head_title, metadata, source, forms, popups in `sections`,
                                 # content: {items: '@self.modular', order: {by: default, dir: asc}}
  01._hero/hero.en.md            # first section with an H1 or a background image/video
  02._why-teams-switch/cards.en.md
  03._partners/gallery.en.md     # logo strip or photo gallery, with its page media beside it
  04._newsletter/shared.en.md    # {shared: newsletter}: renders /shared/newsletter in place
  05._contact/form.en.md
```

- Folder names are `NN._<name>`. The `NN.` prefix keeps source order; the slug starting with `_` makes it a module, which is never routable. Names come from the section's first heading, so editors recognize them in Admin.
- The module file name is its **kind**: `hero`, `cards`, `gallery`, `form`, `shared`, or `section` for anything else. Each kind has `templates/modular/<kind>.html.twig` and `blueprints/pages/modular/<kind>.yaml`.
- A module's frontmatter holds one section, flattened: `anchor` (the id), `tone`, `space`, `role`, `classes`, `background`, `background_video`, `blocks`. The block schema is the same as in `sections`, and so is the Admin editor: both blueprints import `blueprints/pages/partials/block-fields.yaml`.
- Media used only by one module lives in that module's folder; shared and repeated media still go to `user/media/images`.

Why modules instead of a long `sections` list: each section gets its own Admin page, media folder and ETag, so editors and agents can reorder, add, hide (`published: false`) or edit one section without rewriting the rest of the page. A short page is easier to edit as a single page, which is why the threshold exists.

**Specializing a module kind.** When editors need named fields for a kind (a hero with `heading`, `subheading`, `image`, `cta`), give that kind its own markup in `templates/modular/<kind>.html.twig` and its own fields in `blueprints/pages/modular/<kind>.yaml`. Then convert existing modules of that kind with a rerunnable script in `migration/fixups/`. This is the module version of promoting a page type, below; prefer it when the same section design recurs across many different pages.

## Promoting a layout cluster to a page type

The generic `sections` page is an initial content import; it does not establish faithful layout or useful editing fields. Plan the final page/module types from the rendered source before expanding them across routes ([fidelity.md](fidelity.md)). When several routes share a layout (a cluster in `content-index.json`), or one key page (home) has a distinctive composition, give it a page type:

1. Pick names from the source's own vocabulary (`product`, `case-study`, `solution`). Read the source HTML of a few routes in the cluster to design the fields; it's cleaner than the flattened blocks.
2. Write `templates/<type>.html.twig` that renders named fields (e.g. `page.header.hero.heading`, `page.header.features`) and falls back to `partials/sections.html.twig` for anything else.
3. Write `blueprints/pages/<type>.yaml` with `extends@: {type: default, context: blueprints://pages}` and the same named fields: `media` fields with `sources: [page, site, url]` for images, `list` for repeatables, `array` with `value_only: true` for string lists.
4. Map the content into those fields. Either transform `sections` in a small project script (keep it rerunnable) or let `build_pages.py --template-map map.json` assign the template, then restructure.
5. Rerun order matters: `build_pages.py` rewrites page files (and deletes stale `*.<lang>.md` of the same template), so run page-type transforms as scripts afterwards (`migration/fixups/`), never as one-off manual edits.
6. Verify: blueprint fields resolve in Admin (`get_blueprint` over MCP), every route in the cluster renders, and the parity verifier still passes.

Introduce a type only when its fields differ in practice. Copies of the same layout belong to the same type.

## Languages

`build_pages.py --languages auto` chooses **native** when ≥ 80% of localized pages map to a default-language page (via `hreflang`, then by stripping the `/xx` prefix), otherwise **trees**.

- Native: `system.yaml → languages.supported`, `include_default_lang: false` (default language without prefix, as on most sites), `include_default_lang_file_extension: true` (`page.en.md`). URLs stay `/es/...`. The theme's switcher and hreflang use `page.translatedLanguages`. Untranslated localized pages get their own folder with only that language file.
- Trees: each language prefix is an ordinary subtree; language-specific chrome comes from `navigation.<lang>` in theme config. Simpler, but no translation linking in Admin.
- Every UI string the theme adds needs every language. When the source left a localized page in English, keep it and point its canonical at the original if the user wants SEO consolidation.

## Shared sections, forms and modals

- Sections repeated across ≥ 50% of a language's pages (newsletter bands, CTA strips, popups) are stored once in `/shared/<name>` (non-routable) and referenced with `type: shared`. Edit once, change everywhere.
- Forms live in `/forms/<name>`; pages reference them with a `form` block (see forms.md).
- Modal sections render as `<dialog>` at the end of the page. Buttons open them with `modal: <name>`; links to `#modal-<name>` work too. Builders often trigger popups with `href="#"` plus custom JS. The extractor records these as CTAs with `action: "#"`, so wire them to the right modal (`modal:` on the CTA in theme config or on the button block).

## Media

`import_media.py` downloads each URL once and dedupes by SHA-256. `build_pages.py` then places files:

| Scope | Location | Reference |
| --- | --- | --- |
| used by one page | beside the page `.md` | `photo.jpg` |
| repeated / shared sections | `user/media/images/` | `media://images/photo.jpg` (works in frontmatter and Markdown, image actions included) |
| documents (PDF, DOCX…) | `user/media/files/` | `/user/media/files/report.pdf` |
| logo, menu icons | `user/themes/<theme>/images/` | `theme://images/logo.svg` |

Keep originals; serve sized derivatives (`derivatives()`, `cropResize`, `quality`) from Twig instead of shrinking originals. `grav/images/` is a disposable derivative cache: never reference or commit it.

## Redirects

Source redirects found while crawling go to `system.yaml → pages.redirects` (`'/old': '/new[301]'`). Add one for every URL you rename later. `verify_parity.py` replays them.

## Editing through MCP/API

- Read before write: `get_page` returns the ETag; `update_page` sends it (`If-Match`). On `409 Conflict`, re-read, merge and retry once.
- Create pages one at a time under a given parent. Parallel creates of sibling folders have dropped pages while still reporting success; verify with `list_pages` afterwards.
- The API needs `api.pages.write` for content and `api.config.*` for config. If a config write is refused, edit `user/config/*.yaml` directly with `grav_config.php … merge` and clear the cache.
- Some root/home routes can behave differently in the pages endpoint (e.g. a collection on read, 405 on update). Fall back to a direct file edit for those and note it.
- Modules are pages too: `get_page`/`update_page` on `/<parent-route>/_<name>` (e.g. `/home/_hero`) edits one section; the module keeps its other frontmatter. Create a new module as a child of the parent with a folder starting with `_` and a kind template (`modular/cards`).
- After direct file edits: `php bin/grav clearcache` (or MCP `clear_cache`).
