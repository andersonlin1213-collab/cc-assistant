# Retail-Briefing γ Skeleton — Design

**Date**: 2026-05-04
**Source task**: `cc-assitant/tasks/doing/<original-task>.md`
**Target project**: `<your-user>\projects\retail-briefing\` (new, independent, peer to cc-assitant)

## 一句話

把 003 卡里手动跑通的"DeepSeek 生成 → 企微推送"两步，固化成一个独立的 Python 项目骨架（γ scope），下一轮就能从"接 W1 真数据源"开始。

## 背景与决策

- **003 当前状态**：webhook + DeepSeek key 已进 `cc-assitant\.env`；2026-05-02 用 DeepSeek 跑通生成；2026-05-03 用一次性脚本 `_send_retail_test.py` 把样例推到企微测试群（HTTP 200）。本地骨架还没建。
- **2026-05-04 决策**：
  - **路径选 A（独立平级）**：`projects\retail-briefing\`，跟 cc-assitant 同级。理由：现有 16 个项目全平级；retail-briefing 是独立业务，不是 cc-assitant 内部组件。
  - **scope 选 γ（骨架 + 推送 + DeepSeek client）**：把已经手动跑通的两步搬进项目结构 + 加测试。理由：α 太空下一轮还要回头补；β 留个尴尬中间态。
  - **LLM provider = DeepSeek**：003 卡 V1 规格里写 Haiku 4.5，但实际验证用的 DeepSeek（成本 ~$0.0003/次，已确认可用）。Haiku-vs-DeepSeek 真正抉择留给 W2。
  - **本地 git，不立即推远程**：等代码稳定再决定 GitHub 还是只本地。

## 项目结构

```
projects/retail-briefing/
├── README.md                    # 项目说明 + 怎么跑
├── pyproject.toml               # Python 3.11, deps: requests, python-dotenv, pytest
├── .env.example                 # DEEPSEEK_API_KEY=, RETAIL_BRIEFING_WECOM_WEBHOOK=
├── .env                         # 实际凭据（gitignored）
├── .gitignore                   # .env, __pycache__, .pytest_cache, .venv
├── src/retail_briefing/
│   ├── __init__.py
│   ├── __main__.py              # python -m retail_briefing 入口
│   ├── cli.py                   # argparse: generate / send / generate --send
│   ├── config.py                # 从 .env 读 DEEPSEEK_API_KEY + RETAIL_BRIEFING_WECOM_WEBHOOK
│   ├── deepseek_client.py       # 封装 DeepSeek API（chat/completions）
│   ├── wecom_sender.py          # 封装企微 webhook（markdown 卡片）
│   └── briefing.py              # 编排：generate prompt → deepseek → format → return
└── tests/
    ├── __init__.py
    ├── test_deepseek_client.py  # mock requests，测 payload 构造 + 错误处理
    ├── test_wecom_sender.py     # mock requests，测 markdown 卡片格式 + errcode 解析
    └── test_briefing.py         # mock 两个 client，测端到端编排
```

## CLI 形态

```bash
python -m retail_briefing generate              # DeepSeek 生成早报，stdout 输出
python -m retail_briefing send --text "测试"     # 直接推一条文本到企微
python -m retail_briefing generate --send       # 全链路：生成 → 推送
```

## 模块职责

### `config.py`
- 从项目根 `.env` 加载 `DEEPSEEK_API_KEY` 和 `RETAIL_BRIEFING_WECOM_WEBHOOK`
- 缺任何一条就 raise，给清晰错误信息（带变量名）
- 暴露一个 `Config` 对象或两个常量

### `deepseek_client.py`
- 类 `DeepSeekClient(api_key: str)`
- 方法 `chat(messages: list[dict], model: str = "deepseek-chat") -> str`
- 内部用 `requests.post` 打 `https://api.deepseek.com/v1/chat/completions`
- 非 2xx 抛 `DeepSeekError(status, body)`
- 解析返回拿到 `choices[0].message.content`

### `wecom_sender.py`
- 类 `WeComSender(webhook_url: str)`
- 方法 `send_markdown(content: str) -> dict`（返回企微响应 dict）
- 内部 POST `{"msgtype": "markdown", "markdown": {"content": content}}`
- `errcode != 0` 抛 `WeComError(errcode, errmsg)`

