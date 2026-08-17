"""Tests for N-BW2 stream framing and sequence handling."""

import pytest

from pyrinnaitouch.protocol import (
    HELLO,
    ProtocolError,
    StatusFrameParser,
    encode_command,
    next_sequence,
)


STATUS = b'[{"SYST":{"CFG":{"MTSP":"N"}}},{"HGOM":{"OOP":{"ST":"F"}}}]'


def frame(sequence: int, payload: bytes = STATUS) -> bytes:
    """Build a status frame used by parser tests."""
    return f"N{sequence:06d}".encode("ascii") + payload


@pytest.mark.parametrize(
    ("current", "expected"),
    [(0, 1), (1, 2), (254, 255), (255, 0)],
)
def test_next_sequence(current, expected):
    assert next_sequence(current) == expected


@pytest.mark.parametrize("invalid", [-1, 256])
def test_sequence_range_is_validated(invalid):
    with pytest.raises(ValueError):
        next_sequence(invalid)
    with pytest.raises(ValueError):
        encode_command(invalid, "NA")


def test_encode_command_uses_six_digit_header():
    assert encode_command(255, "NA") == b"N000255NA"


def test_parser_accepts_fragmented_hello_and_status():
    parser = StatusFrameParser()

    assert parser.feed(HELLO[:3]) == []
    assert parser.feed(HELLO[3:] + frame(17)[:11]) == []
    frames = parser.feed(frame(17)[11:])

    assert parser.hello_received
    assert len(frames) == 1
    assert frames[0].sequence == 17
    assert frames[0].payload[0]["SYST"]["CFG"]["MTSP"] == "N"


def test_parser_retains_a_complete_header_until_json_arrives():
    parser = StatusFrameParser()

    assert parser.feed(b"N000017") == []
    frames = parser.feed(STATUS)

    assert [item.sequence for item in frames] == [17]


def test_parser_returns_multiple_coalesced_frames():
    parser = StatusFrameParser()

    frames = parser.feed(HELLO + frame(254) + frame(255) + frame(0))

    assert [item.sequence for item in frames] == [254, 255, 0]


def test_parser_handles_brackets_inside_json_strings():
    parser = StatusFrameParser()
    payload = b'[{"SYST":{"CFG":{"ZA":"Living [front]"}}}]'

    frames = parser.feed(frame(3, payload))

    assert frames[0].payload[0]["SYST"]["CFG"]["ZA"] == "Living [front]"


def test_parser_recovers_from_noise_and_a_truncated_frame():
    parser = StatusFrameParser()

    frames = parser.feed(b"noiseN000004[{bad" + frame(5))

    assert [item.sequence for item in frames] == [5]


def test_parser_rejects_excessive_incomplete_input():
    parser = StatusFrameParser(max_buffer_size=32)

    with pytest.raises(ProtocolError):
        parser.feed(b"N000001[" + b"x" * 32)

    assert parser.buffered_bytes == 0


@pytest.mark.parametrize("payload", [b"[]", b"{}"])
def test_parser_rejects_invalid_status_shapes(payload):
    parser = StatusFrameParser()

    with pytest.raises(ProtocolError):
        parser.feed(frame(1, payload))


def test_parser_rejects_out_of_range_status_sequence():
    parser = StatusFrameParser()

    with pytest.raises(ProtocolError):
        parser.feed(b"N000256" + STATUS)
