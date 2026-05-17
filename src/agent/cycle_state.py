from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CycleState:
    """Per-cycle scratchpad capturing control-tool calls.

    The Orchestrator constructs a fresh CycleState at the start of each cycle.
    Control tools (`mark_complete`, `mark_blocked`) mutate this state via the
    ToolBridge; the Orchestrator inspects it after the LLM loop terminates to
    decide the next TaskStatus.
    """

    marked_complete: bool = False
    marked_blocked: bool = False
    complete_reason: str = ""
    blocked_reason: str = ""

    def mark_complete(self, reason: str = "") -> None:
        self.marked_complete = True
        self.complete_reason = reason

    def mark_blocked(self, reason: str = "") -> None:
        self.marked_blocked = True
        self.blocked_reason = reason
