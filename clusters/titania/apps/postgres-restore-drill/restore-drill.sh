#!/bin/bash
# Restores the dumps that the init container fetched into a throwaway Postgres
# and fails unless every database comes back with its tables and extensions.
set -euo pipefail

export PGHOST=/tmp PGUSER=postgres
BACKUP_DIR="${BACKUP_DIR:-/restore}"
PGDATA="${PGDATA_DIR:-/pgdata/data}"
DRILL_STARTED=$SECONDS

initdb -U postgres -E UTF8 --locale=en_US.UTF-8 --auth=trust -D "$PGDATA" >/dev/null
# Durability is pointless here; the server logs to disk so that statements
# containing role hashes never reach the pod log.
# pg_ctl hands these to a shell, so they must stay on one line.
SERVER_OPTS="-c listen_addresses='' -c unix_socket_directories=/tmp"
SERVER_OPTS+=" -c fsync=off -c full_page_writes=off -c synchronous_commit=off"
SERVER_OPTS+=" -c shared_buffers=512MB -c maintenance_work_mem=256MB -c max_wal_size=8GB"
pg_ctl -D "$PGDATA" -l "$PGDATA/../server.log" -w -t 120 start -o "$SERVER_OPTS" >/dev/null
trap 'pg_ctl -D "$PGDATA" -m immediate stop >/dev/null 2>&1 || true' EXIT

# Parsing with Postgres also proves metadata.json is valid JSON.
EXPECTED="$(psql -X -At -v "metadata=$(cat "$BACKUP_DIR/metadata.json")" -d postgres <<'SQL'
SELECT jsonb_array_elements_text((:'metadata'::jsonb)->'databases') ORDER BY 1;
SQL
)"
FOUND="$(find "$BACKUP_DIR/databases" -name '*.dump' -printf '%f\n' | sed 's/\.dump$//' | LC_ALL=C sort)"
if [ "$(LC_ALL=C sort <<<"$EXPECTED")" != "$FOUND" ]; then
  echo "FAIL: dumps do not match metadata.json" >&2
  diff <(LC_ALL=C sort <<<"$EXPECTED") <(echo "$FOUND") >&2 || true
  exit 1
fi

# The dump always recreates the postgres role, which initdb already made.
GLOBALS_ERRORS="$(psql -X -q -d postgres -f "$BACKUP_DIR/globals.sql" 2>&1 >/dev/null |
  grep ' ERROR: ' | grep -v 'role "postgres" already exists' || true)"
if [ -n "$GLOBALS_ERRORS" ]; then
  echo "FAIL: restoring roles" >&2
  echo "$GLOBALS_ERRORS" >&2
  exit 1
fi
echo "roles restored: $(psql -X -Atc "SELECT count(*) FROM pg_roles WHERE rolname !~ '^pg_'" -d postgres)"

FAILED=0
COUNT=0
while read -r DB; do
  COUNT=$((COUNT + 1))
  DUMP="$BACKUP_DIR/databases/$DB.dump"
  STARTED=$SECONDS

  if ! pg_restore -C -d postgres --exit-on-error -j 2 "$DUMP"; then
    echo "FAIL $DB: pg_restore" >&2
    FAILED=$((FAILED + 1))
    continue
  fi

  TOC="$(pg_restore -l "$DUMP")"
  WANT_TABLES="$(awk '$4 == "TABLE" && $5 != "DATA" && $5 != "ATTACH"' <<<"$TOC" | wc -l)"
  GOT_TABLES="$(psql -X -At -d "$DB" <<'SQL'
SELECT count(*) FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname !~ '^pg_toast'
  AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = c.oid AND d.deptype = 'e');
SQL
)"
  MISSING_EXT=""
  for EXT in $(awk '$4 == "EXTENSION" {print $6}' <<<"$TOC"); do
    if [ "$(psql -X -At -d "$DB" -c "SELECT count(*) FROM pg_extension WHERE extname = '$EXT'")" != 1 ]; then
      MISSING_EXT="$MISSING_EXT $EXT"
    fi
  done

  psql -X -q -d "$DB" -c 'ANALYZE' >/dev/null
  ROWS="$(psql -X -At -d "$DB" -c "SELECT coalesce(sum(greatest(reltuples, 0)), 0)::bigint FROM pg_class WHERE relkind = 'r' AND relnamespace NOT IN ('pg_catalog'::regnamespace, 'information_schema'::regnamespace)")"
  SIZE="$(psql -X -At -d "$DB" -c 'SELECT pg_size_pretty(pg_database_size(current_database()))')"

  if [ "$WANT_TABLES" != "$GOT_TABLES" ] || [ -n "$MISSING_EXT" ]; then
    echo "FAIL $DB: tables $GOT_TABLES of $WANT_TABLES, missing extensions:${MISSING_EXT:- none}" >&2
    FAILED=$((FAILED + 1))
    continue
  fi
  echo "ok $DB: tables=$GOT_TABLES rows~=$ROWS size=$SIZE seconds=$((SECONDS - STARTED))"
done <<<"$EXPECTED"

echo "backup taken: $(grep -o '"backup_started_at": *"[^"]*"' "$BACKUP_DIR/metadata.json" | cut -d'"' -f4)"
echo "databases: $COUNT failed: $FAILED seconds: $((SECONDS - DRILL_STARTED))"
[ "$COUNT" -gt 0 ] && [ "$FAILED" -eq 0 ]
