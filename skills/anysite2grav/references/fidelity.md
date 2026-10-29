# Build from the source, then prove the Grav result

Read this before building templates. The scripts extract content and scaffold a **draft**. Their generic blocks, four tones, spacing buckets and inferred layouts lose information. A successful script run does not establish design parity.

## Inventory before implementation

Inspect rendered pages alongside the cached HTML and stylesheets. Group routes by actual composition, including header/footer variants and responsive behavior. For each distinct section or widget record:

- Source route and selector; its local selector once implemented; routes that reuse it.
- Exact container and text widths, all four padding/margin sides, gaps, grid/flex tracks, alignment, ordering, heights and sticky/overlap behavior.
- Font files, weight, size, line height, tracking, wrapping, inline emphasis, link decoration and highlighted text. Wait for fonts to load before measuring.
- Colors (including alpha), gradients, images/crops, borders on each side, radii, shadows, icons and generated `::before`/`::after` decoration.
- Desktop, tablet, mobile, and both sides of source breakpoints. Preserve differences between widths instead of scaling the desktop layout down indiscriminately.
- Default, hover, keyboard focus, active/selected, open/closed, disabled, empty and error states where applicable. Observe animation timing, easing and scroll behavior separately from reduced-motion screenshots.
- Functionality and its data source: search scope, pagination, taxonomy, sorting, filtering, form delivery, dialogs, galleries and feeds. Trace what controls open and what changes after input.

Use the original CSS rules to recover `clamp()`, media queries, custom properties and state selectors. Computed values explain one viewport; they do not reveal the responsive rule by themselves. Keep source evidence and machine-readable mappings in `migration/`; decisions and progress belong in the user's working-doc store.

## Choose Grav types before expanding the site

Define the template, fields, blueprint and media ownership for each composition. Use the site's vocabulary: `editorial-hero`, `feature-split`, `theme-directory`, `release-notes`, for example. Two visually different heroes can need different kinds. One kind reused across routes should have one template and blueprint.

| Source composition | Grav implementation |
| --- | --- |
| Independently editable horizontal sections | `modular.md` parent, ordered `_` child modules, a Twig template and matching blueprint per kind |
| Short page or unique composition best edited together | Named page type: `<kind>.md`, `templates/<kind>.html.twig`, `blueprints/pages/<kind>.yaml` |
| Article/legal/prose | Markdown body with the source's surrounding layout and shared chrome |
| Searchable/paginated records | Collections of pages or Flex records; real taxonomy and plugin behavior |
| Repeated site-wide section | Shared content with a dedicated renderer and blueprint |

The builder's three-section threshold is an initial import heuristic. Preserve a previously agreed cutoff; adapt ownership when the source or editor workflow calls for it. Generic `sections` blocks may remain when they really express the design and edit well. Do not spend the whole run adding global exceptions to a generic block renderer to avoid authoring a needed template.

Each content field must map to a blueprint field and rendered output. Keep prose in Markdown and content in frontmatter or records, not hardcoded Twig. A module can use its Markdown body for the description:

```text
user/pages/01.home/
  modular.en.md
  01._intro/editorial-hero.en.md
  02._capabilities/feature-split.en.md
user/themes/<theme>/
  templates/modular/editorial-hero.html.twig
  templates/modular/feature-split.html.twig
  blueprints/pages/modular/editorial-hero.yaml
  blueprints/pages/modular/feature-split.yaml
  css/src/editorial.css
```

```yaml
# editorial-hero.en.md, followed by its Markdown body
---
title: A recognizable section name
eyebrow: From the source
heading: The original heading
image: hero.webp
image_alt: The original alternative text
cta:
  label: Explore
  url: /explore
---
The source paragraph, with **emphasis** and [links](/details).
```

Render `page.header.heading`, `page.header.eyebrow`, media and CTA through purpose-built Twig; render `page.content` for the paragraph. Expose every field in the kind's blueprint, retaining the normal Markdown editor and page media. A renamed generic template with no named fields is not a specialized module. Confirm blueprint imports and fields in the running Admin/API, then edit and save a heading, paragraph, image and repeated item and check the rendered result.

Write any import transforms as rerunnable project scripts; run them after the generic builder. Keep the import code and an explicit rebuild command with the site's source. Rebuilding the input must recreate specialized pages without erasing later editorial changes accidentally. Never run destructive import/replacement flags against an edited site without checking the diff.

