# Forms

## Contents
- Questions to ask
- How forms are built
- The plan file
- CAPTCHA providers
- Email delivery
- Third-party embeds
- Testing
- Gotchas

## Questions to ask

Ask per form (or once as the default) after showing the audit's form list. Recommend the first option unless the audit suggests otherwise:

| Decision | Options | Notes |
| --- | --- | --- |
| Delivery | **save** to `user/data/<form>/` · **email** (SMTP) · both · **webhook** · keep the **third-party embed** | Hosted builders (Webflow, Squarespace) handle submissions on their servers, and that path ends with the migration. Ask where submissions should go now. Email needs from/to addresses and an SMTP provider. |
| CAPTCHA | **Cap** (built into Grav Form 9: invisible proof-of-work, self-hosted, no keys) · Turnstile · reCAPTCHA · basic math · none | Cap is the default, and the user corrected a Turnstile choice before. Multi-instance deployments need shared Cap storage (e.g. Redis). |
| Success | **inline message** (source copy) · redirect to a thank-you page · display a sub-page | Inline uses XHR, so modals and footers keep context. |
| Consent / storage notice | keep source wording · add a privacy line | Never claim delivery that isn't configured. |
| Separate lists | keep each source form separate (newsletter ≠ demo request ≠ waitlist) | Don't merge forms with different purposes or consent. |

Also check what the source does after submit. Download forms often just reveal a PDF and store nothing, and some forms post to Calendly or HubSpot. Replicate the real behavior, not a guess.

## How forms are built

`build_forms.py` turns each distinct source form (deduped by provider + action + field names) into a page:

```
user/pages/forms/<name>/form.<lang>.md     # one file per language that used it
```

```yaml
title: "Newsletter form"
visible: false
noindex: true
cache_enable: false
sitemap: {ignore: true}
form:
  name: newsletter-form
  action: /forms/newsletter-form    # always post to the defining page
  xhr_submit: true                  # inline result, no navigation
  keep_alive: true
  fields:
    first_name: {type: text, label: "First Name", validate: {required: true}}
    email: {type: email, label: "Email", validate: {required: true, type: email}}
    captcha: {type: captcha, provider: cap}
  buttons: [{type: submit, value: "Subscribe"}]
  process:
    - save: {fileprefix: newsletter-form-, dateformat: Ymd-His-u, extension: txt, body: "{% include 'forms/data.txt.twig' %}"}
    - message: "Thank you! Your submission has been received!"
    - reset: true
```

Pages show the form with a `form` block. The theme renders `forms({route: '/forms/<name>'})` through `partials/form-embed.html.twig`. `shared_form_routes` in theme config lists these pages, and the theme replays Grav's form registration for them on every request. Without that replay, cached page trees can leave an embedded form unregistered: it renders, but POSTs fail or the form disappears for some sessions.

Each language variant of a form is its own plan entry (labels, submit text and messages come from that language's page); variants sharing a builder name land in the same `/forms/<name>` folder as `form.<lang>.md`. Two different forms with the same builder name in one language get a `-2` suffix instead of overwriting each other.

Headings and helper/consent text inside the source `<form>` become `display` fields (`form_heading`, `form_note_N`). Links revealed in the success block (download-gated PDFs) are appended to the success message, pointing at the imported file in `user/media/files`.

Builders often duplicate one form per page ("Demo Req - Pricing Form", "Demo Req - About Form") with identical fields. These collapse into one Grav form. If the user needs attribution, add a hidden field (e.g. `source_form`) and fill it per page: set a frontmatter value on each embedding page and pass it through a small theme tweak in `form-embed.html.twig`.

Field mapping: radio groups and same-name checkboxes merge into `radio`/`checkboxes`; selects keep options and use the empty option as a placeholder; `maxlength`/`pattern` become `validate`; hidden fields keep their values.

## The plan file

`--init` writes `migration/forms-plan.json`: `defaults` (`delivery`, `captcha`, `success`, `email`) plus one entry per form with its fields, languages, pages and modal flag. Edit the defaults or per-form fields with the user's answers (or set `"enabled": false`), then run without `--init`. Rerunning rewrites the form pages from the plan.

## CAPTCHA providers

`user/config/plugins/form.yaml` (written for the providers used):

```yaml
cap: {mode: invisible, storage: grav-cache, challenge_difficulty: 4}
turnstile: {site_key: "…", secret_key: "…"}      # keys from Cloudflare
recaptcha: {version: "3", site_key: "…", secret_key: "…"}
```

Field: `{type: captcha, provider: cap|turnstile|recaptcha}` or `{type: basic-captcha}`. Keep secrets out of git: put them in `user/env/<host>/config/plugins/form.yaml` (ignored) or environment overrides. The web server must serve Cap's `.wasm` file with `application/wasm`. Apache configs that allowlist static extensions can block it.

## Email delivery

1. Configure `user/config/plugins/email.yaml`: `from`, `to`, `mailer.engine: smtp`, `mailer.smtp.server/port/encryption/user`.
2. Password via env: `GRAV_CONFIG=true` plus `GRAV_CONFIG__plugins__email__mailer__smtp__password=…`. Never put it in YAML.
3. Local testing: Mailpit (`brew install mailpit`, or the Docker compose service) on `127.0.0.1:1025` with no encryption; read mail at `:8025`.
4. Add `"email"` to the plan's delivery and rerun `build_forms.py`. It refuses while `email.yaml` lacks from/to, because Grav's email action throws (HTTP 500 on submit) without a recipient.
5. Send from a domain the SMTP provider has verified. Some providers verify each sending subdomain separately.

## Third-party embeds

Set delivery `["embed"]` to skip the Grav form and keep the provider. Put its embed code in a `{type: html}` block (HubSpot `hbspt.forms.create`, Typeform, Jotform, Calendly inline widget) and add the provider's script only on pages that need it. Confirm the provider account will keep working after the migration.

## Testing

Cap solves its challenge in the browser, so test with a real browser (Playwright, or the agent's browser tool):

1. Open a page that embeds the form, fill the required fields, submit.
2. Expect the inline success message in place (URL unchanged) and a new file in `user/data/<form>/` (or a Mailpit message).
3. Submit with a required field empty: expect a validation message, no record.
4. Repeat inside a modal and in a second language.
5. Delete test records afterwards.

## Gotchas

- `save` only allows safe extensions: use `txt` (YAML/JSON extensions are rejected with a 500).
- `email` without a configured `to` → 500 on every submit.
- Forms in modals: after a non-XHR submit the page reloads with the dialog closed. Keep `xhr_submit`, or reopen the dialog when a form message is present (the theme JS does).
- Duplicate element IDs (the same form embedded twice on one page) break labels. Render each form once per page.
- Don't set `keep_alive: true`: it loads Form's `form.min.js`, which expects jQuery, and the scaffolded theme ships none (`jQuery is not defined` on every page with a form).
- Hidden fields get a label so saved/emailed records read `Source form: …` instead of `: …`.
- Webflow's success/error blocks (`.w-form-done`/`.w-form-fail`) are captured as the form's messages, not page text.
