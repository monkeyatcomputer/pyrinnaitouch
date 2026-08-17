"""Integration-style tests for the threaded bridge connection."""

from queue import SimpleQueue
import socket
import threading

import pytest

from pyrinnaitouch.pollconnection import RinnaiConnectionState, RinnaiPollConnection
from pyrinnaitouch.protocol import HELLO


STATUS = b'[{"SYST":{}},{"HGOM":{}}]'


def frame(sequence: int) -> bytes:
    """Build a minimal status frame."""
    return f"N{sequence:06d}".encode("ascii") + STATUS


def test_command_completes_only_after_matching_ack():
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    received = []

    def bridge() -> None:
        client, _address = listener.accept()
        with client:
            client.sendall(HELLO + frame(254))
            received.append(client.recv(4096))
            client.sendall(frame(255))
        listener.close()

    bridge_thread = threading.Thread(target=bridge)
    bridge_thread.start()

    connection = RinnaiPollConnection("127.0.0.1", SimpleQueue(), port=port)
    try:
        connection.start_thread()
        assert connection.wait_ready(2)
        assert connection.socket_state() == RinnaiConnectionState.CONNECTED

        result = connection.send_command('{"HGOM":{"OOP":{"ST":"N"}}}')

        assert not result.done()
        assert result.result(timeout=2)
        assert received == [
            b'N000255{"HGOM":{"OOP":{"ST":"N"}}}'
        ]
    finally:
        connection.stop_thread()
        bridge_thread.join(2)


def test_command_is_rejected_before_status_stream_is_ready():
    connection = RinnaiPollConnection("not-ready.test", SimpleQueue())
    try:
        result = connection.send_command("NA")

        assert result.done()
        assert isinstance(result.exception(), ConnectionError)
    finally:
        connection.stop_thread()


def test_duplicate_connection_rejection_does_not_leak_client_count():
    first = RinnaiPollConnection("duplicate.test", SimpleQueue())
    try:
        with pytest.raises(RuntimeError):
            RinnaiPollConnection("duplicate.test", SimpleQueue())
        assert RinnaiPollConnection.clients["duplicate.test"] == 1
    finally:
        first.stop_thread()

    assert RinnaiPollConnection.clients["duplicate.test"] == 0
