"""Tests for event dispatch."""

from pyrinnaitouch.event import Event


def test_failing_handler_does_not_block_other_handlers():
    """One consumer must not terminate the status polling thread."""
    event = Event()
    received = []

    def failing_handler(_value):
        raise RuntimeError("boom")

    event += failing_handler
    event += received.append

    event("status")

    assert received == ["status"]
