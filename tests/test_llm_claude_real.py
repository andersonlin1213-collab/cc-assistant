"""Real Anthropic API smoke test.

Skipped automatically when ANTHROPIC_API_KEY is not set. To run locally:
  ANTHROPIC_API_KEY=sk-... uv run pytest tests/test_llm_claude_real.py -v

Cost: a single short round-trip (≤ 100 input tokens, ≤ 64 output tokens).
"""

import os

import pytest

from src.agent.llm.claude import ClaudeClient
from src.agent.llm.types import Message, TextBlock


_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
pytestmark = pytest.mark.skipif(
    not _KEY.startswith("sk-ant-"),
    reason="ANTHROPIC_API_KEY not set to a real key (must start with sk-ant-)",
)


async def test_real_api_round_trip():
    client = ClaudeClient(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = await client.chat(
        messages=[
            Message(role="system", content="Reply with exactly one word."),
            Message(role="user", content="Say 'pong'."),
        ],
        max_tokens=64,
    )
    assert resp.stop_reason in ("end_turn", "stop_sequence")
    assert len(resp.content) >= 1
    text = " ".join(b.text for b in resp.content if isinstance(b, TextBlock))
    assert "pong" in text.lower()
    # Caching should produce non-zero values on the second call, but for a single
    # round-trip we just verify the field exists and is non-negative.
    assert resp.usage.input_tokens > 0
    assert resp.usage.output_tokens > 0
