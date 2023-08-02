set -e

for DB_NAME in $(echo $DATABASES | tr ',' ' '); do
  pg_dump -d "$DB_NAME" > "/backup/${DB_NAME}_backup.sql"
done
