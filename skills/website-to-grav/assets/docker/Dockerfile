# Local Grav 2 + Admin2 runtime. The site's user/ folder is bind-mounted, so edits made in Admin,
# over the API/MCP or in an editor land in the project and survive rebuilds.
# Bump GRAV_VERSION deliberately; "latest" resolves at build time.
FROM php:8.5-apache-bookworm
ARG GRAV_VERSION=latest
RUN apt-get update && apt-get install -y --no-install-recommends unzip libzip-dev libpng-dev libjpeg62-turbo-dev libwebp-dev libfreetype6-dev libicu-dev libyaml-dev \
    && docker-php-ext-configure gd --with-freetype --with-jpeg --with-webp \
    && docker-php-ext-install -j"$(nproc)" gd zip intl exif \
    && pecl install apcu yaml && docker-php-ext-enable apcu yaml \
    && a2enmod rewrite headers expires deflate \
    && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL -o /tmp/grav.zip "https://getgrav.org/download/core/grav-admin/${GRAV_VERSION}" \
    && unzip -q /tmp/grav.zip -d /tmp && cp -a /tmp/grav-admin/. /var/www/html/ && rm -rf /tmp/grav.zip /tmp/grav-admin \
    && cp -a /var/www/html/user /opt/grav-user-skeleton \
    && chown -R www-data:www-data /var/www/html
RUN printf '<Directory /var/www/html>\n  AllowOverride All\n</Directory>\n' > /etc/apache2/conf-enabled/grav.conf \
    && printf 'upload_max_filesize=64M\npost_max_size=64M\nmemory_limit=512M\n' > /usr/local/etc/php/conf.d/grav.ini
COPY --chmod=755 entrypoint.sh /usr/local/bin/grav-entrypoint
ENTRYPOINT ["grav-entrypoint"]
CMD ["apache2-foreground"]