### `briefing.py`
- 函数 `generate_briefing(client: DeepSeekClient, today: date) -> str`
  - prompt 模块常量 `BRIEFING_PROMPT`，由两部分组成：
    1. **System 指令**：基于 003 卡 V1 规格 —— <N> 家watchlist清单 / 三块结构（头条 / 经营数据 / <region-1>+<region-2>本地）/ 本地权重规则 / 早报 ≤ 800 字 / 数据真实性免责声明
    2. **Few-shot 样例**：003 卡 60-78 行那段 2026-05-02 早报样例
  - 后续 W1/W2 接真数据时再抽出 prompt 模板，γ 阶段 inline 即可
  - 返回 markdown 字符串
- 函数 `format_for_wecom(briefing_md: str) -> str`
  - 把生成的 markdown 裁剪/调整到企微卡片格式（≤ 800 字、企微支持的 markdown 子集）

### `cli.py`
- `argparse` 子命令 `generate / send / generate --send`
- `generate`：调 `generate_briefing` → 打 stdout
- `send --text`：调 `wecom_sender.send_markdown(args.text)`
- `generate --send`：链式跑，二者中间打个 stdout 回显

### `__main__.py`
- 一行 `from retail_briefing.cli import main; main()`

## 数据

γ 阶段**不抓真新闻**。Prompt 让 DeepSeek 自己编 placeholder 内容（明确标注"非真实新闻"），跟 003 卡 11:08 那条样例一样。

W1 才接真数据源（<source-A> RSS + <source-B>，SQLite 入库）。

## 凭据迁移

- 从 `cc-assitant\.env` 复制 `DEEPSEEK_API_KEY` + `RETAIL_BRIEFING_WECOM_WEBHOOK` 两条到 `projects\retail-briefing\.env`
- `cc-assitant\.env` 里的两条**保留不删** —— 短期冗余无害，删了反而要 cc-assitant 跟着改
- `.env.example` 进 git，`.env` gitignored

## Git

- `projects\retail-briefing\` 独立 `git init`
- 本地仓库，不立即推远程
- 第一个 commit："chore: scaffold retail-briefing γ skeleton"

## 项目卡（cc-assitant vault）

新建 `cc-assitant\tasks\projects\retail-briefing.md`，frontmatter:

```yaml
---
type: project
slug: "retail-briefing"
status: active
repo_path: "../../retail-briefing"
priority: P1
tags: [news, briefing, retail]
last_touched: 2026-05-04
---
```

正文章节按 CLAUDE.md 惯例：
- **一句話**：每日/每周<my-domain>新闻自动推送（DeepSeek 生成 + 企微推送）
- **現在的焦點**：γ 骨架已落地，跑通"DeepSeek → 企微"全链路（placeholder 数据）
- **下一步**：W1 数据源接入（<source-A> RSS + <source-B>公告 + SQLite）/ W2 真数据 + Haiku-vs-DeepSeek 抉择 / W3 <region-1>+<region-2>本地源 / W4 周报模板
- **決策記錄**：2026-05-04 路径选独立平级 / 2026-05-04 LLM 选 DeepSeek / 2026-05-04 scope 选 γ
- **待解決的問題**：W2 要不要切 Haiku 4.5（成本对比 + 中文质感对比未做）

## 测试

### Unit（pytest）
- `test_deepseek_client.py`：mock `requests.post`，测请求 payload 格式、200 OK 解析、非 2xx 抛 `DeepSeekError`
- `test_wecom_sender.py`：mock `requests.post`，测 markdown 卡片 payload、`errcode=0` 通过、`errcode!=0` 抛 `WeComError`
- `test_briefing.py`：mock `DeepSeekClient` 和 `WeComSender`，测 `generate_briefing` 调用 chat 方法 + 返回内容；测 `format_for_wecom` 裁剪逻辑

### 手动 smoke（不进 pytest）
- `python -m retail_briefing generate` 真调一次 DeepSeek 看输出
- `python -m retail_briefing generate --send` 真发一条到企微测试群

## 验收

- `pytest` 全绿（mock HTTP，不真调外部）
- `pip install -e .` 成功
- 三条 CLI 命令各自能跑（手动 smoke 全过）
- 项目卡 `tasks/projects/retail-briefing.md` 已建并按惯例填充
- 第一个 git commit 已落

## 不做（YAGNI）

明确**不**包含在 γ 里：
- APScheduler / cron 定时（W4 才需要）
- SQLite 入库（W1 才需要）
- 任何真新闻数据源（<source-A> / <source-B> / 本地媒体）
- URL/SimHash/MinHash 去重（W1 需要）
- 远程部署到 `/opt/<deploy>/retail-briefing/`（要单独确认才能动远程）
- 周报模板（W4）
- <region-1>/<region-2>本地源（W3）
- Haiku 4.5 切换（W2 抉择）
