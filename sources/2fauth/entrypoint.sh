#!/bin/sh

set -e

echo "Running version ${VERSION} commit ${COMMIT} built on ${CREATED}"

# Show versions
echo "supervisord version: $(supervisord version)"
php-fpm81 -v | head -n 1
nginx -v

# Inject storage in /2fauth and use it with a symlink
# if [ ! -d /2fauth/storage ]; then
#   mv /srv/storage /2fauth/storage
# else
#   rm -r /srv/storage
# fi
# ln -s /2fauth/storage /srv/storage
#

mkdir -p /srv/storage/app/imagesLink /srv/storage/app/public/icons /srv/storage/app/qrcodes /srv/storage/framework/cache/data /srv/storage/framework/sessions /srv/storage/framework/testing /srv/storage/framework/views /srv/storage/logs
ln -s /srv/storage /2fauth/storage

php artisan migrate
php artisan storage:link --quiet
php artisan config:clear
php artisan config:cache

supervisord
