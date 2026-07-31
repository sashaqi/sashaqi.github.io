#!/usr/bin/env bash
# Sync the vault and run Hugo locally at http://localhost:1313
set -euo pipefail

VAULT="${VAULT_PATH:-$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/obsidian-stardust}"

cd "$(dirname "$0")/.."

# A public/ left behind by `hugo --minify` holds production HTML whose links
# are absolute (https://sashaqi.github.io/...). The dev server will serve
# those files, so clicking a post navigates to the live site instead of
# localhost. Clear it before starting.
rm -rf public resources

python3 scripts/sync_vault.py --vault "$VAULT"
exec hugo server --buildDrafts --port 1313
