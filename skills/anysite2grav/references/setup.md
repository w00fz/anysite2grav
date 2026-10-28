# Setup: Grav, Admin2, API and MCP

## Contents
- Runtimes (PHP server, Docker, existing stacks)
- What `install_grav.sh` installs
- Accounts, API keys and the MCP launcher
- Connecting agent clients
- HTTPS, custom hosts and tunnels
- Git and `.gitignore`
- Production profile
- Troubleshooting

## Runtimes

| Option | When | How |
| --- | --- | --- |
| PHP built-in server (default) | Fastest start; PHP 8.3+ on the machine | `install_grav.sh <project>` then `serve_grav.sh <project> start --port 8000` (uses Grav's `system/router.php`) |
| Docker | No local PHP, or the user wants an isolated runtime | `assets/docker/` (below) |
| Existing stack (Valet, Herd, MAMP, Apache/nginx) | The user already serves local sites | Point the vhost at `<project>/grav`; Apache needs `AllowOverride All` + `mod_rewrite` |

The built-in server is single-threaded but fast enough for one person and a full verifier run.

### Docker

```bash
cd <project>
D=<skill-dir>/assets/docker
SKILL_DOCKER_DIR=$D LOCAL_UID=$(id -u) LOCAL_GID=$(id -g) docker compose -f $D/compose.yaml --project-directory . up -d --build
```

`grav/user` is bind-mounted and seeded with Grav's skeleton on first start, so the same scripts work. Use `--grav grav` and run PHP helpers either on the host (needs PHP) or with `docker compose exec grav php ...` (paths under `/var/www/html`). For CLI commands inside the container (`bin/plugin`, `bin/grav`), run as `www-data`. Mailpit catches email at `http://127.0.0.1:8025`. Point the Email plugin at host `mailpit`, port `1025`, no encryption.

Bootstrap access by running Grav's CLI inside the container (the launcher still needs PHP on the host to read credentials; it only uses `php -r`):

```bash
<skill-dir>/scripts/bootstrap_access.sh <project> --api-url http://127.0.0.1:8080/api \
  --grav-cli "docker compose -f $D/compose.yaml --project-directory <project> exec -T -u www-data grav php"
```

## What `install_grav.sh` installs

The `grav-admin` package for the requested version (default `latest`, resolved from `https://getgrav.org/download/core/grav-admin/latest`). It includes Admin2, API, Login, Form, Email, Flex Objects, Error and Problems. The script checks PHP ≥ 8.3 and required extensions, and reports recommended ones (`intl`, `yaml`, `apcu`, `opcache`). It refuses to overwrite a non-empty `grav/`. Add plugins with `php bin/gpm install <slug> -y` (e.g. `sitemap`); prefer GPM-listed plugins over custom code.

## Accounts, API keys and the MCP launcher

- `bin/plugin login new-user ... --permissions=b --admin-type=api` grants Admin2 + site access (`api.*` permissions incl. `api.super`). The password must satisfy Grav's policy (upper, lower, digit, ≥ 8).
- `bin/plugin api keys:generate --user=<user> --name=<label> [--expiry=<days>]` prints a `grav_…` key once. `keys:list` / `keys:revoke` manage them. Grav stores **hashes** in `user/data/api-keys.yaml`, separate from `user/accounts/`. Back up or persist both, or keys stop matching.
- A key inherits exactly its user's permissions; there's no per-key scope. For least privilege, create a second user with only page/media API permissions in Admin → Accounts and issue the agent key to it.
- `bin/grav-mcp` (written by `bootstrap_access.sh`) exports `GRAV_API_URL`/`GRAV_API_KEY` from `.local/credentials.json` and runs a pinned `npx -y grav-mcp@<version>`. Client configs only reference the launcher, so rotating the key needs a reconnect, not a config edit. An explicit `GRAV_API_KEY` in the client's env overrides it.
- `grav-mcp` (official, Node ≥ 18) speaks stdio by default and exposes ~80 tools: pages, translations, media, config, users/keys, GPM, cache, logs, backups, blueprints. It validates the key against the API on start. `--transport http --port 3100` serves several clients, but **never share an admin key behind a shared HTTP endpoint**: every caller would act as that user.
- Docs: https://learn.getgrav.org/2/advanced/mcp-server and https://learn.getgrav.org/2/api

## Connecting agent clients

The launcher is a stdio server with no URL and no token in config:

| Client | Command |
| --- | --- |
| Claude Code | `.mcp.json` in the project (written for you), or `claude mcp add --scope project grav -- <project>/bin/grav-mcp` |
| Codex | `codex mcp add grav -- <project>/bin/grav-mcp`, or in `~/.codex/config.toml`: `[mcp_servers.grav]` + `command = "<project>/bin/grav-mcp"` |
| Cursor | `.cursor/mcp.json`: `{"mcpServers": {"grav": {"command": "<project>/bin/grav-mcp"}}}` |
| Others | Any MCP client: stdio, command = launcher path |

Ask before writing a user-global config file. After adding, the client must reconnect or restart. Then verify with `list_pages`. REST clients can use `<site>/api/v1/...` with the `X-API-Key` header.

## HTTPS, custom hosts and tunnels

- For a local HTTPS host (e.g. `https://acme.test`), Node needs to trust the local CA: add `NODE_EXTRA_CA_CERTS=<mkcert rootCA.pem>` to the launcher environment.
- Grav builds absolute URLs from the request host. A tunnel (Cloudflare, ngrok) that forwards the public `Host` header gets correct canonical URLs. Tunnel to the HTTPS origin if HTTP redirects to HTTPS. Add the tunnel host to `noindex_hosts`. Protect tunnels that expose Admin.
- If a Cloudflare tunnel stalls over QUIC, switch it to `protocol: http2`.
- When the web PHP worker (FPM/Apache module) is older than CLI `php`, restart the worker; updating the binary doesn't replace a running worker.

## Git and `.gitignore`

Version `grav/user` only (core and vendor are reinstallable). Suggested `grav/user/.gitignore`:

```
accounts/*.yaml
data/*
!data/.gitkeep
env/
config/security-private.php
config/plugins/api-private.php
themes/*/node_modules/
.DS_Store
```

`config/security-private.php` and `config/plugins/api-private.php` hold signing secrets: never commit them. Narrow ignore rules carefully: a broad `images/` rule also hides the theme's `images/`. Generated image derivatives live in `grav/images/` (outside `user/`).

## Production profile (if the user later deploys)

Admin2, API, Login and the MCP launcher are authoring tools. A public deployment should either not install them or deny `/admin`, `/api` and `/mcp` at the web server. It should keep forms working with shared sessions (Redis) if it runs multiple instances, warm caches per instance, and enable `system.cache.allow_webserver_gzip` (Grav otherwise disables Apache compression of dynamic HTML). A content-editing instance separate from the immutable public image works well. Pin Grav and plugin versions instead of running `gpm update` in production.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `Username does not pass the minimum requirements` | Lowercase letters, digits, `-`/`_`, 3–16 chars |
| API returns 401 | Key revoked/rotated, or wrong user; rerun `bootstrap_access.sh` (reuses or regenerates) |
| MCP client shows no tools | Client not restarted; launcher not executable; `npx` missing from the client's PATH (use an absolute node path in the launcher) |
| Changes don't show | `php bin/grav clearcache`; theme CSS cached by the browser (bump the asset URL or hard reload) |
| 500 on form submit | Read `grav/logs/grav.log`: email action without `to`, or `save` with a disallowed extension |
| Page exists on disk but 404 | Folder has no `.md` for the active language, `routable: false`, or a YAML error (`grav_config.php grav lint user`) |
