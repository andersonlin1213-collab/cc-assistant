# cc-assistant

> 在 Obsidian 里勾一个复选框，就能让 Claude Code 跨多个仓库帮你干活。

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)
[![Status: beta](https://img.shields.io/badge/status-beta-orange.svg)](#)

[English README](./README.md)

一个本地 file-first 的任务 daemon，用 Obsidian vault 当 UI。把一个 markdown
文件丢到 `tasks/todo/` 里，或者在任何项目卡下面勾一个 `- [ ]`，daemon 就会
拿起来，驱动一个 Claude agent 把活干完，并把文件流转到 `doing/` → `done/`
（或 `review/` / `blocked/`）。

不用数据库。不用 MCP server。不用 web 应用。一个 Python daemon + 你的 vault
+ 你现有的 Claude Code，就够了。

<!-- demo gif 占位
![demo](docs/demo.gif)
-->

---

## 为什么再造一个 Claude + Obsidian agent？

大部分 Obsidian + Claude 项目都是**插件**（你打开 Obsidian，在 sidebar 里
打字）。cc-assistant 反过来：一个**无头 daemon**，把 vault 当文件来 watch，
**根本不需要 Obsidian 在运行**。

同类项目里你**找不到**的三件事：

| | cc-assistant | 典型的 "Obsidian + Claude" |
|---|---|---|
| **烧 Max 订阅，不烧 API token** | ✅ 默认走 `claude_cli` provider — 调本地 `claude` CLI，**每个任务成本 $0** | ❌ 只能用 API，每个任务都烧钱 |
| **按任务自动路由 provider** | ✅ 给任务打 `db,mysql,api` tag → 自动升级到 API（自定义工具能用）。其余继续走免费 CLI。 | ❌ 一个 provider，一张账单 |
| **勾一个 `- [ ]` → 派单到另一个 repo** | ✅ `projects/<slug>.md` 通过 `repo_path:` 指向相邻仓库。在 `## 下一步` 下勾选复选框，daemon 会派单到那个 repo 里。 | ❌ 单 vault scope |
| **零基础设施** | ✅ `pip install -e .` + 你现有的 Claude CLI，就这些 | ❌ MCP server、Postgres+pgvector、OAuth app、webhook 一堆 |

如果想要一个有语义记忆 + dashboard 的"个人 AI 操作系统"，看
[work-buddy](https://github.com/KadenMc/work-buddy)。如果想用 Obsidian 当
Linear issue 的看板，看
[ai-agent-workflow](https://github.com/Jason-Cyr/ai-agent-workflow)。如果想要
**最轻**的那种 daemon，能从手机排队任务、让 Claude 一晚上跑完，那你来对了。

---

## 快速开始

```bash
# 1. 安装
git clone https://github.com/<your-user>/cc-assistant.git
cd cc-assistant
pip install -e .

# 2. 配置
cp .env.example .env
# 最少只要：LLM_PROVIDER=claude_cli（默认 — 调本地 `claude` CLI 用 Max 订阅，
# 不需要 API key）。
# 想用 tag-based 升级到 API 的话，再加 ANTHROPIC_API_KEY。

# 3. 单任务 dry-run，验证接线
cc-assistant run --dry-run --target tasks/todo/foo.md

# 4. 启动 daemon
cc-assistant run            # 前台
# 或者
scripts\run-daemon.bat      # Windows 后台

# 5. 状态 / 停止
cc-assistant status
cc-assistant stop
```

**前置条件**：Python 3.11+、任意平台的 Obsidian、外加 `claude` CLI（推荐）
或 `ANTHROPIC_API_KEY`。

> 🇨🇳 **大陆用户注意**：直接连 `api.anthropic.com` 不通，会报 403。看下面
> [进阶配置](#进阶配置) 里的代理设置一节。

---

## 工作原理

1. 把 `tasks/` 文件夹当 Obsidian vault 打开。用 Obsidian Sync / iCloud / Syncthing（随你）同步到手机。
2. 任何地方，在 `tasks/todo/` 下建一个文件。文件名就是任务标题；不需要 frontmatter — daemon 自动填 `id`、`created`、`updated`。
3. daemon 端的 file watcher 接住文件，挪到 `tasks/doing/`，开始驱动 Claude 对话。每条 AI 回复都会追加到文件里。文件里会留一行 placeholder，你在 Obsidian 里覆盖那一行并保存，就能继续对话回合。
4. AI 能调的工具：`mark_complete`、`mark_blocked`，加上 `src/tools/` 里的自定义工具表（文件操作、shell、web fetch、MySQL、API caller、通知器）。

### Provider 路由（省钱设计）

两个 LLM provider 共存；`LLMRouter` 给每个任务挑一个：

- **`claude_cli`**（默认）— 调本地 `claude` CLI 子进程。烧 Claude.ai Max 订阅。**每任务成本 $0**。代价：这个 CLI 跑的是它自己的原生工具，cc-assistant 的自定义工具从这个 provider 调不到。
- **`claude`** — 走 Anthropic SDK + `ANTHROPIC_API_KEY`。按 token 付费，但 cc-assistant 完整的自定义工具集（MySQL / 企微 / 钉钉 / api_caller / web_fetch）能用。

路由优先级：

1. 任务 frontmatter 里显式写 `provider:`（`claude` 或 `claude_cli`）
2. Tag 升级：任意 tag 命中 `ESCALATE_TAGS`（默认 `db,mysql,wecom,dingtalk,api`）就强制走 API
3. 全局默认（`LLM_PROVIDER`）

如果命中的 provider 没配置好，daemon 写一条 `provider_unavailable` 日志后直接跳过这个 cycle ——**绝不**静默 fallback 到另一个跑不了任务的 provider。

### 项目卡（跨多仓派单）

除了单任务文件，`tasks/projects/<slug>.md` 存放每个项目的上下文（做什么 /
为什么 / 下一步 / 决策记录）。每张卡声明自己对应哪个 repo：

```yaml
---
type: project
slug: "my-side-project"
status: active            # 或 paused / archived
repo_path: "../my-side-project"   # 相对 projects/ 子目录
priority: P1
tags: []
last_touched: 2026-05-17
---
```

daemon 反应两个信号：

- `status: paused` / `archived` 会阻止该项目派**新**任务（已在跑的不杀）。
- 在项目卡的 `## 下一步 (Next actions)` 下勾选 `- [ ]`，会**自动派单**到 `tasks/todo/`，并把那行重写成 wikilink。这就是"勾一下，agent 上岗"的 UX。

dogfood 例子：`tasks/projects/cc-assitant.md`。

---

## 架构

```
src/
  agent/          # Orchestrator + LLM clients + ToolBridge
    llm/          # ClaudeClient, ClaudeCLIClient, LLMRouter
  board/          # Parser, writer, manager, project_handler
  dispatcher/     # File watcher + scheduler
  rules/          # Skill / rules loader
  tools/          # FileOps, Shell, WebFetch, Database, Notifier, ApiCaller
  cli.py          # `cc-assistant`入口
  config.py       # pydantic-settings 从 .env 加载
tasks/            # Obsidian vault — 所有看板状态在这
  todo/ doing/ done/<YYYY-MM>/ blocked/ review/ backlog/
  projects/       # 项目卡
logs/             # 每任务 JSONL + agent.jsonl 系统日志
tests/            # pytest suite
```

---

## 配置

所有值通过 `pydantic-settings` 从 `.env` 读。完整 schema 看 `src/config.py`。
最常用的：

| Var | 默认 | 用途 |
| --- | --- | --- |
| `LLM_PROVIDER` | `claude_cli` | `claude` 或 `claude_cli`（可被任务 frontmatter `provider:` 覆盖） |
| `ANTHROPIC_API_KEY` | `""` | 任何路径走 API client 时必填 |
| `ESCALATE_TAGS` | `db,mysql,wecom,dingtalk,api` | 强制升级到 API 的 tag 列表（CSV） |
| `TASKS_DIR` | `tasks` | Vault 根目录 |
| `LOGS_DIR` | `logs` | JSONL 日志目的地 |
| `POLL_INTERVAL_MINUTES` | `30` | Watcher 漏接的兜底轮询 |
| `DEBOUNCE_SECONDS` | `15` | 文件保存后多久才触发 cycle 的最小空闲时间。专门为 Obsidian Sync 从手机上传半成品的场景调过 — 只在桌面用的话可以调低换更快响应。 |
| `OBSIDIAN_CHECK_PROCESS` | `false` | 启动时如果 Obsidian 桌面端没在跑就警告 |

---

## 测试

```bash
pytest             # 全套（~25s）
pytest -q tests/test_orchestrator.py
```

唯一一个 skip 的（`test_llm_claude_real`）需要真 API key。

---

## 进阶配置

<details>
<summary><b>注册成 Windows Scheduled Task（重启/登出都不掉）</b></summary>

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-task-scheduler.ps1
Start-ScheduledTask -TaskName "cc-assistant"
```

状态 / 卸载：

```powershell
Get-ScheduledTask -TaskName cc-assistant | Get-ScheduledTaskInfo
scripts\uninstall-task-scheduler.ps1
```

</details>

<details open>
<summary><b>🇨🇳 大陆/GFW 环境下的代理配置</b></summary>

如果你机器直连 `api.anthropic.com` 不通，`claude` CLI 会报 `403 Request not
allowed`。在你 shell 的 rc 文件（`~/.bashrc` 之类）里 export
`HTTP_PROXY` / `HTTPS_PROXY` **不够** —— daemon 是被 Windows Task Scheduler
/ `cmd.exe` 拉起来的，根本不读 `.bashrc`，所以那个 spawn 出来的 `claude`
子进程看不到你的代理。

正确做法：把代理写到 Windows 用户级环境变量里，所有用户态拉起来的进程
（包括 Scheduled Task 的 daemon）就都能继承：

```powershell
# 在 PowerShell 里跑一次。把 127.0.0.1:10808 换成你本地代理端口（v2rayN / Clash 等）。
[Environment]::SetEnvironmentVariable("HTTP_PROXY",  "http://127.0.0.1:10808", "User")
[Environment]::SetEnvironmentVariable("HTTPS_PROXY", "http://127.0.0.1:10808", "User")
[Environment]::SetEnvironmentVariable("NO_PROXY",    "localhost,127.0.0.1,10.*,100.*,192.168.*,*.local", "User")

# 然后重启 daemon 让它捡到新 env：
Stop-ScheduledTask -TaskName "cc-assistant"
Start-ScheduledTask -TaskName "cc-assistant"
```

**不配的话症状**：`logs/{id}.jsonl` 里全是 `cycle_error`，里面带
`api_error_status:403`。`claude auth status` 还显示 `loggedIn: true`，看起来
像 auth 出问题 —— 其实是网络不通。

**快速确认是不是这个坑**：自己在干净 shell 里跑一次 CLI。如果
`claude auth status` 和直接调用在你终端里都正常，但 daemon 的 `cycle_error`
报 403，就是它。

</details>

---

## 贡献

欢迎 PR。开 PR 前请：

- `pytest` 全绿（那个 skip 的 real-API 测试保持 skip 没问题）
- 改动聚焦 —— 一个 PR 一个 feature / fix
- 已上线 feature 的设计文档在 `docs/superpowers/specs/` 和
  `docs/superpowers/plans/`。引入大块新子系统时，加一份带日期的新 spec。

---

## License

[MIT](./LICENSE) © Anderson Lin
