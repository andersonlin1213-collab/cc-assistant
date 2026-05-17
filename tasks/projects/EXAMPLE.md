---
type: project
slug: "my-side-project"
status: active
repo_path: "../my-side-project"
priority: P1
tags: []
last_touched: 2026-05-17
---

# my-side-project

## 一句話

A one-line description of what this project is.

## 現在的焦點

What you're working on right now. The daemon reads this to give Claude
context when dispatching tasks against this project.

## 下一步 (Next actions)

- [ ] Check a box here, save the file, and the daemon will spawn a task in `tasks/todo/` with a wikilink back to this card.
- [ ] Each unchecked item is a candidate task. The daemon only spawns when you flip `[ ]` to `[x]`.
- [x] Already-spawned items show up checked, with the wikilink prefix `[[stem]] `.

## 決策記錄

- 2026-05-17 Created from EXAMPLE template. Replace this file with real
  project cards (one per repo you want the daemon to drive against).

## 待解決的問題

Open follow-ups, known bugs, or constraints. The daemon will surface these
when relevant.

## 回顧 / 暫停原因

If `status: paused` or `archived`, explain why here. The daemon will refuse
to spawn new tasks for paused/archived projects but won't kill in-flight
ones.
