# retail-briefing γ Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scaffold an independent Python project at `<your-user>\projects\retail-briefing\` that codifies the manually-verified "DeepSeek 生成 → 企微推送" flow from task `cc-assitant\tasks\doing\<original-task>.md`, with mock-HTTP unit tests and three CLI commands.

**Architecture:** Standalone Python 3.11 package (src layout), zero business state in γ — DeepSeek generates placeholder content (no real news yet), WeCom webhook sends to a test group. Five focused modules: `config` (env loading), `deepseek_client` (API wrapper), `wecom_sender` (webhook wrapper), `briefing` (prompt + orchestration), `cli` (argparse). Each external HTTP call wrapped behind a thin client with typed errors so unit tests can mock at the `requests.post` boundary.

**Tech Stack:** Python 3.11, `requests`, `python-dotenv`, `pytest`. No async, no scheduler, no DB — those land in W1+.

---

## File Structure

**New project root:** `<your-user>\projects\retail-briefing\`

```
retail-briefing/
├── README.md                    # Task 1 — usage docs
├── pyproject.toml               # Task 1 — package metadata
├── .env.example                 # Task 1 — credential template
├── .gitignore                   # Task 1
├── src/retail_briefing/
│   ├── __init__.py              # Task 1 — version
│   ├── config.py                # Task 2 — env-loaded Config dataclass
│   ├── deepseek_client.py       # Task 3 — DeepSeek API wrapper
│   ├── wecom_sender.py          # Task 4 — WeCom webhook wrapper
│   ├── briefing.py              # Task 5 — prompt + orchestration
│   ├── cli.py                   # Task 6 — argparse entry
│   └── __main__.py              # Task 6 — `python -m retail_briefing` shim
└── tests/
    ├── __init__.py              # Task 1 — empty
    ├── test_deepseek_client.py  # Task 3 — mock HTTP
    ├── test_wecom_sender.py     # Task 4 — mock HTTP
    └── test_briefing.py         # Task 5 — mock both clients
```

**Touched in cc-assitant:**
- Modify: `cc-assitant\tasks\doing\<original-task>.md` (Task 9 — append final AI cycle, move to done/)
- Create: `cc-assitant\tasks\projects\retail-briefing.md` (Task 9 — new project card)

---

## Task 1: Scaffold project root + git init

**Files:**
- Create: `<your-user>\projects\retail-briefing\.gitignore`
- Create: `<your-user>\projects\retail-briefing\.env.example`
- Create: `<your-user>\projects\retail-briefing\pyproject.toml`
- Create: `<your-user>\projects\retail-briefing\README.md`
- Create: `<your-user>\projects\retail-briefing\src\retail_briefing\__init__.py`
- Create: `<your-user>\projects\retail-briefing\tests\__init__.py`

- [ ] **Step 1: Create the project root directory**

```bash
mkdir -p /c/<your-user>/projects/retail-briefing/src/retail_briefing
mkdir -p /c/<your-user>/projects/retail-briefing/tests
```

- [ ] **Step 2: Write `.gitignore`**

File: `<your-user>\projects\retail-briefing\.gitignore`

```
.env
__pycache__/
*.pyc
.pytest_cache/
.venv/
*.egg-info/
build/
dist/
```

- [ ] **Step 3: Write `.env.example`**

File: `<your-user>\projects\retail-briefing\.env.example`

```
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
RETAIL_BRIEFING_WECOM_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
```

- [ ] **Step 4: Write `pyproject.toml`**

File: `<your-user>\projects\retail-briefing\pyproject.toml`

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "retail-briefing"
version = "0.1.0"
description = "Daily/weekly domain-specific briefing — DeepSeek 生成 + 企微推送"
requires-python = ">=3.11"
dependencies = [
    "requests>=2.31",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
]

[project.scripts]
retail-briefing = "retail_briefing.cli:main"

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 5: Write `README.md`**

File: `<your-user>\projects\retail-briefing\README.md`

````markdown
# retail-briefing

每日/每周 domain-specific 简报自动推送（DeepSeek 生成 + 企微推送）。

## 状态

γ 骨架（2026-05-04）—— 项目结构 + DeepSeek client + 企微推送 + CLI。
内容为 placeholder（DeepSeek 自编），W1 才接真数据源。

## 快速开始

```bash
pip install -e .

cp .env.example .env
# 编辑 .env 填入 DEEPSEEK_API_KEY 和 RETAIL_BRIEFING_WECOM_WEBHOOK

