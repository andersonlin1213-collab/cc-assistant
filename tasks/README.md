# Your vault lives here

cc-assistant treats this `tasks/` directory as an Obsidian vault. Everything
inside it — your task cards, project cards, conversation history, decision
logs — is **your private data**, not something this repo wants to ship.

## Two ways to use it

### Option A: keep your vault inside this repo (simple, single-machine)

Just open `tasks/` in Obsidian and start writing markdown files into
`todo/`. The daemon will pick them up. Don't commit your real cards to the
public `cc-assistant` repo — the recommended `.gitignore` already excludes
`tasks/_attachments/`, but everything else under `tasks/` would still be
tracked. Either keep your fork private, or use Option B.

### Option B: keep your vault in a separate (private) repo (recommended)

This is what the upstream maintainer does. Move (or create) your vault at a
sibling path and point the daemon at it via `.env`:

```bash
# .env
TASKS_DIR=../my-vault
```

Then your layout looks like:

```
projects/
  cc-assistant/        # this repo — public, just the daemon
  my-vault/            # your private vault — your tasks, your cards
```

The skeleton in this `tasks/` directory (`templates/`, `projects/EXAMPLE.md`,
the empty status folders) is just here so the daemon has something to look at
out of the box, and so new users can see the expected layout.

## What goes where

| Folder | What lives here |
| --- | --- |
| `todo/` | Tasks waiting to be picked up |
| `doing/` | Tasks the daemon is currently driving |
| `done/<YYYY-MM>/` | Completed tasks, grouped by month |
| `blocked/` | Tasks halted by `mark_blocked` |
| `review/` | Tasks waiting for human approval |
| `backlog/` | Long-term ideas (daemon won't touch) |
| `projects/` | Per-project context cards |
| `templates/` | Task and project card templates |

## Templates

- `templates/default.md` — minimal task card
- `templates/full.md` — task card with all optional frontmatter
- `templates/project.md` — project card

## A note on Obsidian setup

When you first open this folder in Obsidian, it'll create `.obsidian/` with
your workspace state. The committed `.gitignore` excludes the volatile bits
(`workspace.json`, plugin binaries, cache) but tracks vault-level settings
that are worth sharing — adjust to taste.
