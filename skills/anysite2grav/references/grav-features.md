# Grav features for source functionality

Before writing custom code for something the source site does, check whether Grav or an official plugin (getgrav / Trilby Media, installed with GPM) already does it. A site built on Grav's own features stays maintainable, and editors find them in Admin.

## Contents
- Where to look
- Feature map
- Installing and checking plugins
- Listings: collections, pagination, filters, search
- When nothing fits

## Where to look

- **Grav Learn (2.x):** https://learn.getgrav.org/2. Start with:
  - collections: `/2/content/collections`
  - taxonomy: `/2/content/taxonomy`
  - modular pages: `/2/content/modular`
  - blueprints and fields: `/2/forms/blueprints`, `/2/forms/blueprints/fields-available`
  - Twig: `/2/themes/twig-primer`, `/2/themes/twig-tags-filters-functions`
  - Flex Objects: `/2/advanced/flex`
  - plugins: `/2/plugins`

  Fetch the page you need instead of relying on memory: Grav 2 changed details since 1.7, and 1.7 docs (`/17/`) still rank in search.
- **Plugin index:** `bin/gpm index` (or `bin/gpm info <slug>`) inside the Grav root lists every plugin with the Grav versions it supports. Use only plugins that list `2.0`.
- **A plugin's README** (`user/plugins/<slug>/README.md` after install) for its config keys, Twig variables and templates to override.

## Feature map

| Source feature | Grav way | Plugin (slug) |
| --- | --- | --- |
| Blog, news, post list, "latest posts" | Collection of child pages, ordered by `date` | core |
| Pagination (`/page/2/`, "Load more") | `pagination: true` on the collection → `/route/page:2` | `pagination` |
| Category / tag filters, tag clouds | `taxonomy:` on items, URL filters `/route/category:x`, term lists | core + `taxonomylist` |
| Archive by month | Date-based archive lists | `archives` |
| Site search (header search box) | `/search` results page | `simplesearch`; `tntsearch` for instant, indexed search |
| Search inside one directory (plugins, themes, showcase) | Collection block with `search: true` (filters by `?q=`), or a scoped `tntsearch` | core / `tntsearch` |
| RSS / Atom / JSON feed | Feed of a collection | `feed` |
| Related posts | Related pages by taxonomy | `relatedpages` |
| Breadcrumbs | Trail from the page tree | `breadcrumbs` |
| On-page table of contents, heading anchors | TOC from headings | `page-toc`, `anchors` |
| Code samples with highlighting | Fenced code blocks (`code` block) | `highlight` or `prism-highlight` |
| Image lightbox, galleries | Page media + lightbox | `lightbox-gallery` or `featherlight` |
| YouTube / Vimeo embeds | `embed` block, or the plugin's markdown syntax | `youtube` |
| Image captions | Captions from title/alt | `image-captions` |
| Notices / callouts | Markdown alerts | `markdown-notices`, `github-markdown-alerts` |
| Reading time | Twig variable | `readingtime` |
| Language switcher | Theme switcher (scaffolded), or the plugin | `langswitcher` |
| XML sitemap | `/sitemap.xml` | `sitemap` |
| External links open in a new tab | Markdown post-processing | `external_links` |
| Forms, newsletter sign-up, contact | Grav Form + Email (+ Cap) | `form`, `email`, `email-*` providers |
| Comments | Comments | `comments` (`comments-pro` is premium) |
| Directories of structured records (products, people, locations) beyond pages | Flex Objects directory with its own blueprint | `flex-objects` |
| Members area, gated pages | Login and access rules | `login`, `login-oauth2` |

Premium plugins (YetiSearch Pro, Comments Pro, SEO Magic, Editor Pro) need a license: ask before using one, and offer the free option.

## Installing and checking plugins

```bash
cd <project>/grav
bin/gpm install pagination simplesearch -y     # only after the user agreed in phase 6
bin/gpm info tntsearch                          # versions, author, dependencies
bin/grav clearcache
```

- Plugin settings go in `user/config/plugins/<slug>.yaml`. Copy the keys you change from the plugin's own `<slug>.yaml`; don't edit files under `user/plugins/`.
- Style plugin output from the theme: override its current templates in `user/themes/<theme>/templates/` (for example `partials/pagination.html.twig` or `simplesearch_results.html.twig`), preserving fields, actions, hidden inputs and required assets. Match source geometry, type, colors, icons, borders and hover/focus/selected/error states. Verify results and empty states with real data; installing a plugin is not feature parity. See [fidelity.md](fidelity.md).
- Record each plugin and why in the project notes, and list them in the handoff.

## Listings: collections, pagination, filters, search

`extract_content.py` marks repeated items with collection signals (post or CMS-item markup, dates, pagination, a page-scoped search form) as a `listing`. `build_pages.py` turns each one into a `collection` block (see content-model.md):

- **Items imported as pages** (a full blog migration): the collection lists them where they live (`descendants: true`, ordered by date). Each item page gets `date`, `taxonomy.category`, `image` and `summary` from the listing.
- **Items not imported** (a scoped copy, or a feed of external records): each item becomes a non-routable record under the page (`<page>/<collection>/NN.<slug>/item.md`). Its `link` keeps the original URL, so pagination, filters and Admin editing still work.
- **Filters:** `taxonomy: category` makes the theme list the terms and link `/route/category:<term>`. Only that collection reacts to URL filters (`url_taxonomy_filters`), and a modular parent never does, so its modules don't disappear.
- **Pagination:** set `limit` and `pagination`. With the `pagination` plugin enabled, the theme uses the plugin's partial, otherwise its own numbered links.
- **Search:** `search: true` adds a box that filters the collection by `?q=` (title, summary, terms). For full-text or instant search, install `tntsearch` and point its results at the collection.
- **Caching:** a module that holds a collection gets `cache_enable: false`, because its output depends on the URL.

A scoped copy only has the items the crawl saw (the first page of a 49-page directory). Say so in the handoff instead of faking extra items.

## When nothing fits

Build it in the theme or a small project plugin, in this order: a Twig partial plus blueprint fields, then a page type (`templates/<type>.html.twig` + `blueprints/pages/<type>.yaml`), then a Flex Objects directory for structured data. Then a plugin, if it needs PHP. Keep the content in frontmatter or Flex data, never in templates. Note the decision and the plugins you ruled out in the project notes.