python -m retail_briefing generate              # 生成早报到 stdout
python -m retail_briefing send --text "测试"     # 直接推一条到企微
python -m retail_briefing generate --send       # 全链路：生成 → 推送
```

## 测试

```bash
pip install -e ".[dev]"
pytest
```

## 路线图

- [x] γ 骨架（2026-05-04）
- [ ] W1 数据源接入（<source-A> RSS + <source-B><retailer>公告 + SQLite）
- [ ] W2 真数据 + Haiku-vs-DeepSeek 抉择
- [ ] W3 <region-1>+<region-2>本地源
- [ ] W4 周报模板

## 关联

设计与决策见 `cc-assitant/docs/superpowers/specs/2026-05-04-retail-briefing-gamma-skeleton-design.md`。
任务卡：`cc-assitant/tasks/projects/retail-briefing.md`。
````

- [ ] **Step 6: Write `src/retail_briefing/__init__.py`**

File: `<your-user>\projects\retail-briefing\src\retail_briefing\__init__.py`

```python
__version__ = "0.1.0"
```

- [ ] **Step 7: Write empty `tests/__init__.py`**

File: `<your-user>\projects\retail-briefing\tests\__init__.py`

```python
```

- [ ] **Step 8: `git init` and verify install works**

```bash
cd /c/<your-user>/projects/retail-briefing
git init
pip install -e ".[dev]"
```

Expected: `git init` reports "Initialized empty Git repository". `pip install -e ".[dev]"` ends with "Successfully installed retail-briefing-0.1.0" and pulls `requests`, `python-dotenv`, `pytest`.

- [ ] **Step 9: First commit**

```bash
cd /c/<your-user>/projects/retail-briefing
git add .gitignore .env.example pyproject.toml README.md src/ tests/
git commit -m "chore: scaffold retail-briefing γ skeleton"
```

---

## Task 2: `config.py` — env loading

**Files:**
- Create: `<your-user>\projects\retail-briefing\src\retail_briefing\config.py`
- Create: `<your-user>\projects\retail-briefing\tests\test_config.py`

- [ ] **Step 1: Write the failing test**

File: `<your-user>\projects\retail-briefing\tests\test_config.py`

```python
import pytest

from retail_briefing.config import Config


