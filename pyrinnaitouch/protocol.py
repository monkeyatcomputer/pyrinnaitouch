"""Low-level N-BW2 stream framing and sequence handling."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any


HELLO = b"*HELLO*"
MAX_RECEIVE_BUFFER = 64 * 1024
SEQUENCE_MODULUS = 256

_HEADER = re.compile(br"N(?P<sequence>\d{6})(?=\[)")
_PARTIAL_HEADER = re.compile(br"N\d{0,6}")
_SEQUENCE_PREFIX = re.compile(br"N\d{6}")


class ProtocolError(ValueError):
    """Raised when the bridge sends an invalid or excessive stream."""


@dataclass(frozen=True)
class StatusFrame:
    """A decoded status frame received from the bridge."""

    sequence: int
    payload: list[dict[str, Any]]


def next_sequence(sequence: int) -> int:
    """Return the next N-BW2 sequence number, wrapping 255 to zero."""
    if not 0 <= sequence < SEQUENCE_MODULUS:
        raise ValueError(f"Sequence number out of range: {sequence}")
    return (sequence + 1) % SEQUENCE_MODULUS


def encode_command(sequence: int, command: str) -> bytes:
    """Encode a command using the bridge's six-digit sequence header."""
    if not 0 <= sequence < SEQUENCE_MODULUS:
        raise ValueError(f"Sequence number out of range: {sequence}")
    return f"N{sequence:06d}{command}".encode("ascii")


class StatusFrameParser:
    """Incrementally parse HELLO and JSON status frames from a TCP stream."""

    def __init__(self, max_buffer_size: int = MAX_RECEIVE_BUFFER) -> None:
        self._buffer = bytearray()
        self._max_buffer_size = max_buffer_size
        self.hello_received = False

    @property
    def buffered_bytes(self) -> int:
        """Return the number of bytes awaiting a complete frame."""
        return len(self._buffer)

    def reset(self) -> None:
        """Reset all state for a new TCP connection."""
        self._buffer.clear()
        self.hello_received = False

    def feed(self, data: bytes) -> list[StatusFrame]:
        """Add bytes and return every complete status frame now available."""
        if data:
            self._buffer.extend(data)
        if len(self._buffer) > self._max_buffer_size:
            self.reset()
            raise ProtocolError("Receive buffer exceeded maximum size")

        frames: list[StatusFrame] = []
        while self._buffer:
            if self._buffer.startswith(HELLO):
                del self._buffer[: len(HELLO)]
                self.hello_received = True
                continue

            if len(self._buffer) < 7:
                break

            if (
                len(self._buffer) >= 8
                and _SEQUENCE_PREFIX.match(self._buffer)
                and self._buffer[7] != ord("[")
            ):
                self.reset()
                raise ProtocolError("Status header is not followed by a JSON list")

            header = _HEADER.match(self._buffer)
            if header is None:
                if _PARTIAL_HEADER.fullmatch(self._buffer):
                    break
                if self._discard_to_next_marker():
                    continue
                break

            json_start = header.end()
            try:
                text = bytes(self._buffer[json_start:]).decode("ascii")
            except UnicodeDecodeError as err:
                self.reset()
                raise ProtocolError("Status stream is not ASCII") from err

            try:
                payload, json_end = json.JSONDecoder().raw_decode(text)
            except json.JSONDecodeError:
                next_header = _HEADER.search(self._buffer, json_start + 1)
                if next_header is not None:
                    del self._buffer[: next_header.start()]
                    continue
                break

            if not isinstance(payload, list) or not payload or not all(
                isinstance(item, dict) for item in payload
            ):
                self.reset()
                raise ProtocolError("Status payload must be a non-empty list of objects")

            sequence = int(header.group("sequence"))
            if not 0 <= sequence < SEQUENCE_MODULUS:
                self.reset()
                raise ProtocolError(f"Status sequence is out of range: {sequence}")

            frames.append(
                StatusFrame(
                    sequence=sequence,
                    payload=payload,
                )
            )
            del self._buffer[: json_start + json_end]

        return frames

    def _discard_to_next_marker(self) -> bool:
        """Discard noise before a plausible HELLO or status marker."""
        hello_index = self._buffer.find(HELLO, 1)
        header = _HEADER.search(self._buffer, 1)
        candidates = [
            index
            for index in (
                hello_index if hello_index >= 0 else None,
                header.start() if header is not None else None,
            )
            if index is not None
        ]
        if candidates:
            del self._buffer[: min(candidates)]
            return True

        # Retain a possible partial marker at the end of the buffer.
        keep = min(len(self._buffer), max(len(HELLO) - 1, 7))
        if keep:
            del self._buffer[:-keep]
        else:
            self._buffer.clear()
        return False
