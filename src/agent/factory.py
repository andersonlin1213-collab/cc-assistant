from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from src.agent.llm.base import LLMClient
from src.agent.orchestrator import Orchestrator
from src.dispatcher.coordinator import DispatcherCoordinator
from src.tools import ALL_TOOLS


def build_orchestrator_and_coordinator(
    tasks_dir: Path,
    skills_dir: Path,
    logs_dir: Path,
    llm: LLMClient,
    debounce_seconds: float = DispatcherCoordinator.DEFAULT_DEBOUNCE_SECONDS,
    poll_interval_seconds: float = DispatcherCoordinator.DEFAULT_POLL_INTERVAL_SECONDS,
    tools: Optional[list] = None,
) -> tuple[Orchestrator, DispatcherCoordinator]:
    """Wire Orchestrator + DispatcherCoordinator into a runnable pair.

    Two-step construction:
      1. Build the coordinator with placeholder callbacks (Orchestrator depends on
         coordinator.suppress_self).
      2. Build the orchestrator using that suppress_self.
      3. Re-wire the coordinator's callbacks to real orchestrator methods via the
         public `set_callbacks` API.
    """
    if tools is None:
        tools = [cls() for cls in ALL_TOOLS]

    coordinator = DispatcherCoordinator(
        tasks_dir=tasks_dir,
        on_task_change=lambda p: None,
        on_poll=lambda: None,
        debounce_seconds=debounce_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )

    orchestrator = Orchestrator(
        tasks_dir=tasks_dir,
        skills_dir=skills_dir,
        logs_dir=logs_dir,
        llm=llm,
        tools=tools,
        suppress_self=coordinator.suppress_self,
    )

    from src.board.project_handler import process_project_card

    def _routed_on_change(path):
        # Route project card events to project_handler (no LLM); everything
        # else goes to the orchestrator's run_cycle.
        if path.parent.name == "projects" and path.parent.parent == tasks_dir:
            try:
                process_project_card(
                    path,
                    tasks_dir=tasks_dir,
                    logs_dir=logs_dir,
                    suppress_self=coordinator.suppress_self,
                )
            except Exception:  # pylint: disable=broad-except
                # Project card errors must not kill the watcher thread.
                import logging
                logging.getLogger(__name__).exception(
                    "project_handler failed for %s", path
                )
            return
        _run_async(orchestrator.run_cycle(path))

    coordinator.set_callbacks(
        on_task_change=_routed_on_change,
        on_poll=lambda: _run_async(orchestrator.on_poll()),
    )

    return orchestrator, coordinator


def build_orchestrator_only(
    tasks_dir: Path,
    skills_dir: Path,
    logs_dir: Path,
    llm: LLMClient,
    tools: Optional[list] = None,
) -> Orchestrator:
    """Build an Orchestrator without a coordinator.

    Used for one-shot paths (cc-assistant run --dry-run, cc-assistant status)
    that do not need watchdog/scheduler. `suppress_self` is a no-op context manager.
    """
    if tools is None:
        tools = [cls() for cls in ALL_TOOLS]

    return Orchestrator(
        tasks_dir=tasks_dir,
        skills_dir=skills_dir,
        logs_dir=logs_dir,
        llm=llm,
        tools=tools,
        suppress_self=_noop_suppress,
    )


@contextmanager
def _noop_suppress() -> Iterator[None]:
    yield


def _run_async(coro) -> None:
    """Run an async coroutine to completion in a fresh event loop.

    The watcher's callback runs in the watchdog observer thread (sync); the
    scheduler's callback runs in an APScheduler worker thread (sync). We need
    to drive an async coroutine to completion from sync code, which means a
    fresh event loop per invocation. This is fine for the cycle-per-event
    pattern (Completion Promise) — no ambient loop is shared across cycles.
    """
    import asyncio

    asyncio.run(coro)
