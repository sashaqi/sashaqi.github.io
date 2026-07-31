#!/usr/bin/env python3
"""Convert the vault's 05-Public folder into Hugo content.

Only 05-Public is ever read. Nothing else in the vault is touched, so
private folders (00-Inbox, 01-Daily, 02-Notes, ...) cannot leak into a
build even by accident.

Usage:
    python3 scripts/sync_vault.py --vault /path/to/obsidian-stardust
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import shutil
import sys
import unicodedata
from pathlib import Path

import yaml

PUBLIC_DIR = "05-Public"
POSTS_OUT = Path("content/posts")
STATIC_IMG_OUT = Path("static/images")
HOME_OUT = Path("content/_index.md")

# Attachments we're willing to copy into the public site.
ASSET_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif",
    ".pdf", ".mp4", ".webm", ".mov",
}

FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)
# ![[embed]] or [[link]] or [[link|alias]] or [[link#heading]]
WIKILINK_RE = re.compile(r"(!?)\[\[([^\]\|#]+)(#[^\]\|]+)?(?:\|([^\]]+))?\]\]")


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value))
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    return re.sub(r"[-\s]+", "-", value) or "untitled"


def split_frontmatter(text: str) -> tuple[dict, str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        print(f"  ! unparseable frontmatter, treating as empty: {exc}", file=sys.stderr)
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    return meta, text[match.end():]


def is_published(meta: dict) -> bool:
    """Everything in 05-Public publishes unless it explicitly opts out."""
    if meta.get("publish") is False:
        return False
    if meta.get("draft") is True:
        return False
    return True


def coerce_date(value, fallback: Path) -> str:
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, str) and value.strip():
        cleaned = value.strip().split("T")[0].split(" ")[0]
        try:
            return dt.date.fromisoformat(cleaned).isoformat()
        except ValueError:
            pass
    mtime = dt.datetime.fromtimestamp(fallback.stat().st_mtime)
    return mtime.date().isoformat()


def as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    return [str(value)]


def collect_notes(public_root: Path) -> tuple[dict, list]:
    """Return (link index keyed by note name, list of publishable notes)."""
    index: dict[str, str] = {}
    notes: list[dict] = []

    for path in sorted(public_root.rglob("*.md")):
        if path.name.startswith("."):
            continue
        raw = path.read_text(encoding="utf-8")
        meta, body = split_frontmatter(raw)

        if path.name == "_index.md":
            notes.append({"path": path, "meta": meta, "body": body, "home": True})
            continue

        if not is_published(meta):
            print(f"  - skipped (opted out): {path.name}")
            continue

        title = str(meta.get("title") or path.stem)
        slug = slugify(meta.get("slug") or title)
        url = f"/posts/{slug}/"

        # Obsidian resolves wikilinks by note name, and by relative path.
        index[path.stem.lower()] = url
        index[title.lower()] = url
        rel = path.relative_to(public_root).with_suffix("")
        index[str(rel).lower()] = url

        notes.append({
            "path": path, "meta": meta, "body": body,
            "title": title, "slug": slug, "home": False,
            "section": rel.parts[0] if len(rel.parts) > 1 else None,
        })

    return index, notes


def collect_assets(vault_root: Path) -> dict[str, Path]:
    """Index every attachment in the vault by filename, for ![[embeds]]."""
    assets: dict[str, Path] = {}
    for path in vault_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in ASSET_SUFFIXES:
            continue
        if any(part.startswith(".") for part in path.parts):
            continue
        assets.setdefault(path.name.lower(), path)
    return assets


def convert_links(body: str, index: dict, assets: dict, copied: set, note_name: str) -> str:
    """Rewrite Obsidian wikilinks into Hugo-safe markdown."""

    def replace(match: re.Match) -> str:
        embed, target, heading, alias = match.groups()
        target = target.strip()
        # Obsidian displays only the note name for path-style links.
        label = (alias or target.split("/")[-1]).strip()

        if embed:
            asset = assets.get(target.lower())
            if asset:
                dest = STATIC_IMG_OUT / asset.name
                if asset.name.lower() not in copied:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(asset, dest)
                    copied.add(asset.name.lower())
                return f"![{label}](/images/{asset.name})"
            # An embedded note (transclusion) — Hugo has no equivalent.
            url = index.get(target.lower())
            if url:
                return f"[{label}]({url})"
            print(f"  ! missing embed in {note_name}: {target}")
            return label

        url = index.get(target.lower())
        if url:
            anchor = f"#{slugify(heading[1:])}" if heading else ""
            return f"[{label}]({url}{anchor})"

        # Points at an unpublished note — unwrap so no dead link ships.
        return label

    return WIKILINK_RE.sub(replace, body)


def write_post(note: dict, body: str) -> None:
    meta = note["meta"]
    front = {
        "title": note["title"],
        "date": coerce_date(meta.get("date") or meta.get("created"), note["path"]),
        "draft": False,
    }
    tags = as_list(meta.get("tags"))
    if tags:
        front["tags"] = tags
    categories = as_list(meta.get("categories")) or ([note["section"]] if note["section"] else [])
    if categories:
        front["categories"] = categories
    for key in ("summary", "description", "cover", "weight", "aliases", "math"):
        if meta.get(key) is not None:
            front[key] = meta[key]

    POSTS_OUT.mkdir(parents=True, exist_ok=True)
    out = POSTS_OUT / f"{note['slug']}.md"
    rendered = yaml.safe_dump(front, sort_keys=False, allow_unicode=True).strip()
    out.write_text(f"---\n{rendered}\n---\n\n{body.strip()}\n", encoding="utf-8")
    print(f"  + {out}  ({front['date']})")


def write_home(note: dict, body: str) -> None:
    meta = note["meta"]
    front = {"title": meta.get("title", "Home")}
    HOME_OUT.parent.mkdir(parents=True, exist_ok=True)
    rendered = yaml.safe_dump(front, sort_keys=False, allow_unicode=True).strip()
    HOME_OUT.write_text(f"---\n{rendered}\n---\n\n{body.strip()}\n", encoding="utf-8")
    print(f"  + {HOME_OUT} (home)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", required=True, type=Path, help="path to the vault root")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    vault = args.vault.expanduser().resolve()
    public_root = vault / PUBLIC_DIR
    if not public_root.is_dir():
        print(f"error: {public_root} not found", file=sys.stderr)
        return 1

    print(f"Reading {public_root}")
    index, notes = collect_notes(public_root)
    assets = collect_assets(vault)
    print(f"Found {len([n for n in notes if not n['home']])} publishable notes, "
          f"{len(assets)} candidate attachments")

    if args.dry_run:
        for note in notes:
            if not note["home"]:
                print(f"  would write content/posts/{note['slug']}.md")
        return 0

    # Regenerate from scratch so deletions in the vault propagate.
    if POSTS_OUT.exists():
        shutil.rmtree(POSTS_OUT)
    if STATIC_IMG_OUT.exists():
        shutil.rmtree(STATIC_IMG_OUT)

    copied: set[str] = set()
    for note in notes:
        name = note["path"].name
        body = convert_links(note["body"], index, assets, copied, name)
        if note["home"]:
            write_home(note, body)
        else:
            write_post(note, body)

    print(f"Done. {len(copied)} attachment(s) copied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
