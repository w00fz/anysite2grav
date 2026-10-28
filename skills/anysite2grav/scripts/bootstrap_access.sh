#!/usr/bin/env bash
# Create the local Admin2/API account, an API key, and an MCP launcher for agents.
#
# Usage: bootstrap_access.sh <project-dir> [--user site-admin] [--email admin@example.test]
#                            [--name "Site Admin"] [--api-url http://127.0.0.1:8000/api]
#                            [--server-name grav] [--rotate-key]
#                            [--grav-cli "docker compose exec -T -u www-data grav php"]
#
# --grav-cli runs Grav's CLI through another command (e.g. inside the Docker service), from
# <project>; the account check still reads the bind-mounted grav/user on the host.
#
# Idempotent: credentials are generated once into <project>/.local/credentials.json (0600)
# and reused, so connected agents keep working across restarts. --rotate-key issues a new
# key and revokes the old one; the launcher picks it up on the next connection.
#
# Writes:
#   <project>/.local/credentials.json  username, initial password, api key + id, api url
#   <project>/bin/grav-mcp             stdio launcher: reads the key at start, runs grav-mcp
#   <project>/.mcp.json                Claude Code project config pointing at the launcher
# Prints ready-to-paste config for Codex and Cursor. Never prints the API key.
set -euo pipefail

GRAV_MCP_VERSION="0.1.4"

[ $# -ge 1 ] || { sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
project="$(cd "$1" && pwd)"; shift
user="site-admin"; email="admin@example.test"; fullname="Site Admin"; api_url=""; server_name="grav"; rotate=0; grav_cli=""
while [ $# -gt 0 ]; do
  case "$1" in
    --user) user="$2"; shift 2 ;;
    --email) email="$2"; shift 2 ;;
    --name) fullname="$2"; shift 2 ;;
    --api-url) api_url="$2"; shift 2 ;;
    --server-name) server_name="$2"; shift 2 ;;
    --rotate-key) rotate=1; shift ;;
    --grav-cli) grav_cli="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

grav="$project/grav"
state="$project/.local"
credentials="$state/credentials.json"
mkdir -p "$state" "$project/bin"
chmod 700 "$state"
if [ -z "$grav_cli" ]; then
  [ -x "$grav/bin/plugin" ] || { echo "Grav not found at $grav (run install_grav.sh first)" >&2; exit 1; }
fi
grav_plugin() {
  if [ -n "$grav_cli" ]; then
    read -r -a cli_parts <<<"$grav_cli"
    (cd "$project" && "${cli_parts[@]}" bin/plugin "$@")
  else
    (cd "$grav" && php bin/plugin "$@")
  fi
}

if [ -z "$api_url" ]; then
  port=$(cat "$state/server.port" 2>/dev/null || echo 8000)
  api_url="http://127.0.0.1:$port/api"
fi

json_get() { php -r '$d=json_decode(file_get_contents($argv[1]),true); echo $d[$argv[2]] ?? "";' "$credentials" "$1"; }
json_write() {
  # json_write key value [key value ...] — merges into the credentials file atomically.
  php -r '
    array_shift($argv); $file = array_shift($argv); array_shift($argv);
    $data = is_file($file) ? json_decode(file_get_contents($file), true) : [];
    for ($i = 0; $i < count($argv); $i += 2) { $data[$argv[$i]] = $argv[$i + 1]; }
    $tmp = $file . ".tmp"; file_put_contents($tmp, json_encode($data, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES) . "\n");
    chmod($tmp, 0600); rename($tmp, $file);
  ' "$credentials" -- "$@"
}

if [ ! -f "$credentials" ]; then
  password="Aa1!$(php -r 'echo bin2hex(random_bytes(16));')"
  json_write username "$user" password "$password" api_url "$api_url"
fi
user=$(json_get username)
json_write api_url "$api_url"

if [ ! -f "$grav/user/accounts/$user.yaml" ]; then
  # Grav's CLI takes the password as an option; it is visible to local process listings only briefly.
  grav_plugin login new-user --user="$user" --password="$(json_get password)" --email="$email" \
    --permissions=b --admin-type=api --fullname="$fullname" --title="Site Administrator" \
    --state=enabled --no-interaction --no-ansi >/dev/null
  echo "Created Grav account '$user' (Admin2 + API super access)"
fi

if [ -z "$(json_get api_key)" ] || [ "$rotate" = 1 ]; then
  old_key_id=$(json_get key_id)
  output=$(grav_plugin api keys:generate --user="$user" --name="Local agent (MCP)" --no-interaction --no-ansi)
  key=$(printf '%s\n' "$output" | sed -nE 's/.*API Key:[[:space:]]*(grav_[A-Za-z0-9_-]+).*/\1/p' | head -1)
  key_id=$(printf '%s\n' "$output" | sed -nE 's/.*Key ID:[[:space:]]*([^[:space:]]+).*/\1/p' | head -1)
  [ -n "$key" ] || { echo "Grav did not return an API key" >&2; exit 1; }
  json_write api_key "$key" key_id "$key_id"
  if [ -n "$old_key_id" ] && [ "$old_key_id" != "$key_id" ]; then
    printf 'yes\n' | grav_plugin api keys:revoke --user="$user" "$old_key_id" --no-ansi >/dev/null || true
    echo "Rotated API key (old key revoked); reconnect agents."
  else
    echo "Generated API key for '$user'"
  fi
fi

launcher="$project/bin/grav-mcp"
cat >"$launcher" <<EOF
#!/usr/bin/env bash
# MCP stdio launcher for this Grav site. Reads the API key at start so client configs hold no secret.
set -euo pipefail
here="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")/.." && pwd)"
read_credential() { php -r '\$d=json_decode(file_get_contents(\$argv[1]),true); echo \$d[\$argv[2]] ?? "";' "\$here/.local/credentials.json" "\$1"; }
export GRAV_API_URL="\${GRAV_API_URL:-\$(read_credential api_url)}"
export GRAV_API_KEY="\${GRAV_API_KEY:-\$(read_credential api_key)}"
exec npx -y grav-mcp@$GRAV_MCP_VERSION "\$@"
EOF
chmod +x "$launcher"

if [ ! -f "$project/.mcp.json" ]; then
  php -r 'echo json_encode(["mcpServers" => [$argv[1] => ["command" => $argv[2], "args" => []]]], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES) . "\n";' "$server_name" "$launcher" >"$project/.mcp.json"
fi

status=$(curl -s -o /dev/null -w '%{http_code}' -H "X-API-Key: $(json_get api_key)" "$api_url/v1/pages?per_page=1" || true)
echo
echo "Admin:     ${api_url%/api}/admin   user: $user   password: in .local/credentials.json"
echo "API check: GET $api_url/v1/pages → HTTP $status$([ "$status" = 200 ] || echo '  (start the server, then re-run to verify)')"
echo
echo "MCP launcher: $launcher"
echo "  Claude Code: .mcp.json written (project scope). Or: claude mcp add --scope project $server_name -- $launcher"
echo "  Codex:       codex mcp add $server_name -- $launcher"
echo "               (or ~/.codex/config.toml →  [mcp_servers.$server_name]  command = \"$launcher\")"
echo "  Cursor:      .cursor/mcp.json → {\"mcpServers\": {\"$server_name\": {\"command\": \"$launcher\"}}}"
echo "Reconnect the agent after adding the server, then ask it to list pages."
