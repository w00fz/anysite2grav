# anysite2grav

Rebuild a live website as an editable [Grav 2](https://getgrav.org) site with a new theme, native pages and modules, Admin2, and API and MCP access for your agent.

The goal is source fidelity: the same routes, content, layout, spacing, typography, colors, borders, highlights, and interactions. Your agent uses the scripts to import a draft, then builds and verifies the source-specific templates and blueprints.

**Status: early access.** The helpers have automated coverage, including Grav integration and browser comparisons. A fresh end-to-end migration using the revised fidelity workflow still needs validation. Review each generated site before treating the migration as complete.

[Website and overview](https://anysite2grav.djamil.dev) · [Agent workflow](skills/anysite2grav/SKILL.md) · [Fidelity guide](skills/anysite2grav/references/fidelity.md)

## Install

### Codex

Paste this prompt into Codex:

```text
$skill-installer Install anysite2grav from https://github.com/w00fz/anysite2grav/tree/main/skills/anysite2grav
```

If the installed skill does not appear, restart Codex. See the [official skill installation guidance](https://learn.chatgpt.com/docs/build-skills#install-curated-skills-for-local-use).

### Claude Code

Run these commands inside Claude Code to add this repository as a marketplace and open the plugin installation panel:

```text
/plugin marketplace add w00fz/anysite2grav
/plugin install anysite2grav@anysite2grav
```

Choose an installation scope when prompted. To update the installed plugin later, run this command in your terminal:

```bash
claude plugin update anysite2grav@anysite2grav
```

See the [official plugin installation and update guidance](https://code.claude.com/docs/en/discover-plugins).

### Local development or another compatible agent

Clone the repository, then link the skill into your client's skill directory:

```bash
git clone https://github.com/w00fz/anysite2grav.git ~/Projects/anysite2grav
mkdir -p ~/.agents/skills
ln -s ~/Projects/anysite2grav/skills/anysite2grav ~/.agents/skills/anysite2grav
```

For a local Claude Code skill, use `~/.claude/skills/anysite2grav` as the link destination instead. Create `~/.claude/skills` first. [Codex](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills) and [Claude Code](https://code.claude.com/docs/en/skills#choose-where-skills-load) support symlinked skill folders.

For linked installations, update the checkout with `git pull`. Other agents that support [Agent Skills](https://agentskills.io) can load `skills/anysite2grav/`.

If repository access is restricted, your GitHub account needs read access to install or clone it.

## Start a migration

In Codex:

```text
Use $anysite2grav to rebuild https://example.com locally in ~/Sites/example-grav.
```

With the Claude Code plugin:

```text
/anysite2grav:anysite2grav Rebuild https://example.com locally in ~/Sites/example-grav.
```

The agent asks for choices that are not already specified: runtime, connected clients, theme name, Tailwind or plain CSS, languages, form delivery, CAPTCHA, and analytics. It audits the source before asking about the options that depend on the site.

Give the agent the source URL and destination folder. Specify any route restrictions or known external integrations. Use source content and assets that you are authorized to reproduce.

## What the workflow does

1. Installs Grav with Admin2 in a new project folder. Creates an authoring account, API key, MCP launcher, and project configuration. Global client configuration changes require your approval.
2. Discovers routes through sitemaps and same-site links. Audits forms, analytics, embeds, media, fonts, languages, redirects, and source features.
3. Imports content into Markdown and YAML frontmatter. Composed pages become ordered modules or individual page types. Articles retain a Markdown body. Each final page or module type has a matching blueprint for editing in Admin.
4. Builds a standalone theme from the source design. Finishes a representative page with dedicated Twig templates, named fields, and exact responsive styles before expanding that design family across the site.
5. Recreates functionality with Grav core and compatible plugins. Styles plugin output to match the source, including hover, focus, selected, open, and error states. Tests forms against their configured delivery destination.
6. Verifies routes, content, component measurements, full-color screenshots, interactions, and CMS editing. Keeps local and preview hosts out of search, and gates approved analytics to production hosts.

The [full workflow](skills/anysite2grav/SKILL.md) has 13 checkpoints. The [fidelity guide](skills/anysite2grav/references/fidelity.md) explains source inspection, content modeling, plugin styling, and acceptance.

## Requirements

The agent needs shell and filesystem access, plus network access to the source site and download hosts.

| Tool | Requirement |
| --- | --- |
| PHP | 8.3+ for Grav and the current host-side bootstrap and YAML helpers |
| Python | 3.9+, standard library only |
| Node.js and npm | Node 20+ for the migration tools, including the pinned Playwright browser helpers |
| Shell tools | Bash, `curl`, and `unzip` for the installation and setup scripts |
| Browser | Playwright and Chromium, installed in the migration project's `.tools` directory by the capture helpers |

PHP extensions required for the native Grav runtime: `curl ctype dom gd json mbstring openssl session simplexml xml zip`. Recommended: `intl yaml apcu opcache exif`.

Docker can run Grav and Mailpit, but the current host-side helpers still invoke PHP. See the [runtime and Docker setup guide](skills/anysite2grav/references/setup.md). The overview website's build tools require Node 22.18+.

## Generated project

```text
example-grav/
  grav/
    user/
      pages/              Markdown, frontmatter, modules, and page media
      themes/<theme>/     Twig templates, blueprints, CSS, and JavaScript
      config/             Site, plugin, language, and theme settings
      media/              Shared images and documents
  migration/              Crawl data, imported assets, transforms, and reports
  .local/                 Credentials and local server state
  bin/grav-mcp             Launcher that reads the API key at startup
  .mcp.json                Claude Code project MCP configuration
```

The agent connects each selected MCP client and verifies that it can list pages. Credentials stay in `.local/credentials.json`; client configuration points at the launcher. Keep credentials and form submissions out of Git.

See the [content model](skills/anysite2grav/references/content-model.md), [form configuration](skills/anysite2grav/references/forms.md), and [Grav feature map](skills/anysite2grav/references/grav-features.md) for details.

## Fidelity and current limits

- The generic theme and inferred tone, spacing, and layout settings are draft inputs. The agent must preserve exact source values in reusable theme components and author dedicated content types where needed.
- Imports cover discovered routes within the agreed crawl scope. A scoped directory import needs enough data to reproduce its search, filters, and pagination, or an agreed integration with the original provider.
- Custom widgets, client-rendered content, animations, and responsive variants can require additional extraction and implementation. An inaccessible feature or dataset remains an open requirement.
- `build_pages.py` records unresolved controls in `unresolved-controls.json` and fails by default when controls remain. `--allow-incomplete` permits a draft import; it does not approve missing functionality.
- Screenshot grayscale scores are triage hints. Text coverage and selected component matches do not establish whole-site fidelity. Review full-color screenshots, exercise controls, and save content through Admin or the API.
- Review font and asset licenses before production. Configure real form delivery and verify preview indexing and analytics behavior before deployment.

See the [verification checklist](skills/anysite2grav/references/verification.md) for completion criteria.

## Extend the theme

The theme stays standalone. A [source-linked review of Quark2](skills/anysite2grav/references/quark2-conventions.md) documents the conventions used for deferred plugin assets, Twig extension blocks, and reusable blueprint fields.

Put project overrides in `css/custom.css`. It loads after the generated stylesheet. Ordinary forced scaffold rebuilds preserve site settings, theme configuration blueprints, and custom CSS. Review replacement flags and page-import changes before rerunning them against an edited site.

Read the [theme guide](skills/anysite2grav/references/theme.md) before changing templates or the stylesheet pipeline.

## Scripts

Run these through the agent workflow so setup, configuration choices, imports, and verification happen in order.

| Script | Purpose |
| --- | --- |
| `install_grav.sh` | Install Grav with Admin2 and check PHP requirements |
| `serve_grav.sh` | Start, stop, or inspect the local PHP server |
| `bootstrap_access.sh` | Create or reuse the authoring account, API key, and MCP launcher |
| `crawl_site.py` | Discover routes and cache HTML, stylesheets, and redirects |
| `audit_site.py` | Inventory forms, trackers, embeds, fonts, and colors |
| `extract_content.py` | Extract sections, blocks, shared content, navigation, and layout groups |
| `measure_layout.mjs` | Measure source sections and blocks for the draft layout model |
| `import_media.py` | Download, deduplicate, and assign media |
| `build_pages.py` | Build native page, module, collection, and media files |
| `scaffold_theme.py` | Generate the draft theme, initial tokens, and optional Tailwind setup |
| `build_forms.py` | Build Grav Form pages from the chosen configuration |
| `capture_pages.mjs` | Capture screenshots, design tokens, and section metrics |
| `compare_components.mjs` | Compare paired component geometry, CSS, pseudo-elements, and UI states |
| `verify_parity.py` | Check route, content, metadata, media, and preview behavior |
| `grav_config.php` | Read, merge, and lint YAML through Grav |

## Run the checks

Set `GRAV_TEST_ROOT` to an installed Grav 2 runtime with PHP 8.3+ available on `PATH`. The tests create temporary sites and leave that runtime unchanged:

```bash
GRAV_TEST_ROOT=/path/to/grav python3 -m unittest discover -s skills/anysite2grav/tests -v
```

For browser comparator tests, point `GRAV_PLAYWRIGHT_TOOLS` at a migration's `.tools` directory containing Playwright and its installed Chromium browser:

```bash
GRAV_PLAYWRIGHT_TOOLS=/path/to/migration/.tools node --test skills/anysite2grav/tests/test_component_comparison.mjs
```

Grav integration tests skip without a valid runtime. Browser tests skip without `GRAV_PLAYWRIGHT_TOOLS`. Check skipped tests before treating a run as complete.

The tests cover extraction, rebuild preservation, blueprint resolution, real Grav rendering, embedded Form and Cap assets, and controlled browser comparisons. Each migrated site still needs its own visual, interaction, form-delivery, and editing checks.

## Publish the overview

This section is for maintainers of [anysite2grav.djamil.dev](https://anysite2grav.djamil.dev). The repository's Cloudflare configuration targets Djamil's personal account and the `anysite2grav` Worker. To host your own copy, change `cloudflare.config.ts` before deployment and review `wrangler.config.ts`.

With Node 22.18+, install the deployment dependencies:

```bash
npm ci
```

If you need a login for this project, create a named Cloudflare profile once:

```bash
npx cf auth create anysite2grav
```

Confirm that the profile can access the configured account, then dry-run and deploy:

```bash
npx cf auth whoami --profile anysite2grav
npm run deploy -- --profile anysite2grav --dry-run
npm run deploy -- --profile anysite2grav
```

Use your existing profile name if it differs. Passing the profile explicitly avoids changing the default login used by other projects.

The default deployment publishes `docs/`. `npm run deploy:legacy -- --profile anysite2grav` publishes only `hosting/legacy/` to the previous `website2grav` Worker. That Worker redirects its custom domain and workers.dev URL to the canonical site, preserving paths and query strings. Pushing to GitHub does not deploy the overview.

## Report a bug

[Open an issue](https://github.com/w00fz/anysite2grav/issues) with the agent client, operating system, tool versions, failing command, and error output. Include a source URL and screenshots when they can be shared. Remove credentials, private content, and form submissions from reports.

## License

[MIT](LICENSE). The website includes the [Inter](docs/fonts/OFL-Inter.txt) and [Google Sans](docs/fonts/OFL-Google-Sans.txt) font licenses.
