# cc-assistant

> Check a box in Obsidian, get a Claude Code agent on the job — across all your repos.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)
[![Status: beta](https://img.shields.io/badge/status-beta-orange.svg)](#)

[中文版 README](./README.zh-CN.md)

A local file-first task daemon that uses an Obsidian vault as its UI. Drop a
markdown file into `tasks/todo/`, or check a `- [ ]` under any project card,
and a Claude agent picks it up, drives the conversation, and moves the file
through `doing/` → `done/` (or `review/` / `blocked/`).

No database. No MCP server. No web app. Just a Python daemon, your vault, and
your existing Claude Code install.

<!-- demo gif placeholder
![demo](docs/demo.gif)
-->

---

## Why another Claude + Obsidian agent?

Most Obsidian + Claude projects are **plugins** (you open Obsidian, type into a
sidebar). cc-assistant is the opposite: a **headless daemon** that watches the
vault as files and never needs Obsidian to be running.

Three things you won't find in the other major projects in this space:

| | cc-assistant | Typical "Obsidian + Claude" |
|---|---|---|
| **Burns Max subscription, not API tokens** | ✅ `claude_cli` provider by default — drives your local `claude` CLI so cost = $0 per task | ❌ API-only, every task costs tokens |
| **Per-task provider routing** | ✅ Tag a task `db,mysql,api` → auto-escalate to API (where custom tools work). Anything else stays on the free CLI provider. | ❌ One provider, one bill |
| **Check a `- [ ]` → spawn a job in another repo** | ✅ `projects/<slug>.md` cards point at sibling repos via `repo_path:`. Check a checkbox under `## 下一步` and a task is dispatched against that repo. | ❌ Single-vault scope |
| **Zero infrastructure** | ✅ `pip install -e .` + your existing Claude CLI. That's it. | ❌ MCP servers, Postgres+pgvector, OAuth apps, webhooks |

If you want a heavy "personal AI OS" with semantic memory and a dashboard, look
at [work-buddy](https://github.com/KadenMc/work-buddy). If you want Obsidian as
a tracker of Linear issues, look at
[ai-agent-workflow](https://github.com/Jason-Cyr/ai-agent-workflow). If you
want the smallest possible daemon that lets you queue work from your phone and
let Claude grind through it overnight, you're in the right place.

---

## Quick start

```bash
# 1. Install
git clone https://github.com/<your-user>/cc-assistant.git
cd cc-assistant
pip install -e .

# 2. Configure
cp .env.example .env
# Minimum: LLM_PROVIDER=claude_cli (default — uses your Claude Max subscription
# via the local `claude` CLI, no API key required).
# Add ANTHROPIC_API_KEY only if you want tag-based escalation to the API.

# 3. Dry-run on one task to check wiring
cc-assistant run --dry-run --target tasks/todo/foo.md

# 4. Start the daemon
cc-assistant run            # foreground
# or
scripts\run-daemon.bat      # Windows background helper

# 5. Status / stop
cc-assistant status
cc-assistant stop
```

**Prerequisites:** Python 3.11+, an Obsidian install (any platform), and
either the `claude` CLI (recommended) or an `ANTHROPIC_API_KEY`.

---

## How it works

1. Open the `tasks/` folder as an Obsidian vault. Sync it (Obsidian Sync, iCloud, Syncthing — your choice) to your phone.
2. From anywhere, create a file under `tasks/todo/`. The filename is the task title; no frontmatter required — the daemon auto-fills `id`, `created`, `updated`.
3. A file watcher on the daemon side picks it up, moves it to `tasks/doing/`, and drives a Claude conversation. Each AI reply is appended to the file. A placeholder line lets you continue the loop by overwriting it in Obsidian and saving.
4. Tools the AI can call: `mark_complete`, `mark_blocked`, plus the custom tool registry in `src/tools/` (filesystem, shell, web fetch, MySQL, API caller, notifier).

### Provider routing (the cost-control story)

Two LLM providers coexist; `LLMRouter` picks one per task:

- **`claude_cli`** *(default)* — drives the local `claude` CLI as a subprocess. Burns your Claude.ai Max subscription. **Cost: $0 per task.** Tradeoff: the CLI runs its own native tools, so cc-assistant's custom tools are unreachable from this provider.
- **`claude`** — Anthropic SDK with `ANTHROPIC_API_KEY`. Pay per token, but the full custom tool set (MySQL / WeCom / DingTalk / api_caller / web_fetch) works.

Routing precedence:

1. Explicit `provider:` in task frontmatter (`claude` or `claude_cli`)
2. Tag-based escalation: any tag listed in `ESCALATE_TAGS` (default `db,mysql,wecom,dingtalk,api`) forces API
3. Config default (`LLM_PROVIDER`)

If the resolved provider isn't configured, the daemon logs `provider_unavailable` and skips the cycle — it never silently falls back.

### Project cards (the multi-repo story)

Beyond per-task files, `tasks/projects/<slug>.md` holds per-project context
(what / why / next actions / decision log). Each card declares the repo it
points at:

```yaml
---
type: project
slug: "my-side-project"
status: active            # or paused / archived
repo_path: "../my-side-project"   # relative to projects/ subdir
priority: P1
tags: []
last_touched: 2026-05-17
---
```

Two signals the daemon reacts to:

- `status: paused` / `archived` blocks **new** tasks for that project (in-flight ones continue).
- Checking a `- [ ]` under the card's `## 下一步 (Next actions)` section **spawns a corresponding task** in `tasks/todo/` and rewrites the line with a wikilink. This is the "check a box, get an agent" UX.

See `tasks/projects/cc-assitant.md` for the dogfood example.

---

## Architecture

```
src/
  agent/          # Orchestrator + LLM clients + ToolBridge
    llm/          # ClaudeClient, ClaudeCLIClient, LLMRouter
  board/          # Parser, writer, manager, project_handler
  dispatcher/     # File watcher + scheduler
  rules/          # Skill / rules loader
  tools/          # FileOps, Shell, WebFetch, Database, Notifier, ApiCaller
  cli.py          # `cc-assistant` entrypoint
  config.py       # pydantic-settings loaded from .env
tasks/            # The Obsidian vault — all board state lives here
  todo/ doing/ done/<YYYY-MM>/ blocked/ review/ backlog/
  projects/       # Project cards
logs/             # Per-task JSONL + agent.jsonl system log
tests/            # pytest suite
```

---

## Configuration

All values read from `.env` via `pydantic-settings`. See `src/config.py` for
the full schema. Most-used:

| Var | Default | Purpose |
| --- | --- | --- |
| `LLM_PROVIDER` | `claude_cli` | `claude` or `claude_cli` (per-task override via `provider:` frontmatter) |
| `ANTHROPIC_API_KEY` | `""` | Required only if any path uses the API client |
| `ESCALATE_TAGS` | `db,mysql,wecom,dingtalk,api` | CSV of tags that force API routing |
| `TASKS_DIR` | `tasks` | Vault root |
| `LOGS_DIR` | `logs` | JSONL log destination |
| `POLL_INTERVAL_MINUTES` | `30` | Watcher-miss safety net |
| `DEBOUNCE_SECONDS` | `15` | Min idle time after a file save before firing a cycle. Tuned for Obsidian Sync from mobile uploading partial states mid-typing — lower it for desktop-only use. |
| `OBSIDIAN_CHECK_PROCESS` | `false` | Warn at startup if Obsidian desktop isn't running |

---

## Testing

```bash
pytest             # full suite (~25s)
pytest -q tests/test_orchestrator.py
```

The one skipped test (`test_llm_claude_real`) requires a real API key.

---

## Advanced setup

<details>
<summary><b>Run as a Windows Scheduled Task (survives reboot/logout)</b></summary>

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-task-scheduler.ps1
Start-ScheduledTask -TaskName "cc-assistant"
```

Status / removal:

```powershell
Get-ScheduledTask -TaskName cc-assistant | Get-ScheduledTaskInfo
scripts\uninstall-task-scheduler.ps1
```

</details>

<details>
<summary><b>Running behind a proxy (e.g. mainland China / GFW)</b></summary>

If `api.anthropic.com` isn't reachable directly from your machine, the
`claude` CLI fails with `403 Request not allowed`. Setting `HTTP_PROXY` /
`HTTPS_PROXY` in your shell rc file (e.g. `~/.bashrc`) is **not enough** —
the daemon runs under Windows Task Scheduler / `cmd.exe`, which doesn't
source `.bashrc`, so the subprocess that spawns `claude` won't see your
proxy.

The fix: put proxy values into Windows User-level environment variables so
any user-launched process — including the Scheduled Task daemon — inherits
them:

```powershell
# Run once in PowerShell. Replace 127.0.0.1:10808 with your local proxy.
[Environment]::SetEnvironmentVariable("HTTP_PROXY",  "http://127.0.0.1:10808", "User")
[Environment]::SetEnvironmentVariable("HTTPS_PROXY", "http://127.0.0.1:10808", "User")
[Environment]::SetEnvironmentVariable("NO_PROXY",    "localhost,127.0.0.1,10.*,100.*,192.168.*,*.local", "User")

# Restart the daemon so it picks up the new env:
Stop-ScheduledTask -TaskName "cc-assistant"
Start-ScheduledTask -TaskName "cc-assistant"
```

**Symptom without this:** `logs/{id}.jsonl` fills with `cycle_error` entries
containing `api_error_status:403`. `claude auth status` shows `loggedIn: true`,
so it looks like an auth bug — it's actually network reach.

**Quick confirmation:** run the CLI yourself in a clean shell. If both
`claude auth status` and a direct call work in your terminal but the daemon's
`cycle_error` reports 403, you're hitting this.

</details>

---

## Contributing

PRs welcome. Before opening one:

- `pytest` should pass (the one skipped real-API test is fine to leave skipped).
- Keep changes focused — one feature / fix per PR.
- Design docs for shipped features live under `docs/superpowers/specs/` and
  `docs/superpowers/plans/`. Add a new dated spec when introducing a
  substantial subsystem.

---

## License

[MIT](./LICENSE) © Anderson Lin
