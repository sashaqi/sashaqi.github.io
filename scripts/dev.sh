#!/usr/bin/env bash
# Sync the vault and run Hugo locally at http://localhost:1313
set -euo pipefail

VAULT="${VAULT_PATH:-$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/obsidian-stardust}"

cd "$(dirname "$0")/.."
python3 scripts/sync_vault.py --vault "$VAULT"
exec hugo server --buildDrafts --port 1313
