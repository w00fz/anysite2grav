# Quark2 conventions for source-matching themes

Consult this reference when extending the generated theme shell, adding module blueprints, or checking Grav/plugin integration. The comparison below records the original scaffold baseline. The adoption table identifies the changes now incorporated; other recommendations remain conditional.

**Source baseline:** official `getgrav/grav-theme-quark2`, `develop` at [`6e5fd40fbf9b9309607a9d9dea10486f5e0332e3`](https://github.com/getgrav/grav-theme-quark2/commit/6e5fd40fbf9b9309607a9d9dea10486f5e0332e3), inspected 2026-10-27 from a clean clone. Its theme blueprint reports version `1.1.19` and requires Grav `>=2.1.0`; the skill scaffold inspected at repository HEAD `c57224cc108520d9cff3eb78db0da678b18557e0` declares `>=2.0.0`. Verify APIs against the target installation rather than copying Quark2's compatibility declaration. [Quark2 metadata][q-metadata]

**Boundary:** retain the standalone theme and source-derived tokens, `.src-*` hooks, routes, navigation, section order and language behavior described in [theme.md](theme.md) and [content-model.md](content-model.md). Borrow integration conventions. Adopting Quark2 inheritance, its visual system, fonts, icons or additional interactions requires a separate source requirement or user decision.

## Incorporated into the scaffold

| Convention | Implementation |
| --- | --- |
| Deferred assets and focused blocks | Deferred `head` and `assets`, `assets.all()` once per head/bottom group, extension blocks for the body, classes, modals and bottom output. |
| Configuration ownership | `--force` seeds missing keys while keeping site overrides, explicit false/empty lists and theme blueprints; `--reset-config --force` deliberately recreates site settings. |
| CSS extension seam | `css/custom.css` loads after generated CSS and survives ordinary rebuilds. |
| Reusable Admin fields | Shared browser title, body classes and noindex fields imported by sections, modular and form page blueprints. |
| Navigation fidelity | Linked parent destinations plus separate disclosure controls, translated labels, `aria-current`, Escape focus return and dropdown edge fitting. |

See [theme.md](theme.md) for the supported extension and rebuild workflow, and [verification.md](verification.md) for acceptance checks. The regression suite under `tests/` uses an installed Grav 2 runtime; passing it does not replace a project's Admin edit and browser form-submission checks.

## 1. Adopt: keep lifecycle work and configuration ownership explicit

Quark2 registers loader work in `onTwigLoader` and Twig functions, filters and form styling variables in `onTwigInitialized`. Its subscribed `onThemeInitialized` currently has an empty body; that is not a reason to add an empty hook. Theme initialization belongs in that theme event when needed, rather than `onPluginsInitialized`. [Theme class][q-lifecycle], [official theme lifecycle guidance](https://learn.getgrav.org/2/themes/theme-tutorial#required-items-to-function)

**At the original baseline:** the [theme class](../assets/theme/__THEME_SLUG__.php) registers Twig helpers at the correct event and separately handles shared-form registration and response headers. The [scaffolder](../scripts/scaffold_theme.py) separates packaged defaults from site settings under `user/config/themes/<slug>.yaml`.

**Gap / adoption criterion:** document which settings may inherit from page headers. Quark2 uses `theme_var()` for visual settings; Grav documents page → ancestors → theme → explicit default lookup. Use that only where per-page visual overrides are intended. Keep preview indexing and analytics policy tied to the existing theme settings. Preserve explicit `false` values; test a page disabling an inherited option. Do not copy Quark2's deprecated `header_var()` calls from its blog templates. [Shell settings][q-settings], [blog lookups][q-blog], [official lookup semantics and deprecation](https://learn.getgrav.org/2/themes/twig-tags-filters-functions/functions#theme_var)

## 2. Adopt first: defer asset output until nested templates register assets

Quark2 separates asset registration from a deferred head-output block, then emits the bottom script group separately. Its gallery illustrates why: a module registers inline CSS while rendering content. Grav explicitly documents deferred output as the way to collect assets registered later in the template tree. [Asset blocks][q-assets], [gallery registration][q-gallery], [official Asset Manager](https://learn.getgrav.org/2/themes/asset-manager)

**At the original baseline:** [base.html.twig](../assets/theme/templates/partials/base.html.twig) uses Asset Manager priorities, emits default-group plugin scripts, and puts theme JS in the bottom group with browser `defer`. Includes preserve the context needed by forms, as documented in [theme.md](theme.md).

**Gap at the original baseline:** head CSS/JS output is immediate, before content modules, footer forms and dialogs render. Add a named deferred output block while preserving both groups and existing analytics/SEO behavior. Browser script `defer` controls execution; it does not solve Twig registration timing. Use the installed Grav version's render API, including its link/module support; the current docs recommend `assets.all()`. Avoid emitting the same group twice.

**Verify:** a later module registers a stylesheet, inline CSS and a script; all appear once in the intended groups. Exercise nested Form/CAPTCHA assets, including cached-page rendering, rather than assuming route 200 proves integration.

## 3. Adopt: offer small Twig extension points inside the owned shell

Quark2 provides blocks for navigation, hero, surrounding content, messages and bottom assets; its reusable two-column layout exposes item/sidebar blocks through `embed`. This lets page types change a region without duplicating the document. [Shell regions][q-regions], [layout component][q-layout], [content surround][q-content]

**At the original baseline:** the base exposes head, stylesheet, header, content, footer and JavaScript blocks, and page templates extend it.

**Gap / adoption criterion:** provide a bottom-output block and narrow navigation or content-surround blocks when a source layout needs them. Preserve `parent()` when appending registrations/output. Introduce a shared embedded layout only after multiple source-derived page types need it. Keep the existing shell, skip link and SEO partials; Quark2's block trait, containers and default title formatting are implementation choices, not migration requirements.

## 4. Adopt: treat blueprints and rendered data as one contract

Quark2 gives features and galleries named repeatable fields, validates positive thumbnail dimensions, and imports shared blog fields. Its logo template expects an upload mapping, while its icon filter normalizes several Admin/manual icon shapes; the filter's source explains a real picker-to-template mismatch. [Features blueprint][q-features], [gallery blueprint][q-gallery-fields], [shared fields][q-blog-fields], [logo value handling][q-logo], [icon normalization][q-icon]

**At the original baseline:** [sections.yaml](../assets/theme/blueprints/pages/sections.yaml) and [modular/section.yaml](../assets/theme/blueprints/pages/modular/section.yaml) import the same block fields. The skill already requires template/blueprint pairs and rerunnable specialization scripts. Hero/cards/gallery blueprints initially inherit the generic section editor; that is a useful fallback, not a claim that they have specialized fields.

**Gap / adoption criterion:** specialize recurring source sections with named fields only when editor needs justify it; update renderer, blueprint and conversion together. Validate dimensions and structured values, and keep import contexts explicit. Retain this scaffold's Admin2 blueprint locations rather than relocating them to match Quark2. [Official blueprint inheritance/imports](https://learn.getgrav.org/2/forms/blueprints/advanced-features)

**Verify:** save, clear, reorder and remove fields in Admin2/MCP, then check rendered output and retained frontmatter. Keep current `media` values as strings unless the editor contract deliberately changes; switching to Quark2's `file` picker requires normalization. Add Font Awesome normalization only if that picker/set was chosen; preserve source SVGs by default.

## 5. Conditional: modular menus, with source order and stable anchors

Quark2 renders module collections, offers an on-page menu, and derives anchor IDs from menu labels. It also renders all hero modules in a separate pass before other modules. These suit its one-page design but can reorder a migrated page or produce changing/duplicate anchors when labels repeat or are translated. [Modular template][q-modular], [modular blueprint][q-modular-fields]

**At the original baseline:** [modular.html.twig](../assets/theme/templates/modular.html.twig) renders the collection in one pass; the content builder preserves source order and explicit section anchors. Keep that behavior.

**Adoption criterion:** add an on-page menu only when the source has one or the user requests it. Use preserved source IDs or persistent explicit IDs, with unique target validation. Keep menu visibility separate from whether section content renders. Test hidden/deleted modules, duplicate headings, translated labels and fixed-header offsets. Respect reduced motion in JavaScript scrolling; Quark2's modular click handler requests smooth scrolling unconditionally, so its global CSS motion rule is not enough to copy that handler unchanged.

## 6. Adopt selectively: robust navigation geometry and semantics

Quark2's recursive navigation preserves parent destinations and marks active ancestors. Its dropdown fitting code considers nested panels, RTL, the opposite edge after flipping, resize and web-font completion. These are useful robustness cases. [Navigation macro][q-navigation], [panel fitting][q-navigation-js]

**At the original baseline:** [header.html.twig](../assets/theme/templates/partials/header.html.twig) has disclosure buttons and `aria-expanded`; [site.js](../assets/theme/js/site.js) handles clicks and Escape for dropdowns. A skip link, native dialogs and reduced-motion CSS already exist.

**Gaps at the original baseline:** a menu item with children is rendered only as a button, even if it also has a source URL; active styling compares only direct URLs; panel positioning has no viewport-fit pass. Preserve a linked parent's destination alongside its disclosure control when the source has both, expose current-page state with `aria-current`, and translate the navigation landmark label. Support deeper groups when present in source; keep the configured source menu instead of replacing it with `pages.children.visible`.

**Avoid copying:** Quark2's mobile overlay toggle only changes classes; the inspected handler does not synchronize expanded state, handle Escape, or manage focus. Its dialog role alone does not supply those behaviors. Verify keyboard focus/return, mobile close behavior, no-JS reachability and narrow/RTL/font-loaded layouts explicitly. [Overlay markup][q-overlay], [toggle handler][q-mobile-js]

## 7. Adopt: make plugin styling and availability explicit

Quark2 supplies Form's `form_*_classes` Twig variables centrally and checks enabled optional plugins before rendering search/sidebar features. Its gallery, however, delegates image output to a lightbox partial with `ignore missing`, so that partial's absence can omit the image markup entirely. [Form class variables][q-lifecycle], [optional-plugin guards][q-sidebar], [gallery output][q-gallery]

**At the original baseline:** shared forms are registered before rendering/POST handling; [form-embed.html.twig](../assets/theme/templates/partials/form-embed.html.twig) renders Form's own template with context intact. Form processing, CAPTCHA and submissions are covered by the existing workflow.

**Gap / adoption criterion:** use Form's supported styling variables when generic plugin wrappers cannot match the source; select this theme's class names, not Quark2's framework classes. Required plugins should be installed and checked explicitly. Optional enhancements should guard their availability and retain real content through a plain-image/link fallback. `ignore missing` is appropriate only where omission is acceptable. Verify plugin-disabled behavior and form error/success states; never hide a missing required integration behind a successful page response.

## 8. Adopt measured performance practices; condition every visual effect

Quark2 self-hosts WOFF2 fonts with swap display, preloads two critical faces, ships built CSS, and keeps theme JS framework-free. Its scroll logic uses passive listeners, animation-frame throttling for parallax, and separate on/off thresholds to avoid header shrink oscillation. Gallery thumbnails use Grav media transforms. [Fonts][q-fonts], [preloads][q-preloads], [build inputs][q-build], [scroll logic][q-scroll], [gallery media][q-gallery]

**At the original baseline:** source font downloading, optional Tailwind build output, dependency-free JS, responsive derivatives for image blocks, lazy media and global motion reduction are present. [Theme guidance](theme.md) already calls for sized media and source-relative Lighthouse checks.

**Gaps / adoption criteria:** generic gallery images still use original URLs and all generic image blocks are lazy. Choose eager loading/preload for the actual above-the-fold image or poster; derive gallery sizes from its source layout. Preload only font files used by critical content, preserve required language coverage/weights and check licensing. Add throttling/hysteresis only when implementing a source effect that needs it. Compare transfer, layout shift and visual crops before/after; fixed `600×450` crops, new parallax and a global icon CDN are not safe defaults.

## 9. Conditional: appearance preferences; avoid importing a redesign

Quark2 resolves saved preference before paint and follows OS changes in auto mode. It synchronizes desktop/mobile controls, translates runtime labels through Twig data attributes and tolerates unavailable storage. These are useful when the source or requested product includes an appearance selector. [Pre-paint bootstrap][q-bootstrap], [appearance controller][q-appearance]

**At the original baseline:** source-derived tokens and per-language theme strings; an appearance selector is intentionally not a generic migration feature.

**Adoption criterion:** when requested, use a project-specific storage key, validate stored modes, preserve source defaults, check blocked storage/live OS changes and synchronize every control. Avoid importing Quark2's palette, Cal Sans/Inter fonts, Blades resets, Font Awesome dependency, blog/sidebar UI or fixed/fluid header behavior into unrelated sites. Accessibility repairs can accompany parity work; new visual features need an explicit decision and recorded deviation. The existing [visual acceptance process](verification.md) remains the completion gate.

[q-metadata]: https://github.com/getgrav/grav-theme-quark2/blob/6e5fd40fbf9b9309607a9d9dea10486f5e0332e3/blueprints.yaml#L1-L18
[q-lifecycle]: https://github.com/getgrav/grav-theme-quark2/blob/6e5fd40fbf9b9309607a9d9dea10486f5e0332e3/quark2.php#L9-L53
[q-settings]: https://github.com/getgrav/grav-theme-quark2/blob/6e5fd40fbf9b9309607a9d9dea10486f5e0332e3/templates/partials/base.html.twig#L1-L11
[q-blog]: https://github.com/getgrav/grav-theme-quark2/blob/6e5fd40fbf9b9309607a9d9dea10486f5e0332e3/templates/blog.html.twig#L1-L8
[q-assets]: https://github.com/getgrav/grav-theme-quark2/blob/6e5fd40fbf9b9309607a9d9dea10486f5e0332e3/templates/partials/base.html.twig#L67-L89
[q-gallery]: https://github.com/getgrav/grav-theme-quark2/blob/6e5fd40fbf9b9309607a9d9dea10486f5e0332e3/templates/modular/gallery.html.twig#L1-L35
[q-regions]: https://github.com/getgrav/grav-theme-quark2/blob/6e5fd40fbf9b9309607a9d9dea10486f5e0332e3/templates/partials/base.html.twig#L93-L164
[q-layout]: https://github.com/getgrav/grav-theme-quark2/blob/6e5fd40fbf9b9309607a9d9dea10486f5e0332e3/templates/partials/layout.html.twig#L1-L11
[q-content]: https://github.com/getgrav/grav-theme-quark2/blob/6e5fd40fbf9b9309607a9d9dea10486f5e0332e3/templates/blocks/base.html.twig#L1-L3
[q-features]: https://github.com/getgrav/grav-theme-quark2/blob/6e5fd40fbf9b9309607a9d9dea10486f5e0332e3/blueprints/modular/features.yaml#L1-L38
[q-gallery-fields]: https://github.com/getgrav/grav-theme-quark2/blob/6e5fd40fbf9b9309607a9d9dea10486f5e0332e3/blueprints/modular/gallery.yaml#L1-L49
[q-blog-fields]: https://github.com/getgrav/grav-theme-quark2/blob/6e5fd40fbf9b9309607a9d9dea10486f5e0332e3/blueprints/item.yaml#L71-L72
[q-logo]: https://github.com/getgrav/grav-theme-quark2/blob/6e5fd40fbf9b9309607a9d9dea10486f5e0332e3/templates/partials/logo.html.twig#L1-L14
[q-icon]: https://github.com/getgrav/grav-theme-quark2/blob/6e5fd40fbf9b9309607a9d9dea10486f5e0332e3/quark2.php#L55-L104
[q-modular]: https://github.com/getgrav/grav-theme-quark2/blob/6e5fd40fbf9b9309607a9d9dea10486f5e0332e3/templates/modular.html.twig#L3-L73
[q-modular-fields]: https://github.com/getgrav/grav-theme-quark2/blob/6e5fd40fbf9b9309607a9d9dea10486f5e0332e3/blueprints/modular.yaml#L18-L47
[q-navigation]: https://github.com/getgrav/grav-theme-quark2/blob/6e5fd40fbf9b9309607a9d9dea10486f5e0332e3/templates/macros/macros.html.twig#L1-L18
[q-navigation-js]: https://github.com/getgrav/grav-theme-quark2/blob/6e5fd40fbf9b9309607a9d9dea10486f5e0332e3/js/site.js#L14-L69
[q-overlay]: https://github.com/getgrav/grav-theme-quark2/blob/6e5fd40fbf9b9309607a9d9dea10486f5e0332e3/templates/partials/base.html.twig#L116-L159
[q-mobile-js]: https://github.com/getgrav/grav-theme-quark2/blob/6e5fd40fbf9b9309607a9d9dea10486f5e0332e3/js/site.js#L73-L89
[q-sidebar]: https://github.com/getgrav/grav-theme-quark2/blob/6e5fd40fbf9b9309607a9d9dea10486f5e0332e3/templates/partials/sidebar.html.twig#L3-L50
[q-fonts]: https://github.com/getgrav/grav-theme-quark2/blob/6e5fd40fbf9b9309607a9d9dea10486f5e0332e3/css/fonts.css#L1-L33
[q-preloads]: https://github.com/getgrav/grav-theme-quark2/blob/6e5fd40fbf9b9309607a9d9dea10486f5e0332e3/templates/partials/base.html.twig#L29-L31
[q-build]: https://github.com/getgrav/grav-theme-quark2/blob/6e5fd40fbf9b9309607a9d9dea10486f5e0332e3/package.json#L1-L17
[q-scroll]: https://github.com/getgrav/grav-theme-quark2/blob/6e5fd40fbf9b9309607a9d9dea10486f5e0332e3/js/site.js#L91-L127
[q-bootstrap]: https://github.com/getgrav/grav-theme-quark2/blob/6e5fd40fbf9b9309607a9d9dea10486f5e0332e3/templates/partials/base.html.twig#L51-L64
[q-appearance]: https://github.com/getgrav/grav-theme-quark2/blob/6e5fd40fbf9b9309607a9d9dea10486f5e0332e3/js/theme-toggle.js#L14-L94
