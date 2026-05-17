from src.agent.cycle_state import CycleState


def test_cycle_state_defaults():
    s = CycleState()
    assert s.marked_complete is False
    assert s.marked_blocked is False
    assert s.complete_reason == ""
    assert s.blocked_reason == ""


def test_cycle_state_mark_complete():
    s = CycleState()
    s.mark_complete("all good")
    assert s.marked_complete is True
    assert s.complete_reason == "all good"


def test_cycle_state_mark_blocked():
    s = CycleState()
    s.mark_blocked("need user input")
    assert s.marked_blocked is True
    assert s.blocked_reason == "need user input"


def test_cycle_state_both_marks_independent():
    """Both flags can technically be set; orchestrator decides which wins."""
    s = CycleState()
    s.mark_complete("done")
    s.mark_blocked("but also blocked?")
    assert s.marked_complete is True
    assert s.marked_blocked is True
