#!/bin/sh
# ежедневный бэкап баз всех ботов из /opt/bots/*/data, храним 14 дней
set -e
dest=/opt/backups/$(date +%F)
mkdir -p "$dest"
for db in /opt/bots/*/data/*.db; do
  [ -f "$db" ] || continue
  bot=$(basename "$(dirname "$(dirname "$db")")")
  sqlite3 "$db" ".backup $dest/$bot-$(basename "$db")"
done
find /opt/backups -mindepth 1 -maxdepth 1 -type d -mtime +14 -exec rm -rf {} +
