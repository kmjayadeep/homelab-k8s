set -e

for DB_NAME in $(echo $DATABASES | tr ',' ' '); do
  pg_dump -c -d "$DB_NAME" -F tar -f "/backup/${DB_NAME}_backup.sql"
done