class TestConfigFromEnv:
    def test_loads_both_vars(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        monkeypatch.setenv("RETAIL_BRIEFING_WECOM_WEBHOOK", "https://example.com/hook")

        config = Config.from_env(load_dotenv=False)

        assert config.deepseek_api_key == "sk-test"
        assert config.wecom_webhook_url == "https://example.com/hook"

    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.setenv("RETAIL_BRIEFING_WECOM_WEBHOOK", "https://example.com/hook")

        with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
            Config.from_env(load_dotenv=False)

    def test_missing_webhook_raises(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        monkeypatch.delenv("RETAIL_BRIEFING_WECOM_WEBHOOK", raising=False)

        with pytest.raises(RuntimeError, match="RETAIL_BRIEFING_WECOM_WEBHOOK"):
            Config.from_env(load_dotenv=False)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /c/<your-user>/projects/retail-briefing
pytest tests/test_config.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'retail_briefing.config'`.

- [ ] **Step 3: Write minimal implementation**

File: `<your-user>\projects\retail-briefing\src\retail_briefing\config.py`

```python
"""Configuration loaded from environment / .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv as _load_dotenv


@dataclass(frozen=True)
class Config:
    deepseek_api_key: str
    wecom_webhook_url: str

    @classmethod
    def from_env(cls, load_dotenv: bool = True) -> "Config":
        if load_dotenv:
            env_path = Path(__file__).resolve().parents[2] / ".env"
            _load_dotenv(env_path)

        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise RuntimeError(
                "DEEPSEEK_API_KEY not set. Copy .env.example to .env and fill in credentials."
            )

        webhook_url = os.environ.get("RETAIL_BRIEFING_WECOM_WEBHOOK")
        if not webhook_url:
            raise RuntimeError(
                "RETAIL_BRIEFING_WECOM_WEBHOOK not set. Copy .env.example to .env and fill in credentials."
            )

        return cls(deepseek_api_key=api_key, wecom_webhook_url=webhook_url)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /c/<your-user>/projects/retail-briefing
pytest tests/test_config.py -v
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
cd /c/<your-user>/projects/retail-briefing
git add src/retail_briefing/config.py tests/test_config.py
git commit -m "feat(config): load DEEPSEEK_API_KEY + WECOM_WEBHOOK from env"
```

---

## Task 3: `deepseek_client.py` — DeepSeek API wrapper

**Files:**
- Create: `<your-user>\projects\retail-briefing\src\retail_briefing\deepseek_client.py`
- Create: `<your-user>\projects\retail-briefing\tests\test_deepseek_client.py`

- [ ] **Step 1: Write the failing test**

File: `<your-user>\projects\retail-briefing\tests\test_deepseek_client.py`

```python
from unittest.mock import MagicMock, patch

import pytest

from retail_briefing.deepseek_client import DeepSeekClient, DeepSeekError


class TestDeepSeekClient:
    def test_chat_success_returns_content(self):
        client = DeepSeekClient("test-key")
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hello world"}}]
        }
        with patch(
            "retail_briefing.deepseek_client.requests.post",
            return_value=mock_response,
        ) as mock_post:
            result = client.chat([{"role": "user", "content": "Hi"}])

        assert result == "Hello world"
        call = mock_post.call_args
        assert call.kwargs["json"]["model"] == "deepseek-chat"
        assert call.kwargs["json"]["messages"] == [{"role": "user", "content": "Hi"}]
        assert call.kwargs["headers"]["Authorization"] == "Bearer test-key"
        assert call.kwargs["headers"]["Content-Type"] == "application/json"

    def test_chat_custom_model_passed_through(self):
        client = DeepSeekClient("test-key")
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "ok"}}]
        }
        with patch(
            "retail_briefing.deepseek_client.requests.post",
            return_value=mock_response,
        ) as mock_post:
            client.chat([], model="deepseek-reasoner")

        assert mock_post.call_args.kwargs["json"]["model"] == "deepseek-reasoner"

    def test_chat_non_2xx_raises_deepseek_error(self):
        client = DeepSeekClient("test-key")
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 401
        mock_response.text = "Invalid API key"
        with patch(
            "retail_briefing.deepseek_client.requests.post",
            return_value=mock_response,
        ):
            with pytest.raises(DeepSeekError) as exc_info:
                client.chat([])

        assert exc_info.value.status_code == 401
        assert exc_info.value.body == "Invalid API key"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /c/<your-user>/projects/retail-briefing
pytest tests/test_deepseek_client.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'retail_briefing.deepseek_client'`.

- [ ] **Step 3: Write minimal implementation**

File: `<your-user>\projects\retail-briefing\src\retail_briefing\deepseek_client.py`

```python
"""DeepSeek chat completions API wrapper."""

from __future__ import annotations

import requests


class DeepSeekError(Exception):
    def __init__(self, status_code: int, body: str):
        super().__init__(f"DeepSeek API error {status_code}: {body}")
        self.status_code = status_code
        self.body = body


class DeepSeekClient:
    BASE_URL = "https://api.deepseek.com/v1/chat/completions"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def chat(self, messages: list[dict], model: str = "deepseek-chat") -> str:
        payload = {"model": model, "messages": messages}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        response = requests.post(self.BASE_URL, json=payload, headers=headers, timeout=60)
        if not response.ok:
            raise DeepSeekError(response.status_code, response.text)
        data = response.json()
        return data["choices"][0]["message"]["content"]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /c/<your-user>/projects/retail-briefing
pytest tests/test_deepseek_client.py -v
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
cd /c/<your-user>/projects/retail-briefing
git add src/retail_briefing/deepseek_client.py tests/test_deepseek_client.py
git commit -m "feat(deepseek): add chat client + DeepSeekError"
```

---

## Task 4: `wecom_sender.py` — WeCom webhook wrapper

**Files:**
- Create: `<your-user>\projects\retail-briefing\src\retail_briefing\wecom_sender.py`
- Create: `<your-user>\projects\retail-briefing\tests\test_wecom_sender.py`

- [ ] **Step 1: Write the failing test**

File: `<your-user>\projects\retail-briefing\tests\test_wecom_sender.py`

```python
from unittest.mock import MagicMock, patch

import pytest

from retail_briefing.wecom_sender import WeComError, WeComSender


class TestWeComSender:
    def test_send_markdown_success(self):
        sender = WeComSender("https://example.com/webhook")
        mock_response = MagicMock()
        mock_response.json.return_value = {"errcode": 0, "errmsg": "ok"}
        with patch(
            "retail_briefing.wecom_sender.requests.post",
            return_value=mock_response,
        ) as mock_post:
            result = sender.send_markdown("# Hello")

        assert result == {"errcode": 0, "errmsg": "ok"}
        payload = mock_post.call_args.kwargs["json"]
        assert payload["msgtype"] == "markdown"
        assert payload["markdown"]["content"] == "# Hello"

    def test_send_markdown_errcode_nonzero_raises(self):
        sender = WeComSender("https://example.com/webhook")
        mock_response = MagicMock()
        mock_response.json.return_value = {"errcode": 93000, "errmsg": "invalid webhook"}
        with patch(
            "retail_briefing.wecom_sender.requests.post",
            return_value=mock_response,
        ):
            with pytest.raises(WeComError) as exc_info:
                sender.send_markdown("test")

        assert exc_info.value.errcode == 93000
        assert exc_info.value.errmsg == "invalid webhook"

    def test_send_markdown_http_error_raises(self):
        sender = WeComSender("https://example.com/webhook")
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("HTTP 500")
        with patch(
            "retail_briefing.wecom_sender.requests.post",
            return_value=mock_response,
        ):
            with pytest.raises(Exception, match="HTTP 500"):
                sender.send_markdown("test")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /c/<your-user>/projects/retail-briefing
pytest tests/test_wecom_sender.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'retail_briefing.wecom_sender'`.

- [ ] **Step 3: Write minimal implementation**

File: `<your-user>\projects\retail-briefing\src\retail_briefing\wecom_sender.py`

```python
"""企微机器人 webhook sender."""

from __future__ import annotations

import requests


class WeComError(Exception):
    def __init__(self, errcode: int, errmsg: str):
        super().__init__(f"WeCom webhook error {errcode}: {errmsg}")
        self.errcode = errcode
        self.errmsg = errmsg


class WeComSender:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send_markdown(self, content: str) -> dict:
        payload = {"msgtype": "markdown", "markdown": {"content": content}}
        response = requests.post(self.webhook_url, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        if data.get("errcode", 0) != 0:
            raise WeComError(data["errcode"], data.get("errmsg", ""))
        return data
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /c/<your-user>/projects/retail-briefing
pytest tests/test_wecom_sender.py -v
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
cd /c/<your-user>/projects/retail-briefing
git add src/retail_briefing/wecom_sender.py tests/test_wecom_sender.py
git commit -m "feat(wecom): add markdown webhook sender + WeComError"
```

---

## Task 5: `briefing.py` — prompt + orchestration

**Files:**
- Create: `<your-user>\projects\retail-briefing\src\retail_briefing\briefing.py`
- Create: `<your-user>\projects\retail-briefing\tests\test_briefing.py`

- [ ] **Step 1: Write the failing test**

File: `<your-user>\projects\retail-briefing\tests\test_briefing.py`

```python
from datetime import date
from unittest.mock import MagicMock

from retail_briefing.briefing import format_for_wecom, generate_briefing


class TestGenerateBriefing:
    def test_calls_chat_with_system_and_user_messages(self):
        client = MagicMock()
        client.chat.return_value = "# Test briefing"

        result = generate_briefing(client, date(2026, 5, 4))

        assert result == "# Test briefing"
        client.chat.assert_called_once()
        messages = client.chat.call_args.args[0]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "2026-05-04" in messages[1]["content"]

    def test_system_prompt_includes_standard_pool(self):
        client = MagicMock()
        client.chat.return_value = "ok"
        generate_briefing(client, date(2026, 5, 4))

        system = client.chat.call_args.args[0][0]["content"]
        # Spot-check key targets from the V1 spec pool
        for name in ["<retailer>", "山姆", "Costco", "<region-1>", "<region-2>"]:
            assert name in system, f"system prompt missing {name!r}"

    def test_system_prompt_includes_disclaimer(self):
        client = MagicMock()
        client.chat.return_value = "ok"
        generate_briefing(client, date(2026, 5, 4))

        system = client.chat.call_args.args[0][0]["content"]
        assert "来源占位符" in system or "占位符" in system


class TestFormatForWecom:
    def test_passthrough_short_briefing(self):
        text = "# 短早报\n\n内容很短"
        assert format_for_wecom(text) == text

    def test_truncates_long_briefing(self):
        text = "x" * 5000
        result = format_for_wecom(text)
        assert len(result) <= 4100  # 4000 + truncate marker
        assert "(truncated)" in result
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /c/<your-user>/projects/retail-briefing
pytest tests/test_briefing.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'retail_briefing.briefing'`.

- [ ] **Step 3: Write minimal implementation**

File: `<your-user>\projects\retail-briefing\src\retail_briefing\briefing.py`

```python
"""Briefing prompt + generation orchestration."""

from __future__ import annotations

from datetime import date

from retail_briefing.deepseek_client import DeepSeekClient


SYSTEM_PROMPT = """You are a domain-specific briefing editor.

# Task
Generate a daily briefing for management.

# Watchlist (<N> companies)
(placeholder — original prompt content redacted for public release)

# Briefing structure (≤ 800 chars)
(placeholder — original structure redacted for public release)

# Local weighting
(placeholder)

# Data authenticity disclaimer
γ-phase uses placeholder content; DeepSeek fabricates reasonable items,
each marked as "non-real news".
"""

FEW_SHOT_EXAMPLE = """Example briefing format (redacted for public release).
"""


def generate_briefing(client: DeepSeekClient, today: date) -> str:
    """Call DeepSeek to generate a briefing for the given date.

    Returns the markdown content as-is from the model.
    """
    user_prompt = f"请生成 {today.isoformat()} 的早报，遵循上面的结构、字数限制和免责声明。"
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + "\n\n" + FEW_SHOT_EXAMPLE},
        {"role": "user", "content": user_prompt},
    ]
    return client.chat(messages)


def format_for_wecom(briefing_md: str) -> str:
    """Trim briefing markdown to fit WeCom limits.

    WeCom markdown messages have a 4096-char limit. We use 4000 as a safety margin.
    γ-phase passthrough: DeepSeek output is already in supported markdown subset.
    """
    if len(briefing_md) > 4000:
        return briefing_md[:4000] + "\n\n... (truncated)"
    return briefing_md
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /c/<your-user>/projects/retail-briefing
pytest tests/test_briefing.py -v
```

Expected: 5 PASS.

- [ ] **Step 5: Run all tests to verify suite still green**

```bash
cd /c/<your-user>/projects/retail-briefing
pytest -v
```

Expected: 14 PASS total (3 config + 3 deepseek + 3 wecom + 5 briefing).

- [ ] **Step 6: Commit**

```bash
cd /c/<your-user>/projects/retail-briefing
git add src/retail_briefing/briefing.py tests/test_briefing.py
git commit -m "feat(briefing): add prompt + generate_briefing + format_for_wecom"
```

---

## Task 6: `cli.py` + `__main__.py` — argparse entry

**Files:**
- Create: `<your-user>\projects\retail-briefing\src\retail_briefing\cli.py`
- Create: `<your-user>\projects\retail-briefing\src\retail_briefing\__main__.py`
- Create: `<your-user>\projects\retail-briefing\tests\test_cli.py`

- [ ] **Step 1: Write the failing test**

File: `<your-user>\projects\retail-briefing\tests\test_cli.py`

```python
from unittest.mock import MagicMock, patch

import pytest

from retail_briefing.cli import main
from retail_briefing.config import Config


@pytest.fixture
def fake_config():
    return Config(deepseek_api_key="sk-test", wecom_webhook_url="https://example.com/hook")


class TestCli:
    def test_generate_prints_briefing_no_send(self, capsys, fake_config):
        with patch("retail_briefing.cli.Config.from_env", return_value=fake_config), \
             patch("retail_briefing.cli.generate_briefing", return_value="# briefing"), \
             patch("retail_briefing.cli.WeComSender") as mock_sender_cls:
            rc = main(["generate"])

        assert rc == 0
        out = capsys.readouterr().out
        assert "# briefing" in out
        mock_sender_cls.assert_not_called()

    def test_generate_with_send_pushes_to_wecom(self, capsys, fake_config):
        mock_sender = MagicMock()
        mock_sender.send_markdown.return_value = {"errcode": 0, "errmsg": "ok"}
        with patch("retail_briefing.cli.Config.from_env", return_value=fake_config), \
             patch("retail_briefing.cli.generate_briefing", return_value="# briefing"), \
             patch("retail_briefing.cli.WeComSender", return_value=mock_sender):
            rc = main(["generate", "--send"])

        assert rc == 0
        mock_sender.send_markdown.assert_called_once_with("# briefing")

    def test_send_text_pushes_raw(self, fake_config):
        mock_sender = MagicMock()
        mock_sender.send_markdown.return_value = {"errcode": 0, "errmsg": "ok"}
        with patch("retail_briefing.cli.Config.from_env", return_value=fake_config), \
             patch("retail_briefing.cli.WeComSender", return_value=mock_sender):
            rc = main(["send", "--text", "hello"])

        assert rc == 0
        mock_sender.send_markdown.assert_called_once_with("hello")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /c/<your-user>/projects/retail-briefing
pytest tests/test_cli.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'retail_briefing.cli'`.

- [ ] **Step 3: Write minimal `cli.py`**

File: `<your-user>\projects\retail-briefing\src\retail_briefing\cli.py`

```python
"""CLI entry: generate / send / generate --send."""

from __future__ import annotations

import argparse
import sys
from datetime import date

from retail_briefing.briefing import format_for_wecom, generate_briefing
from retail_briefing.config import Config
from retail_briefing.deepseek_client import DeepSeekClient
from retail_briefing.wecom_sender import WeComSender


def _cmd_generate(config: Config, send: bool) -> int:
    client = DeepSeekClient(config.deepseek_api_key)
    briefing = generate_briefing(client, date.today())
    formatted = format_for_wecom(briefing)
    print(formatted)
    if send:
        sender = WeComSender(config.wecom_webhook_url)
        result = sender.send_markdown(formatted)
        print(f"\n[sent to wecom] {result}", file=sys.stderr)
    return 0


def _cmd_send(config: Config, text: str) -> int:
    sender = WeComSender(config.wecom_webhook_url)
    result = sender.send_markdown(text)
    print(f"sent: {result}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="retail_briefing")
    sub = parser.add_subparsers(dest="cmd", required=True)

    gen = sub.add_parser("generate", help="Generate briefing from DeepSeek")
    gen.add_argument("--send", action="store_true", help="Also push to WeCom")

    snd = sub.add_parser("send", help="Send raw text to WeCom")
    snd.add_argument("--text", required=True)

    args = parser.parse_args(argv)
    config = Config.from_env()

    if args.cmd == "generate":
        return _cmd_generate(config, send=args.send)
    if args.cmd == "send":
        return _cmd_send(config, args.text)
    return 1
```

- [ ] **Step 4: Write `__main__.py`**

File: `<your-user>\projects\retail-briefing\src\retail_briefing\__main__.py`

```python
import sys

from retail_briefing.cli import main

sys.exit(main())
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /c/<your-user>/projects/retail-briefing
pytest tests/test_cli.py -v
```

Expected: 3 PASS.

- [ ] **Step 6: Run full suite to verify everything green**

```bash
cd /c/<your-user>/projects/retail-briefing
pytest -v
```

Expected: 17 PASS total (3 config + 3 deepseek + 3 wecom + 5 briefing + 3 cli).

- [ ] **Step 7: Commit**

```bash
cd /c/<your-user>/projects/retail-briefing
git add src/retail_briefing/cli.py src/retail_briefing/__main__.py tests/test_cli.py
git commit -m "feat(cli): add generate / send / generate --send subcommands"
```

---

## Task 7: Migrate credentials from cc-assitant to retail-briefing

**Files:**
- Create: `<your-user>\projects\retail-briefing\.env`

- [ ] **Step 1: Read the two credentials from cc-assitant `.env`**

```bash
grep -E "^(DEEPSEEK_API_KEY|RETAIL_BRIEFING_WECOM_WEBHOOK)=" /c/<your-user>/projects/cc-assitant/.env
```

Expected: two lines, each `KEY=value` with the actual secrets.

- [ ] **Step 2: Write `.env` to retail-briefing root**

File: `<your-user>\projects\retail-briefing\.env`

(Copy the two lines from Step 1 verbatim. Do NOT inline the actual secrets in this plan.)

```
DEEPSEEK_API_KEY=<paste from cc-assitant/.env>
RETAIL_BRIEFING_WECOM_WEBHOOK=<paste from cc-assitant/.env>
```

- [ ] **Step 3: Verify `.env` is gitignored**

```bash
cd /c/<your-user>/projects/retail-briefing
git check-ignore -v .env
```

Expected: output like `.gitignore:1:.env  .env` confirming `.env` is ignored. **Do NOT commit `.env`.**

- [ ] **Step 4: Verify `Config.from_env()` loads cleanly**

```bash
cd /c/<your-user>/projects/retail-briefing
python -c "from retail_briefing.config import Config; c = Config.from_env(); print('api_key starts with:', c.deepseek_api_key[:6]); print('webhook host:', c.wecom_webhook_url[:40])"
```

Expected: prints `api_key starts with: sk-...` and `webhook host: https://qyapi.weixin.qq.com/cgi-bin/webhook...`

---

## Task 8: Manual smoke tests

These are NOT automated — run by hand to verify the whole stack works end-to-end. No commits.

- [ ] **Step 1: Smoke `generate` (DeepSeek call only)**

```bash
cd /c/<your-user>/projects/retail-briefing
python -m retail_briefing generate
```

Expected: stdout shows a markdown briefing roughly matching the few-shot format (五块结构 / 含<region-1>/<region-2> / 含【来源占位符】 / ≤ 800 字)。 If 401 → re-check `DEEPSEEK_API_KEY`. If empty → check DeepSeek model name.

- [ ] **Step 2: Smoke `send --text`**

```bash
cd /c/<your-user>/projects/retail-briefing
python -m retail_briefing send --text "[smoke] retail-briefing γ from new project (2026-05-04)"
```

Expected: stdout prints `sent: {'errcode': 0, 'errmsg': 'ok'}`. **Verify on phone** that the 「briefing-test」 WeCom group receives the test message.

- [ ] **Step 3: Smoke `generate --send` (full pipeline)**

```bash
cd /c/<your-user>/projects/retail-briefing
python -m retail_briefing generate --send
```

Expected: stdout shows briefing markdown; stderr shows `[sent to wecom] {'errcode': 0, 'errmsg': 'ok'}`. **Verify on phone** that the 「briefing-test」 group receives the briefing.

- [ ] **Step 4: If any smoke fails, debug before continuing**

Common issues:
- `RuntimeError: DEEPSEEK_API_KEY not set` → `.env` not at project root, or `Config.from_env()` is looking in the wrong place
- `WeComError: 93000 invalid webhook` → webhook key revoked / typo in `.env`
- DeepSeek 401 → API key revoked / typo
- DeepSeek timeout → bump timeout in `deepseek_client.py:DeepSeekClient.chat`

Do not commit any debugging changes until smoke is green.

---

## Task 9: Update task card 003 + create project card

**Files:**
- Modify: `<your-user>\projects\cc-assitant\tasks\doing\<original-task>.md` (append final cycle, then move to done/)
- Create: `<your-user>\projects\cc-assitant\tasks\projects\retail-briefing.md`

- [ ] **Step 1: Append final AI reply to 003**

Edit `cc-assitant\tasks\doing\<original-task>.md` — replace the last `### [我] 2026-05-03 23:19` placeholder line and append:

```markdown
### [AI] 2026-05-04 — γ 骨架完工

✅ 选了 (c)。本地骨架在 `<your-user>\projects\retail-briefing\` 起好了，独立 git，跟 cc-assitant 平级（不是嵌套），符合现有 16 个项目的组织惯例。

**已完成：**
- 项目结构：`src/retail_briefing/{config,deepseek_client,wecom_sender,briefing,cli,__main__}.py`
- 测试：17 个 unit test 全绿（mock HTTP，不真调外部）
- CLI：`python -m retail_briefing generate / send --text / generate --send` 三条命令
- 凭据：从 `cc-assitant\.env` 复制到 `retail-briefing\.env`（cc-assitant 那边保留不删）
- 手动 smoke：generate / send / generate --send 都跑通，企微测试群收到推送
- 项目卡：`cc-assitant\tasks\projects\retail-briefing.md` 已建

**已知边界（明确不做）：** APScheduler / SQLite / 真新闻数据源 / 远程部署。这些进 W1+。

**下一步：** 这张 003 卡可以挪到 `done/`。后续 W1（<source-A> RSS + <source-B><retailer>公告 + SQLite 入库）通过 `tasks/projects/retail-briefing.md` 的 checkbox 派单出来。

设计 + 实现计划：
- spec：`docs/superpowers/specs/2026-05-04-retail-briefing-gamma-skeleton-design.md`
- plan：`docs/superpowers/plans/2026-05-04-retail-briefing-gamma-skeleton.md`
```

- [ ] **Step 2: Move 003 from doing/ to done/**

```bash
cd /c/<your-user>/projects/cc-assitant
mv "tasks/doing/<original-task>.md" "tasks/done/<original-task>.md"
```

- [ ] **Step 3: Create the project card**

File: `<your-user>\projects\cc-assitant\tasks\projects\retail-briefing.md`

```markdown
---
type: project
slug: "retail-briefing"
status: active
repo_path: "../../retail-briefing"
priority: P1
tags: [news, briefing, retail]
last_touched: 2026-05-04
---
# retail-briefing

## 一句話
每日/每周 domain-specific 简报自动推送（DeepSeek 生成 + 企微推送）。

## 現在的焦點
2026-05-04 γ 骨架落地：独立 Python 项目，5 个核心模块 + 17 个 unit test 全绿，三条 CLI 命令（generate / send / generate --send）跑通，企微测试群收到 placeholder 早报。下一步等 W1 数据源接入。

## 下一步 (Next actions)
- [ ] W1 数据源接入：<source-A> RSS + <source-B><retailer>公告 + SQLite 入库
- [ ] W2 真数据接通后做 Haiku-vs-DeepSeek 抉择（成本 + 中文质感对比）
- [ ] W3 <region-1>+<region-2>本地源（华商网 + 山西新闻网/<region-2>日报）
- [ ] W4 周报模板（周一 09:00 节奏）
- [ ] APScheduler + cron 08:30 早报定时（W4 起需要）
- [ ] 远程部署到 `/opt/<deploy>/retail-briefing/`（要单独确认）

## 決策記錄
- 2026-05-04 路径选独立平级 `projects/retail-briefing/`（非嵌套 `cc-assitant/projects/`）—— 符合现有 16 个项目惯例 + 独立 git/部署
- 2026-05-04 LLM 选 DeepSeek（V1 规格写 Haiku 4.5，但实际验证用的 DeepSeek，~$0.0003/次跑通）—— Haiku-vs-DeepSeek 真抉择留给 W2
- 2026-05-04 scope 选 γ（骨架 + DeepSeek client + WeCom sender）—— α 太空、β 留中间态
- 2026-05-04 凭据迁移：从 `cc-assitant\.env` 复制两条到 `retail-briefing\.env`，cc-assitant 那边保留不删（短期冗余无害）
- 2026-05-04 本地 git，不立即推远程 —— 等代码稳定再决定 GitHub 还是只本地

## 待解決的問題
- W1 数据源去重三层（URL → SimHash → MinHash）的具体阈值要实测
- 企微 markdown 子集兼容性：`format_for_wecom` 目前是 passthrough + 长度截断，没做"不支持的语法清洗"；W2 真数据后看效果再决定
- DeepSeek 偶发慢响应没观测过 —— 当前 60s timeout 是猜的

## 回顧 / 暫停原因
(active，刚 ship γ 骨架。)
```

- [ ] **Step 4: Commit cc-assitant changes**

```bash
cd /c/<your-user>/projects/cc-assitant
git add tasks/doing/<original-task>.md tasks/done/<original-task>.md tasks/projects/retail-briefing.md
git commit -m "$(cat <<'EOF'
docs(retail-briefing): close 003 task + add project card

γ skeleton shipped at <your-user>\projects\retail-briefing\
(independent peer to cc-assitant). 003 task moved to done/, project
card added to tasks/projects/.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Final Verification

- [ ] **Step 1: Run full retail-briefing suite one more time**

```bash
cd /c/<your-user>/projects/retail-briefing
pytest -v
```

Expected: 17 PASS, 0 FAIL.

- [ ] **Step 2: Verify retail-briefing git history**

```bash
cd /c/<your-user>/projects/retail-briefing
git log --oneline
```

Expected: 6 commits (scaffold / config / deepseek / wecom / briefing / cli).

- [ ] **Step 3: Verify cc-assitant has the closing commit**

```bash
cd /c/<your-user>/projects/cc-assitant
git log --oneline -3
```

Expected: top commit is `docs(retail-briefing): close 003 task + add project card`; second is `docs(specs): retail-briefing γ skeleton design`.

- [ ] **Step 4: Confirm `.env` not committed**

```bash
cd /c/<your-user>/projects/retail-briefing
git ls-files | grep -E "^\.env$"
```

Expected: empty output (`.env` should NOT be tracked). If `.env` shows up, run `git rm --cached .env` and amend.

---

## Self-Review Notes

- **Spec coverage:** Every section of the design doc is mapped to a task — file structure (Task 1), modules (Tasks 2-6), credential migration (Task 7), git strategy (Task 1 step 8 + 9), project card (Task 9), tests (per-task TDD + Final Verification), manual smoke (Task 8), "不做" boundary respected (no scheduler/DB/real data sources/remote deploy).
- **Placeholder scan:** Cleared. The only `<paste from cc-assitant/.env>` placeholders are in Task 7 step 2 — intentional, since secrets must not be inlined in a committed plan. Engineer reads them from cc-assitant's actual `.env` at execution time.
- **Type consistency:** `Config` constructor accepts `deepseek_api_key` + `wecom_webhook_url` (positional/kwargs both work via dataclass) consistently across config/cli/test files. `DeepSeekClient.chat(messages, model=...)`, `WeComSender.send_markdown(content)`, `generate_briefing(client, today)`, `format_for_wecom(briefing_md)` — names + signatures match between implementation and tests in every task.
