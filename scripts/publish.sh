#!/usr/bin/env bash
# Sync 05-Public from the vault, then commit and push so CI deploys it.
#
#   ./scripts/publish.sh          review the changes, then confirm
#   ./scripts/publish.sh --yes    skip the confirmation
set -euo pipefail

VAULT="${VAULT_PATH:-$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/obsidian-stardust}"
AUTO_YES="${1:-}"

cd "$(dirname "$0")/.."

if [ ! -d "$VAULT/05-Public" ]; then
  echo "error: $VAULT/05-Public not found. Set VAULT_PATH." >&2
  exit 1
fi

python3 scripts/sync_vault.py --vault "$VAULT"

git add content/posts static/images 2>/dev/null || git add content/posts

if git diff --cached --quiet; then
  echo
  echo "Nothing changed — site is already up to date."
  exit 0
fi

echo
echo "About to publish these changes to https://sashaqi.github.io :"
echo
git diff --cached --name-status
echo

if [ "$AUTO_YES" != "--yes" ]; then
  printf "Publish? [y/N] "
  read -r reply
  case "$reply" in
    [yY]*) ;;
    *) echo "Aborted. Changes are staged but not committed."; exit 1 ;;
  esac
fi

git commit -q -m "Publish: $(date '+%Y-%m-%d %H:%M')"
git push -q origin main
echo
echo "Pushed. CI is building — watch it with:"
echo "  gh run watch --repo sashaqi/sashaqi.github.io"
