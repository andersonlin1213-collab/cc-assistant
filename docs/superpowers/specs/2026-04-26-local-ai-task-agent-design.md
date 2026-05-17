# Local AI Task Automation Agent - Design Spec

## Overview

A locally-running, background AI Agent system that collaborates with the user asynchronously through a Markdown-based task board. The Agent can decompose tasks, execute them autonomously, and pause for human input when explicitly required. A lightweight mobile Web UI provides remote access to task status and interaction.

**Inspired by:**
- [cboxdk/delegate](https://github.com/cboxdk/delegate) — kanban-driven task delegation, one-task-per-file, Completion Promise Pattern, status columns including explicit `review`.
- The user's reference video describing a five-layer architecture with skills-based behavior rules.

## Architecture: Five-Layer Model

```
┌──────────────────────────────────────────────────────┐
│                    Local Machine (Windows)            │
│                                                      │
│  ┌─────────────┐    ┌──────────────────────────────┐ │
│  │ task files   │◄──►│  Agent Process (asyncio)      │ │
│  │ tasks/       │    │  ├─ Orchestrator              │ │
│  │  backlog/    │    │  ├─ Tools (7 tools)           │ │
│  │  todo/       │    │  ├─ File Watcher (watchdog)   │ │
│  │  doing/      │    │  ├─ Scheduler (APScheduler)   │ │
│  │  blocked/    │    │  ├─ Rules Loader (skills/)    │ │
│  │  review/     │    │  └─ LLM Client (pluggable)    │ │
│  │  done/       │    └──────────────┬───────────────┘ │
│  └──────┬───────┘                   │ git sync        │
│         │                           │                 │
└─────────┼───────────────────────────┼─────────────────┘
          │                           │
          ▼                           ▼
┌─────────────────────────────────────────────────────┐
│           Remote Server <your-server>                │
│  ┌──────────────┐    ┌────────────────────────────┐ │
│  │ task files   │◄──►│ Web API (FastAPI)           │ │
│  │ (git sync)   │    │  ├─ REST endpoints          │ │
│  │              │    │  └─ Mobile Web UI            │ │
│  └──────────────┘    └────────────────────────────┘ │
│                              ▲                      │
└──────────────────────────────┼──────────────────────┘
                               │
                          ┌────┴────┐
                          │  Mobile  │
                          │ Browser  │
                          └─────────┘
```

**Core data flow:**
1. User creates/edits task file locally → watchdog detects change → wakes Orchestrator
2. Orchestrator reads task + `skills/rules.md` → calls LLM with **fresh context** (Completion Promise Pattern) → calls Tools to execute → writes results back to task file
3. Local task files auto-sync to remote via Git (commit + push)
4. Remote Web API reads Git repo task files → renders for mobile, grouped by `project`
5. Mobile edits → Web API writes file → git push → local git pull → watchdog triggers again

## Layer 1: Task Board Layer

### Directory Structure

```
tasks/
├── backlog/             # Ideas / not yet ready for AI pickup
├── todo/                # Ready, AI may pick up
├── doing/               # AI in progress
├── blocked/             # AI mid-task, waiting for human input
├── review/              # AI completed, awaiting human approval
├── done/                # Approved, archived
│   └── 2026-04/         # Monthly archive
└── templates/
    └── default.md
```

**Status semantics (six columns, kanban-style):**

| Column | Meaning | Who moves it |
|--------|---------|--------------|
| `backlog/` | Idea captured, not ready to work | Human |
| `todo/` | Ready, AI may pick up | Human |
| `doing/` | AI actively working | AI |
| `blocked/` | AI started, needs human input to continue | AI |
| `review/` | AI finished, awaiting human sign-off | AI |
| `done/` | Human approved, archived monthly | Human (or AI if `auto_approve: true`) |

`blocked` and `review` are distinct:
- `blocked` = mid-task, AI is stuck without human input.
- `review` = post-task, AI thinks it's done; human decides "approve → done" or "reject → todo with feedback".

### Task File Format

Filename: `{id}-{slug}.md` (e.g., `025-portfolio-website.md`)

```markdown
---
id: "025"
title: 个人 portfolio 网站
project: portfolio-website        # business line / project grouping
parent: null                      # parent task id, or null for top-level
priority: P1
tags: [frontend, design]
created: 2026-04-26 14:00
updated: 2026-04-26 15:31
auto_approve: true
depends_on: []
instructions: |                   # task-level agent guidance, overrides skills/rules.md for this task only
  请优先使用 Tailwind CSS。设计语言保持极简。
subtasks:
  - id: "025-1"
    title: 设计语言风格选型
    status: blocked
    blocking_reason: 需要用户从方案 A/B/C 中选择
  - id: "025-2"
    title: 实现首页布局
    status: doing
---

## 任务描述
做一个个人作品集网站，三端（移动 / 平板 / 桌面）布局同步完成。

## 对话

### [Human] 2026-04-26 14:00
帮我做一个个人 portfolio 网站。

### [AI] 2026-04-26 14:02
收到。我需要先确认设计语言。我准备了三种方案：
- A. 极简黑白
- B. 渐变彩色
- C. 复古印刷风
请你选一个，再继续。

### [Human] 2026-04-26 15:30
选 A。

## 执行日志
> 详细日志见 logs/025-portfolio-website.jsonl
```

**Key design decisions:**
- YAML frontmatter for structured metadata, easy for programmatic parsing.
- `project` field groups tasks by business line for mobile UI grouping and reporting.
- `parent` enables two-level task decomposition: complex subtasks split into independent files referencing the parent, instead of deep YAML nesting.
- `instructions` is a task-level agent prompt that supplements `skills/rules.md`.
- `subtasks` stay one level deep in frontmatter; `blocking_reason` records why a particular subtask is blocked.
- `auto_approve: true` is the default (bold mode); when false, AI moves the task to `review/` after completion instead of `done/`.
- `depends_on` supports inter-task ordering (parallel/serial scheduling).
- Conversation section is the primary human-AI interaction area, with `### [Role] timestamp` headers.
- Detailed execution logs stored separately in JSONL files to prevent task file bloat.
- Completed tasks archived monthly under `done/YYYY-MM/`.

## Layer 2: Dispatcher / Trigger Layer

### Dual Trigger Mechanism

**Mechanism A — Event-driven (primary):**
- `watchdog` library monitors all six `tasks/*` directories for file changes.
- Debounce: 2-second window to merge rapid consecutive saves.
- Self-modification detection: internal flag set before Agent writes, cleared after, to prevent infinite loops.
- On human edit detected → wake Orchestrator.

**Mechanism B — Scheduled polling (fallback):**
- APScheduler runs every 30 minutes.
- Scans all task directories for missed events or long-running task progress checks.
- Also handles watchdog edge cases on Windows.

### Git Sync

- After each task file write: `git add . && git commit -m "agent: {summary}" && git push`.
- Local git pull every 5 minutes to fetch mobile edits.
- Conflict resolution: merge by latest timestamp in conversation entries; if irreconcilable, keep both and mark conflict.

### Remote Sync Trigger

Mobile edit → Web API writes file → git push → local git pull (5-min cycle) → watchdog detects change → Agent wakes.

## Layer 3: Execution Layer

### Orchestrator (Main Agent)

Responsibilities:
1. Detect changed task files.
2. Parse frontmatter + conversation section.
3. Load `skills/rules.md` and merge with task `instructions`.
4. Build a **fresh** LLM context (Completion Promise Pattern — see below).
5. Call LLM to decide next action.
6. Dispatch to appropriate Tool.
7. Write results back to task file conversation area.
8. Update subtask statuses.
9. Move task file according to outcome:
   - Subtasks all done + `auto_approve: true` → `done/YYYY-MM/`
   - Subtasks all done + `auto_approve: false` → `review/`
   - Mid-task, needs human input → `blocked/`
   - Otherwise stays in `doing/`

The Orchestrator does not execute work itself — it only makes decisions and delegates to Tools.

### Completion Promise Pattern

Borrowed from cboxdk/delegate. Key principle: **each task processing cycle uses a fresh LLM context**.

- Orchestrator does NOT keep long-running LLM conversation state across cycles.
- Each cycle reconstructs the prompt from: `skills/rules.md` + task file (frontmatter + description + full conversation history) + task-level `instructions`.
- After processing one logical step, Agent writes results to task file and the cycle ends.
- The next cycle (triggered by watchdog or scheduler) reconstructs context from the updated file.

Benefits:
- No context pollution between tasks.
- Predictable token usage per cycle.
- Failures can be retried without corrupting other in-flight tasks.
- Mobile edits visible in next cycle automatically (file is the single source of truth).

### LLM Client (Pluggable)

```python
class LLMClient(ABC):
    async def chat(self, messages, tools) -> LLMResponse
    async def chat_with_tools(self, messages, tools) -> LLMResponse

class ClaudeClient(LLMClient)    # Anthropic API
class OpenAIClient(LLMClient)    # OpenAI API
class OllamaClient(LLMClient)    # Local Ollama
```

Switched via `LLM_PROVIDER` in `.env`. No code changes needed.

### Tools (7 Workers)

All tools inherit from a common base class:

```python
class Tool(ABC):
    name: str              # Tool name, registered with LLM
    description: str       # Description for LLM to decide when to call
    parameters: dict       # JSON Schema parameter definition
    risk_level: str        # "low" | "high" (used by routing rules)

    async def execute(self, dry_run: bool = False, **params) -> ToolResult
```

Every tool supports `dry_run` mode: when true, write/destructive operations are stubbed and return a description of what *would* happen.

| Tool | Purpose | Execution Mode |
|------|---------|---------------|
| `file_ops` | Local file read/write/delete | async |
| `shell` | Execute shell commands | ThreadPoolExecutor |
| `web_search` | Internet search, fetch web content | async (httpx) |
| `code_edit` | Read and modify project code | async |
| `database` | MySQL queries and operations | ThreadPoolExecutor (aiomysql) |
| `notifier` | WeChat notifications via enterprise bot webhook | async |
| `api_caller` | Third-party REST API calls | async (httpx) |

Tools are auto-discovered and registered at Orchestrator startup.

### Concurrency Model

Single-process asyncio + ThreadPoolExecutor hybrid:
- I/O tasks (API calls, web search, file ops): `async/await`.
- Blocking tasks (shell commands, database): `ThreadPoolExecutor`.
- Multiple independent tasks: `asyncio.gather`.
- Check `depends_on` before executing each task.

## Layer 4: Business Logic & System Rules

### `skills/rules.md` (Human-Editable Rule File)

A standalone Markdown file at `skills/rules.md`, loaded fresh on every Orchestrator cycle and prepended to the LLM context. The user can edit this file at any time without restarting the Agent.

**Skeleton:**

```markdown
# Agent 行为规则

## 1. 任务复杂度分类
- **简单**（直接执行）：单一工具调用、纯查询、纯文件读写
- **中等**（先发计划再执行）：多步骤、跨工具
- **复杂**（必须先拆解 + 等用户确认）：跨系统、不可逆操作、需要人类决策

## 2. 路由表（任务类型 → 执行者）
| 任务类型 | 执行者 |
|---------|-------|
| 代码改动、本地文件 | Agent 自动 |
| 部署到生产 | Agent 起草，人工确认（→ review） |
| 设计风格 / 文案选型 | 必须人工拍板（出方案 → blocked） |
| 联网搜索 / 第三方 API | Agent 自动 |
| 数据库 schema 变更 | Agent 起草，人工确认（→ review） |

## 3. 失败处理表
| 失败类型 | 处理 |
|---------|-----|
| 工具调用超时 | 重试 1 次，仍失败则 blocked |
| 网络错误 | 等 30s 重试 1 次 |
| 权限/凭据缺失 | 立即 blocked，写明缺什么 |
| 任务前提不满足 | blocked + 说明依赖项 |

## 4. 注意力分配规则
- P0 立即处理，可中断 P1/P2
- P2 仅在无 P0/P1 时执行
- P2 任务执行总时长 ≤ 30 分钟，超时挂起
- 阻塞中（blocked-on-human）的任务总数 ≤ 3，超过则不再生成新阻塞，改为先完成已有

## 5. 个人情境（用户 = Siyao）
- 用户有 ADHD / 启动困难
- 分配给人的任务必须满足三条：
  1. 具体（一句话能说清要做什么）
  2. 单次可完成（≤ 15 分钟）
  3. 说清"为什么需要你"（不是"看一下"，而是"你需要从 A/B/C 选一个，因为 X"）
- 一次最多挂起 3 个 blocked-on-human 任务，避免人侧积压
```

### Task Decomposition

1. Orchestrator reads macro task description.
2. Calls LLM (with `skills/rules.md` in context): "Decompose this task into independently executable sub-steps following the complexity classification rules."
3. LLM returns subtask list.
4. Orchestrator writes subtasks into frontmatter `subtasks` field.
5. Posts execution plan in conversation area.
6. Waits 2 seconds (window for human to review).
7. Begins executing subtasks in order/parallel.

If a subtask matches a routing rule that requires human pickup (e.g., "设计风格选型"), Orchestrator marks that subtask `status: blocked` with a `blocking_reason` and moves the file to `blocked/`.

### Priority Management

| Priority | Meaning | Agent Behavior |
|----------|---------|---------------|
| P0 | Urgent | Execute immediately, interrupt current P1/P2 tasks |
| P1 | Important | Normal queue, execute in order |
| P2 | Low | Execute only when no P0/P1 tasks exist; max 30 min total runtime |

When P0 arrives, Agent pauses current P1/P2 (marks `paused: true` in frontmatter) and handles P0 first.

### Permission Mechanism (Bold Mode)

Default: `auto_approve: true` → completed tasks go straight to `done/`.

`auto_approve: false` → completed tasks go to `review/`. Human reviews on the kanban board / mobile UI:
- Approve → manually move to `done/` (or click "Approve" in UI which moves the file).
- Reject → move back to `todo/` with a `### [Human]` feedback comment; Agent will re-pick on next cycle with the feedback in context.

Mid-task blocking (separate from review):
1. Agent writes in conversation: "I need you to confirm: XXX" or proposes options A/B/C.
2. Moves task file to `blocked/`.
3. Sends WeChat notification.
4. Switches to other parallel tasks.

Human confirms by replying in conversation area → Agent detects new reply (via watchdog or polling) → Agent moves file back to `doing/` → resumes task.

### Intelligent Dependency Analysis

- Explicit: `depends_on` field in frontmatter.
- Implicit: LLM analyzes task descriptions for logical ordering (e.g., "deploy backend" should follow "run tests").
- Independent tasks execute in parallel via `asyncio.gather`.

## Layer 5: State & Logging Layer

### Structured Logging (JSONL)

Per-task log: `logs/{task_id}-{slug}.jsonl`

```json
{"ts": "2026-04-26T14:02:00", "task_id": "025", "action": "llm_call", "detail": "任务拆解为5个子步骤", "duration_ms": 1200, "status": "success"}
{"ts": "2026-04-26T14:02:03", "task_id": "025", "action": "tool_exec", "tool": "shell", "detail": "ssh root@<your-server> 'mysqldump ...'", "duration_ms": 8500, "status": "success"}
{"ts": "2026-04-26T14:05:00", "task_id": "025", "action": "status_change", "detail": "doing → blocked", "reason": "合并冲突需人工确认", "duration_ms": 0, "status": "blocked"}
{"ts": "2026-04-26T15:31:00", "task_id": "025", "action": "status_change", "detail": "doing → review", "reason": "auto_approve=false, all subtasks done", "duration_ms": 0, "status": "review"}
```

Global system log: `logs/agent.jsonl` (startup, shutdown, git sync, errors, dry-run reports).

Every operation is traceable: timestamp, duration, what was executed, result.

## Operations & CLI

The Agent ships with a single CLI entry point: `cc-assistant`.

| Command | Purpose |
|---------|---------|
| `cc-assistant run` | Start the Agent daemon (foreground; supervisor in production) |
| `cc-assistant run --dry-run [task_id]` | Simulate one cycle: walk decomposition + routing + tool selection, but stub all writes / shell / API / DB calls. Output a "what would happen" report to stdout and `logs/agent.jsonl`. |
| `cc-assistant stop` | Send SIGTERM to running daemon (PID at `logs/agent.pid`) → finish in-flight tool → close watchdog observer → close APScheduler → write `system_shutdown` log → exit. |
| `cc-assistant status` | Show PID, uptime, active task count by column, recent log entries. |

Lifecycle:
- Foreground (dev): `cc-assistant run` in a terminal.
- Background (prod): wrap with NSSM (Windows service) or systemd (Linux remote).
- PID file: `logs/agent.pid` (overwritten on start, removed on clean stop).

## Mobile Web UI

Deployed on a remote server, built with FastAPI + plain HTML/JS (no framework).

| Page | Function |
|------|----------|
| Task Board | Six-column display: backlog/todo/doing/blocked/review/done; group rows by `project` field; click for details |
| Task Detail | View conversation history, subtask progress, write replies, approve / reject from review |
| New Task | Fill in title, description, priority, project → generates task file in `backlog/` or `todo/` |
| Notifications | View Agent's block requests and review-pending items |

First iteration: no authentication (simple password protection or IP whitelist). Mobile replies write to task file conversation area → git push → local Agent pulls and continues.

## Project Structure

```
cc-assistant/
├── pyproject.toml
├── .env / .env.example
├── .gitignore
├── tasks/                       # Task files (Git synced)
│   ├── backlog/ / todo/ / doing/ / blocked/ / review/ / done/ / templates/
├── skills/
│   └── rules.md                 # Human-editable Agent behavior rules
├── logs/                        # JSONL logs (gitignored)
├── src/
│   ├── main.py                  # Entry point + CLI dispatch
│   ├── config.py                # Configuration
│   ├── models.py                # Pydantic data models
│   ├── cli.py                   # run / stop / status / dry-run subcommands
│   ├── board/
│   │   ├── parser.py            # Parse task files
│   │   ├── writer.py            # Write back to task files
│   │   └── manager.py           # File moves between status dirs, archival
│   ├── dispatcher/
│   │   ├── watcher.py           # watchdog file monitoring
│   │   ├── scheduler.py         # APScheduler polling
│   │   └── sync.py              # Git auto sync
│   ├── agent/
│   │   ├── orchestrator.py      # Main Agent (Completion Promise Pattern)
│   │   ├── context.py           # Build LLM context from rules.md + task file
│   │   └── llm/
│   │       ├── base.py          # LLMClient ABC
│   │       ├── claude.py        # Anthropic
│   │       ├── openai.py        # OpenAI
│   │       └── ollama.py        # Ollama
│   ├── tools/
│   │   ├── base.py              # Tool ABC + auto-register + dry_run
│   │   ├── file_ops.py / shell.py / web_search.py
│   │   ├── code_edit.py / database.py
│   │   ├── notifier.py / api_caller.py
│   ├── rules/
│   │   ├── loader.py            # Load skills/rules.md
│   │   ├── priority.py          # P0/P1/P2 scheduling
│   │   ├── permissions.py       # auto_approve + review/blocked routing
│   │   └── decomposer.py        # Task decomposition
│   └── logging/
│       └── structured.py        # JSONL logger
├── web/                          # Mobile Web UI (deployed to remote)
│   ├── app.py                    # FastAPI app
│   ├── routes.py                 # REST API
│   ├── static/ (style.css, app.js)
│   └── templates/ (board.html, task.html, new_task.html)
└── tests/
    ├── test_parser.py / test_writer.py
    ├── test_orchestrator.py / test_dispatcher.py
    ├── test_rules_loader.py / test_cli.py
    └── test_tools.py
```

## Tech Stack

- **Runtime:** Python 3.11+ / uv
- **Concurrency:** asyncio + ThreadPoolExecutor
- **File monitoring:** watchdog
- **Scheduling:** APScheduler
- **LLM clients:** anthropic, openai, ollama (pluggable)
- **Data models:** pydantic
- **Config:** python-dotenv, pydantic-settings
- **Database:** aiomysql
- **HTTP:** httpx
- **CLI:** typer (or argparse)
- **Web UI:** FastAPI + Jinja2 templates + plain JS
- **Sync:** Git (auto commit/push/pull)
- **Notifications:** WeChat enterprise bot webhook
- **Testing:** pytest + pytest-asyncio
- **Run mode:** Foreground (dev) / Windows service via NSSM (prod)

## Open Questions / Deferred to Future Iterations

- LLM-based auto-evaluator for review-pending tasks (delegate has this; deferred as YAGNI for v1).
- Screenshot / image attachment to tasks (delegate has this; deferred).
- tmux-based agent output streaming (Windows-incompatible; deferred).
- Multi-project support via separate task folders (current design groups by `project` frontmatter field within a single instance; multi-folder support deferred).
