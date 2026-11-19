#!/bin/sh
# Nightly backup of the database + uploaded files + encryption key.
# Run from the deploy/ folder. Add to cron:  0 3 * * * cd /opt/smallbiz-finance-agent/deploy && ./backup.sh
set -eu
DEST="${BACKUP_DIR:-$HOME/backups}"
STAMP="$(date +%Y-%m-%d)"
mkdir -p "$DEST"
C="docker compose -f docker-compose.prod.yml --env-file prod.env"

$C exec -T db pg_dump -U finagent -Fc finagent > "$DEST/db-$STAMP.dump"
$C exec -T api tar czf - -C /app data > "$DEST/files-$STAMP.tar.gz"
cp prod.env "$DEST/prod.env-$STAMP"

# keep 14 days
find "$DEST" -type f -mtime +14 -delete
echo "Backup written to $DEST"