Official references: [modular pages](https://learn.getgrav.org/2/content/modular), [page blueprints](https://learn.getgrav.org/2/forms/blueprints/example-page-blueprint), [theme creation](https://learn.getgrav.org/2/themes/theme-tutorial).

## Match the design in theme code

Build the shared shell and one difficult representative page completely before expanding each layout family. Include its custom modules, blueprint editors, plugin output and responsive/state behavior. Test inner pages with alternate chrome as well as home. If that page fails, fix the architecture or styles before multiplying it across the sitemap.

- Derive reusable tokens from genuinely repeated source values. Preserve exact values, asymmetric insets, distinct colors and type weights; do not round them to the nearest `tone`, `space`, type step or image ratio when that changes the result.
- Put layout in the purpose-built theme component's CSS/Twig, with its real grid/flex structure. Port relevant source declarations and responsive/state rules deliberately against that structure. The automatic source-CSS porter's visual-only restriction protects its changed markup; it is **not** a ban on writing layout CSS or adapting source layout rules in custom components.
- Keep one stylesheet pipeline. Add component CSS through the site's entrypoint, or use `css/custom.css` while iterating. Tailwind may use exact arbitrary values and variants. A preflight/reset must not override source defaults unnoticed.
- Preserve inline text marks, underlines, highlight backgrounds, icon strokes and pseudo-elements. Check real loaded font weights and heading wrapping before adjusting surrounding spacing.
- Carry images, icons, fonts and CSS URL assets into local media/theme assets. Match `object-fit`, `object-position`, aspect ratio and rendered dimensions. Do not substitute identity assets.
- Use styles for each real state; rebuild behavior with semantic markup and keyboard support. Observe the live source; a screenshot cannot tell you what a dropdown or hover does.

## Match plugin output too

Use [grav-features.md](grav-features.md) to choose core functionality and compatible plugins. Verify installed version, configuration, template names and assets from its current README/GPM information. Do not equate installing a plugin with reproducing the feature.

Override the plugin's output in the **theme**, retaining its field names, action URLs, hidden fields, validation, pagination links and required JS/CAPTCHA assets. Style the emitted markup to the same source contract: control dimensions, typography, placeholder, icons, borders, hover/focus, selection, errors, result counts, empty states and mobile layout. Test search/filter combinations, clear/reset, next/previous pages and browser back/forward against the intended dataset. Native URL syntax may differ internally; preserve public source routes through supported routing/redirects where required.

Missing data must be resolved by importing it, keeping an approved provider, or agreeing a narrower scope. A first-page crawl does not justify dropping filters or shipping fake pagination. `unresolved-controls.json` identifies controls the draft builder could not render. Dialog controls with known rendered targets are wired to the scaffold's modal handler. Other label-only controls, including retained tab/toggle placeholders, still require behavior. Each must be implemented or explicitly excluded by the user; a handoff note alone does not approve an omission.

## Measure components and states

Create a project-specific JSON plan that pairs actual selectors on source and local pages. This is measurement input, not generated site content. Select the section wrapper **and** its inner text, image, control and repeated cards; measuring an outer rectangle alone misses internal errors. Cover every design family and widget, then route-specific differences.

```json
{
  "widths": [1440, 768, 390],
  "tolerance": 1,
  "cases": [{
    "id": "directory",
    "route": "/themes/",
    "elements": {
      "hero": {"source": ".source-hero", "local": ".directory-hero", "count": 1},
      "title": {"source": "main h1", "local": "main h1", "count": 1},
      "cards": {"source": ".source-card", "local": ".theme-card", "count": 12}
    },
    "states": [
      {"name": "default"},
      {"name": "first-card-hover", "steps": [
        {"action": "hover", "selector": {"source": ".source-card:first-child a", "local": ".theme-card:first-child a"}}
      ]},
      {"name": "search-focus", "steps": [
        {"action": "focus", "selector": {"source": "input[type=search]", "local": "input[type=search]"}}
      ]}
    ]
  }]
}
```

Replace the selectors and counts with inspected values; do not copy the example as an assumed site model. Add the hovered link and focused input to `elements` so their styles are measured. States may replace `elements` to target an opened dialog or expected-hidden region (`visible: false`). Cases may override `widths`, use different source/local `route` values, and run `setup` steps before every state. `steps` supports `hover`, `focus`, `click`, `fill` (`value`), `press` (`key`, optional selector), `scroll` (`top`) and `waitFor` (`state`). Selectors can be common strings or `{source, local}` pairs. Every action selector must match exactly one element. Use only read-only source interactions; submit forms and other mutations on the local test instance.

```bash
node $S/compare_components.mjs --plan <plan.json> --source <source-url> --local <local-url> \
  --out migration/components --tools migration/.tools
```

Reuse Playwright installed by `capture_pages.mjs`; this helper does not install packages. It writes `components.json`, `components.html` and full-color screenshots for every case/width/state, returning 1 for differences or failed captures, 2 for invalid configuration/runtime, 0 when the selected measurements match. Geometry and pixel lengths allow 1 CSS px by default; colors, weights and other strings compare exactly. It checks all matched items, pseudo-elements, key ARIA attributes, broken images, document height and local horizontal overflow. Empty selectors fail even when both match nothing. No source opacity/transform overrides are injected. Default reduced motion makes final-state comparisons repeatable; separately test original animation with `reducedMotion: "no-preference"` and the intended `settleMs`.

Use `properties` on an element to select CSS properties, `geometry` to select rectangle dimensions, `attributes` to select the measured ARIA/control attributes, and `text: false` only for a justified dynamic region. `count` fixes repeated-item cardinality; without it local must equal the nonzero source count. Tolerance changes and excluded measurements need a concrete reason recorded with the evidence. Custom CSS properties can be included in `properties`. Source/local asset URLs naturally change after media import; verify the underlying asset and crop, then narrow URL-sensitive properties deliberately rather than treating different URL strings as a visual defect. Likewise, equivalent DOM/CSS constructions may need a more precise pairing of painted elements; do not loosen geometry to hide a visible difference.

The comparator checks selected evidence, not the completeness of the plan or actual search/form behavior. Inspect the full-color screenshots and exercise the controls. A low-resolution grayscale score from `capture_pages.mjs` is only a triage hint: a 90+ score is never acceptance, and a low fold score is never excused by an unrelated full-page score. Do not mask a defect or change the reference to make a test pass. Stabilize genuinely dynamic source content and document the exact excluded region instead.

## Completion

Keep route/content parity, component measurements, interaction tests and CMS editability as separate requirements. Check every route for content/order/variant drift, every design family at desktop/tablet/mobile and source breakpoints, and every interactive component in its applicable states. Repeat after changing shared shell/type/spacing rules.

Close visible discrepancies before claiming 1:1. Any remaining design or functionality difference keeps that part incomplete unless the user explicitly accepts it. Report measured scope and unresolved differences honestly; do not call the generated draft a finished migration. User review is the last check on a completed result, not a request to accept missing implementation.
