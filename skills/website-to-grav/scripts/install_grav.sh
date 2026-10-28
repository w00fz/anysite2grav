#!/usr/bin/env bash
# Install the latest (or a pinned) Grav core + Admin2 into <project>/grav and check PHP.
#
# Usage: install_grav.sh <project-dir> [--version latest|2.2.14] [--php php]
#
# Layout created:
#   <project>/grav/        Grav webroot (core + Admin2 + API + Login + Form + Email …)
#   <project>/migration/   crawl/extract artifacts (outside the webroot, never served)
#   <project>/.local/      credentials and runtime state (chmod 700, never commit)
set -euo pipefail

usage() { sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }
[ $# -ge 1 ] || usage 2
case "$1" in -h|--help) usage 0 ;; esac

project="$1"; shift
version="latest"
php_bin="php"
while [ $# -gt 0 ]; do
  case "$1" in
    --version) version="$2"; shift 2 ;;
    --php) php_bin="$2"; shift 2 ;;
    -h|--help) usage 0 ;;
    *) echo "unknown option: $1" >&2; usage 2 ;;
  esac
done

command -v "$php_bin" >/dev/null || { echo "PHP not found ($php_bin). Install PHP 8.3+ (macOS: brew install php)." >&2; exit 1; }
command -v unzip >/dev/null || { echo "unzip is required" >&2; exit 1; }
command -v curl >/dev/null || { echo "curl is required" >&2; exit 1; }

php_version=$("$php_bin" -r 'echo PHP_VERSION;')
"$php_bin" -r 'exit(version_compare(PHP_VERSION, "8.3.0", ">=") ? 0 : 1);' \
  || { echo "Grav 2 needs PHP 8.3+, found $php_version" >&2; exit 1; }

missing=()
for extension in curl ctype dom gd json mbstring openssl session simplexml xml zip; do
  "$php_bin" -r "exit(extension_loaded('$extension') ? 0 : 1);" || missing+=("$extension")
done
optional=()
for extension in intl yaml apcu opcache exif; do
  "$php_bin" -r "exit(extension_loaded('$extension') ? 0 : 1);" || optional+=("$extension")
done
if [ ${#missing[@]} -gt 0 ]; then
  echo "Missing required PHP extensions: ${missing[*]}" >&2
  exit 1
fi

target="$project/grav"
if [ -d "$target" ] && [ -n "$(ls -A "$target" 2>/dev/null)" ]; then
  echo "$target already exists and is not empty; refusing to overwrite." >&2
  exit 1
fi
mkdir -p "$project/migration" "$project/.local"
chmod 700 "$project/.local"

workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT
url="https://getgrav.org/download/core/grav-admin/$version"
echo "Downloading $url"
curl -fsSL --retry 3 -o "$workdir/grav-admin.zip" "$url"
unzip -q "$workdir/grav-admin.zip" -d "$workdir/unzipped"
source_dir=$(find "$workdir/unzipped" -mindepth 1 -maxdepth 1 -type d | head -1)
mkdir -p "$target"
cp -R "$source_dir"/. "$target"/
chmod +x "$target"/bin/* 2>/dev/null || true

# Admin2 depends on the API plugin; make sure both (and Form/Email/Login) are present.
cd "$target"
for plugin in api admin2 login form email; do
  if [ ! -d "user/plugins/$plugin" ]; then
    "$php_bin" bin/gpm install "$plugin" -y >/dev/null
  fi
done

installed=$("$php_bin" -r 'include "system/defines.php"; echo "Grav " . GRAV_VERSION;' 2>/dev/null || true)
plugins=$(ls user/plugins | tr '\n' ' ')
echo "Installed ${installed:-Grav} at $target (PHP $php_version)"
echo "Plugins: $plugins"
if [ ${#optional[@]} -gt 0 ]; then
  echo "Optional PHP extensions not loaded (recommended): ${optional[*]}"
fi
