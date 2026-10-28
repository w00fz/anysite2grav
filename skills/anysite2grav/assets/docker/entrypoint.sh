#!/bin/sh
# Seed an empty bind-mounted user/ with Grav's skeleton (plugins, config) on first start.
set -e
if [ ! -d /var/www/html/user/plugins/admin2 ]; then
  cp -an /opt/grav-user-skeleton/. /var/www/html/user/
fi
# Match file ownership to the host user so edits stay editable on both sides.
if [ -n "$LOCAL_UID" ]; then
  usermod -o -u "$LOCAL_UID" www-data >/dev/null 2>&1 || true
  groupmod -o -g "${LOCAL_GID:-$LOCAL_UID}" www-data >/dev/null 2>&1 || true
fi
chown -R www-data:www-data /var/www/html/user /var/www/html/assets /var/www/html/cache /var/www/html/logs /var/www/html/images /var/www/html/tmp /var/www/html/backup 2>/dev/null || true
exec docker-php-entrypoint "$@"
