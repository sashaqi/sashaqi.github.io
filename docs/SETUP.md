# Setup

## How it fits together

```
Obsidian (05-Public/)
    │  ./scripts/publish.sh   — sync, review, commit, push
    ▼
sashaqi/sashaqi.github.io  (public, this repo)
    │  .github/workflows/deploy.yml — hugo build → Pages
    ▼
https://sashaqi.github.io
```

`content/posts/` is committed to this repo, so CI needs no vault access and
no secrets at all.

> **Trade-off to be aware of:** the markdown of every published post lands in
> this public repo's git history permanently. If a private note is ever synced
> by mistake, deleting the file later does **not** remove it from history —
> that needs a history rewrite. `publish: false` in a note's frontmatter is the
> main guard.

## Publishing

Write in Obsidian under `05-Public/`, then:

```bash
./scripts/publish.sh
```

It syncs the vault, shows exactly which files would change, and asks before
pushing. CI builds and deploys in about a minute.

Add `--yes` to skip the confirmation.

## Writing posts

Anything in `05-Public/` publishes. The subfolder becomes the category.

```markdown
---
title: My Post Title
date: 2026-07-31
tags:
  - machine-learning
---
```

- `title` — falls back to the filename
- `date` — falls back to file mtime
- `tags` — optional
- `summary` — optional, overrides the auto-generated excerpt
- `publish: false` — keep a note in `05-Public` without publishing it

The landing block at the top of the home page (heading, intro line, social
icons) is **not** written in Obsidian — it lives in `hugo.yaml` under
`params.homeInfoParams`, because PaperMod reads it from site config. Edit it
there. `05-Public/_index.md` is ignored and can be deleted from the vault.

### Wikilinks

- `[[Some Post]]` → a real link, if that note is also published
- `[[Some Post|alias]]` → linked alias
- `[[Draft Note]]` → target unpublished, so it's **unwrapped to plain text**
  rather than shipping a dead link
- `![[image.png]]` → the file is found anywhere in the vault, copied to
  `static/images/`, and rewritten as a normal image

Only attachments actually referenced by a published post get copied.

> `05-Public` is a publish queue, not a draft folder. Anything you put there
> goes live on the next `publish.sh`. Use `publish: false` for work in
> progress, or draft in `00-Inbox` and move it over when it's ready.

## Local preview

```bash
./scripts/dev.sh
```

Serves at <http://localhost:1313> without touching git.

## Repo notes

The repo name must stay `sashaqi.github.io` — a GitHub user page only serves
at that URL from a repo with that exact name. Renaming it takes the site
offline. The Quartz version was retired by replacing the default branch, not
by renaming.

The old Quartz site is still on branch `v5`. Roll back with:

```bash
gh api -X PATCH repos/sashaqi/sashaqi.github.io -f default_branch=v5
```

Delete it once you're happy:

```bash
git push origin --delete v5
```
