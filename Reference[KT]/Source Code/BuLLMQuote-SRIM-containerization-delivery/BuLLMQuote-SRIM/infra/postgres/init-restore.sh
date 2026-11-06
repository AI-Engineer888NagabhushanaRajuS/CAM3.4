#!/bin/sh
# Runs automatically on this container's FIRST startup only (Postgres's own
# docker-entrypoint-initdb.d convention -- only fires against a fresh, empty
# data volume, never re-runs against an already-initialized one).
#
# Restores the one-time pg_dump seed of Centum's 4 databases
# (database/pg_dump_seed/*.dump + globals.sql, produced by the exact commands
# in docs/ this session -- see the chat history around the "You run the dump
# yourself" decision). If those files don't exist yet (dump not taken yet),
# this is a no-op -- the container still starts, just empty, rather than
# crash-looping.
set -e

SEED_DIR="/docker-entrypoint-initdb.d/seed"

if [ ! -d "$SEED_DIR" ] || [ -z "$(ls -A "$SEED_DIR" 2>/dev/null)" ]; then
    echo "[init-restore] No seed files found in $SEED_DIR -- starting with an empty database. Run the pg_dump commands, drop the output into database/pg_dump_seed/, and recreate this container's volume to seed it."
    exit 0
fi

if [ -f "$SEED_DIR/globals.sql" ]; then
    echo "[init-restore] Restoring roles from globals.sql"
    psql -v ON_ERROR_STOP=0 -U "$POSTGRES_USER" -f "$SEED_DIR/globals.sql"
fi

for db in logic_db_2 file_metadata_db_2 cognee_memory_db srim; do
    dumpfile="$SEED_DIR/$db.dump"
    if [ -f "$dumpfile" ]; then
        echo "[init-restore] Creating and restoring $db"
        psql -U "$POSTGRES_USER" -c "CREATE DATABASE \"$db\";"
        pg_restore -U "$POSTGRES_USER" -d "$db" --no-owner --role="$POSTGRES_USER" "$dumpfile"
    else
        echo "[init-restore] WARNING: $dumpfile not found, skipping $db"
    fi
done

echo "[init-restore] Done. Verify with: docker compose exec postgres psql -U centum -l"
