# Setup

One-time wiring. Everything after this is automatic: write in Obsidian,
obsidian-git pushes the vault, the site rebuilds.

## How it fits together

```
Obsidian (05-Public/)
    │  obsidian-git auto-commit + push
    ▼
sashaqi/obsidian-stardust  (private)
    │  .github/workflows/publish.yml → repository_dispatch
    ▼
sashaqi/sashaqi.github.io  (public, this repo)
    │  deploy.yml: sparse-checkout vault → sync_vault.py → hugo → Pages
    ▼
https://sashaqi.github.io
```

The vault's markdown is never committed to the public repo. CI checks it out
at build time and publishes only the rendered HTML, so nothing lands in public
git history.

## 1. Authenticate gh

```bash
gh auth login
```

## 2. Create one fine-grained PAT

<https://github.com/settings/personal-access-tokens/new>

- **Repository access** → Only select repositories → pick **both**
  `obsidian-stardust` and `sashaqi.github.io`
- **Permissions** → Repository permissions → **Contents: Read and write**
  (read is what pulls the vault; write is what the dispatch API requires)
- Expiration: 1 year

Copy the token, then:

```bash
gh secret set VAULT_TOKEN --repo sashaqi/sashaqi.github.io
```

```bash
gh secret set SITE_DISPATCH_TOKEN --repo sashaqi/obsidian-stardust
```

Both prompt for the value — paste the same token into each.

## 3. Push this site to a new `main` branch

The existing Quartz site lives on branch `v5`. This leaves it untouched, so
you can roll back by switching the default branch back.

```bash
git remote add origin https://github.com/sashaqi/sashaqi.github.io.git
```

```bash
git push -u origin main
```

Then make `main` the default and point Pages at Actions:

```bash
gh api -X PATCH repos/sashaqi/sashaqi.github.io -f default_branch=main
```

```bash
gh api -X POST repos/sashaqi/sashaqi.github.io/pages -f build_type=workflow || gh api -X PUT repos/sashaqi/sashaqi.github.io/pages -f build_type=workflow
```

## 4. Add the trigger to the vault repo

```bash
mkdir -p "$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/obsidian-stardust/.github/workflows"
```

```bash
cp docs/vault-workflow-publish.yml "$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/obsidian-stardust/.github/workflows/publish.yml"
```

Commit and push it from the vault (or let obsidian-git do it).

## 5. Verify

```bash
gh workflow run "Build and deploy site" --repo sashaqi/sashaqi.github.io
```

```bash
gh run watch --repo sashaqi/sashaqi.github.io
```

---

## Writing posts

Anything in `05-Public/` publishes. The subfolder becomes the category.

There is no landing page — the site root is the post list. An `_index.md` in
`05-Public` is ignored, so you can delete
`05-Public/_index.md` from the vault if you don't want it sitting there.

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

### Wikilinks

- `[[Some Post]]` → a real link, if that note is also published
- `[[Some Post|alias]]` → linked alias
- `[[Draft Note]]` → target unpublished, so it's **unwrapped to plain text**
  rather than shipping a dead link
- `![[image.png]]` → the file is found anywhere in the vault, copied to
  `static/images/`, and rewritten as a normal image

Only attachments actually referenced by a published post get copied.

> **The one thing to watch:** `05-Public` is a publish queue, not a draft
> folder. Anything you put there goes live on the next push. Use
> `publish: false` for work in progress, or draft in `00-Inbox` and move it
> over when it's ready.

## Local preview

```bash
./scripts/dev.sh
```

## Rollback

```bash
gh api -X PATCH repos/sashaqi/sashaqi.github.io -f default_branch=v5
```
