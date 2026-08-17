"""Tests for status readiness across initial and repeated connections."""

import threading

import pytest

from pyrinnaitouch.system import RinnaiSystem
from pyrinnaitouch.system_status import RinnaiSystemStatus


class FakeConnection:
    """Minimal connection that becomes ready when started."""

    def __init__(self, status_event: threading.Event, publish_status: bool) -> None:
        self.ready = False
        self.started = False
        self.status_event = status_event
        self.publish_status = publish_status

    def start_thread(self) -> None:
        self.started = True
        self.ready = True
        if self.publish_status:
            self.status_event.set()

    def wait_ready(self, _timeout=None) -> bool:
        return self.ready


def make_system(publish_status: bool) -> tuple[RinnaiSystem, FakeConnection]:
    system = RinnaiSystem.__new__(RinnaiSystem)
    system._status = RinnaiSystemStatus()
    system._status_ready_event = threading.Event()
    connection = FakeConnection(system._status_ready_event, publish_status)
    system._connection = connection
    return system, connection


def test_get_status_waits_for_transport_and_parsed_status():
    system, connection = make_system(publish_status=True)

    assert system.get_status(timeout=0.1) is system._status
    assert connection.started


def test_get_status_does_not_return_a_stale_status_after_disconnect():
    system, connection = make_system(publish_status=False)
    system._status_ready_event.set()

    with pytest.raises(TimeoutError, match="parsing"):
        system.get_status(timeout=0.01)

    assert connection.started
