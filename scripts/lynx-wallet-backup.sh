#!/bin/bash
#
# Lynx wallet backup script.
# Runs via systemd timer every 6 hours, or manually.
# Backup dir: /var/lib/{chain-name}-backup/ (e.g. /var/lib/lynx-backup/)
# Filename format: YYYY-MM-DD-HH-MM-SS-lynx.dat
# Deduplicates by hash; prunes backups older than 90 days.
#
set -euo pipefail

WORKING_DIR="${LYNX_WORKING_DIR:-/var/lib/lynx}"
CHAIN_ID="${LYNX_CHAIN_ID:-lynx}"
BACKUP_DIR="/var/lib/${CHAIN_ID}-backup"
RPC_CLI="${LYNX_RPC_CLI:-/usr/local/bin/lynx-cli}"
LAST_HASH_FILE="${BACKUP_DIR}/.last-hash"
RETENTION_DAYS=90

mkdir -p "$BACKUP_DIR"

if [ ! -x "$RPC_CLI" ]; then
  echo "lynx-cli not found or not executable" >&2
  exit 1
fi

# Generate dated filename: YYYY-MM-DD-HH-MM-SS-lynx.dat
TIMESTAMP=$(date -u +"%Y-%m-%d-%H-%M-%S")
BACKUP_FILE="${BACKUP_DIR}/${TIMESTAMP}-${CHAIN_ID}.dat"

# Run backupwallet RPC
if ! "$RPC_CLI" -datadir="$WORKING_DIR" backupwallet "$BACKUP_FILE" 2>/dev/null; then
  echo "backupwallet failed" >&2
  exit 1
fi

# Hash the new backup and compare to previous
NEW_HASH=$(sha256sum "$BACKUP_FILE" | cut -d' ' -f1)
if [ -f "$LAST_HASH_FILE" ]; then
  OLD_HASH=$(cat "$LAST_HASH_FILE")
  if [ "$NEW_HASH" = "$OLD_HASH" ]; then
    rm -f "$BACKUP_FILE"
    exit 0
  fi
fi
echo "$NEW_HASH" > "$LAST_HASH_FILE"

# Prune backups older than 90 days
find "$BACKUP_DIR" -maxdepth 1 -name "*.dat" -mtime +$RETENTION_DAYS -delete 2>/dev/null || true

exit 0
