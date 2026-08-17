"""Tests for heating and add-on cooling schedule programming."""

import asyncio
import threading
from unittest.mock import AsyncMock

import pytest

from pyrinnaitouch.const import (
    RinnaiScheduleDay,
    RinnaiScheduleDayGroup,
    RinnaiSchedulePeriod,
    RinnaiSystemMode,
)
from pyrinnaitouch.pollconnection import RinnaiConnectionNotReadyError
from pyrinnaitouch.system import RinnaiSystem
from pyrinnaitouch.system_status import RinnaiSystemStatus
from pyrinnaitouch.topology import RinnaiTopology
from pyrinnaitouch.unit_status import RinnaiUnitStatus


def make_system(
    *,
    multi_set_point: bool,
    day_group: RinnaiScheduleDayGroup,
    zones: set[str],
) -> RinnaiSystem:
    """Create a schedule-capable system without starting its worker thread."""
    system = RinnaiSystem.__new__(RinnaiSystem)
    system._status = RinnaiSystemStatus()
    system._status.mode = RinnaiSystemMode.HEATING
    system._status.is_multi_set_point = multi_set_point
    system._status.unit_status.unit_id = "HGOM"
    system._status.unit_status.pre_sleep_enabled = True
    system._status.unit_status.schedule_day_group = day_group
    system._status.unit_status.zones = {zone: object() for zone in zones}
    system._topology = RinnaiTopology()
    system._topology.observe(
        RinnaiSystemMode.HEATING,
        multi_set_point,
        zones,
    )
    system._schedule_lock = asyncio.Lock()
    system.send_command = AsyncMock(return_value=True)
    return system


def sent_commands(system: RinnaiSystem) -> list[str]:
    """Return commands recorded by the mocked connection."""
    return [call.args[0] for call in system.send_command.await_args_list]


def test_schedule_capabilities_are_parsed_from_unit_config():
    status = RinnaiUnitStatus()

    status.set_config({"PS": "Y", "DG": "W", "ZAIS": "Y"})

    assert status.pre_sleep_enabled
    assert status.schedule_day_group == RinnaiScheduleDayGroup.WEEKDAYS_WEEKENDS
    assert set(status.zones) == {"A"}


def test_program_mtsp_zone_period():
    system = make_system(
        multi_set_point=True,
        day_group=RinnaiScheduleDayGroup.WEEKDAYS_WEEKENDS,
        zones={"A", "B"},
    )

    result = asyncio.run(
        system.set_schedule_period(
            RinnaiScheduleDay.WEEKDAYS,
            RinnaiSchedulePeriod.RETURN,
            "17:30:00",
            22,
            zone="A",
        )
    )

    assert result
    assert sent_commands(system) == [
        '{"HGOM": {"APZ": {"ZV": "A" } } }',
        '{"HGOM": {"APZ": {"WD": "Y" } } }',
        '{"HGOM": {"APZ": {"TP": "R" } } }',
        '{"HGOM": {"APZ": {"TM": "17:30" } } }',
        '{"HGOM": {"APZ": {"SP": "22" } } }',
        '{"HGOM": {"APZ": {"ZV": "N" } } }',
    ]


def test_program_single_set_point_period_and_zone_states():
    system = make_system(
        multi_set_point=False,
        day_group=RinnaiScheduleDayGroup.INDIVIDUAL,
        zones={"A", "B", "U"},
    )

    result = asyncio.run(
        system.set_schedule_period(
            RinnaiScheduleDay.MONDAY,
            RinnaiSchedulePeriod.WAKE,
            "06:00",
            20,
            enabled_zones=["A"],
        )
    )

    assert result
    assert sent_commands(system) == [
        '{"HGOM": {"APS": {"AV": "Y" } } }',
        '{"HGOM": {"APS": {"DY": "MON" } } }',
        '{"HGOM": {"APS": {"TP": "W" } } }',
        '{"HGOM": {"APS": {"TM": "06:00" } } }',
        '{"HGOM": {"APS": {"SP": "20" } } }',
        '{"HGOM": {"APS": {"ZA": "N" } } }',
        '{"HGOM": {"APS": {"ZB": "F" } } }',
        '{"HGOM": {"APS": {"AV": "N" } } }',
    ]


def test_schedule_programming_always_exits_after_failed_field_write():
    system = make_system(
        multi_set_point=True,
        day_group=RinnaiScheduleDayGroup.ALL_DAYS,
        zones={"A"},
    )
    system.send_command.side_effect = [True, True, False, True]

    result = asyncio.run(
        system.set_schedule_period(
            RinnaiScheduleDay.ALL_DAYS,
            RinnaiSchedulePeriod.SLEEP,
            "22:00",
            17,
            zone="A",
        )
    )

    assert not result
    assert sent_commands(system)[-1] == '{"HGOM": {"APZ": {"ZV": "N" } } }'


def test_schedule_day_must_match_controller_grouping():
    system = make_system(
        multi_set_point=True,
        day_group=RinnaiScheduleDayGroup.WEEKDAYS_WEEKENDS,
        zones={"A"},
    )

    with pytest.raises(ValueError, match="weekdays or weekends"):
        asyncio.run(
            system.set_schedule_period(
                RinnaiScheduleDay.MONDAY,
                RinnaiSchedulePeriod.WAKE,
                "06:00",
                20,
                zone="A",
            )
        )


def test_schedule_status_frames_are_detected():
    assert RinnaiSystem._is_schedule_status(
        [{"SYST": {}}, {"HGOM": {"APZ": {"ZV": "A"}}}]
    )
    assert not RinnaiSystem._is_schedule_status(
        [
            {"SYST": {}},
            {"HGOM": {"OOP": {"ST": "N"}, "APZ": {"ZV": "N"}}},
        ]
    )


def test_read_mtsp_schedule_collects_every_period():
    system = make_system(
        multi_set_point=True,
        day_group=RinnaiScheduleDayGroup.ALL_DAYS,
        zones={"A"},
    )
    system._schedule_condition = threading.Condition()
    system._schedule_generation = 0
    responses = [
        {"ZV": "A", "TP": period, "TM": start, "SP": temperature}
        for period, start, temperature in (
            ("W", "06:00", "20"),
            ("L", "08:00", "00"),
            ("R", "17:30", "22"),
            ("P", "21:30", "19"),
            ("S", "22:30", "17"),
        )
    ]
    system._get_schedule_generation = lambda: 0
    system._wait_for_schedule_status = lambda *_args: responses.pop(0)

    schedule = asyncio.run(system.async_read_schedule(zone="A"))

    assert schedule.zone == "A"
    assert schedule.day_group == RinnaiScheduleDayGroup.ALL_DAYS
    assert [entry.period for entry in schedule.entries] == [
        RinnaiSchedulePeriod.WAKE,
        RinnaiSchedulePeriod.LEAVE,
        RinnaiSchedulePeriod.RETURN,
        RinnaiSchedulePeriod.PRE_SLEEP,
        RinnaiSchedulePeriod.SLEEP,
    ]
    assert schedule.entries[1].enabled is False
    assert schedule.entries[2].start_time.strftime("%H:%M") == "17:30"
    assert sent_commands(system) == [
        '{"HGOM": {"APZ": {"ZV": "A" } } }',
        '{"HGOM": {"APZ": {"TP": "W" } } }',
        '{"HGOM": {"APZ": {"TP": "L" } } }',
        '{"HGOM": {"APZ": {"TP": "R" } } }',
        '{"HGOM": {"APZ": {"TP": "P" } } }',
        '{"HGOM": {"APZ": {"TP": "S" } } }',
        '{"HGOM": {"APZ": {"ZV": "N" } } }',
    ]


def test_schedule_response_matcher_rejects_stale_selection():
    matcher = RinnaiSystem._schedule_response_matcher(
        "HGOM",
        "APZ",
        "B",
        RinnaiScheduleDay.WEEKDAYS,
        RinnaiScheduleDayGroup.WEEKDAYS_WEEKENDS,
        RinnaiSchedulePeriod.RETURN,
    )

    stale = [
        {
            "HGOM": {
                "APZ": {
                    "ZV": "B",
                    "WD": "Y",
                    "TP": "L",
                    "TM": "08:00",
                    "SP": "16",
                }
            }
        }
    ]
    expected = [
        {
            "HGOM": {
                "APZ": {
                    "ZV": "B",
                    "WD": "Y",
                    "TP": "R",
                    "TM": "17:30",
                    "SP": "22",
                }
            }
        }
    ]

    assert matcher(stale) is None
    assert matcher(expected) == expected[0]["HGOM"]["APZ"]
    assert RinnaiSystem._is_schedule_status(
        [{"SYST": {}}, {"HGOM": {"APZ": {"ZV": "N"}}}]
    )
    assert RinnaiSystem._is_schedule_status(
        [
            {"SYST": {}},
            {"HGOM": {"OOP": {"ST": "N"}, "APS": {"AV": "Y"}}},
        ]
    )
    assert not RinnaiSystem._is_schedule_status(
        [
            {"SYST": {}},
            {"HGOM": {"OOP": {"ST": "N"}, "APS": {"AV": "N"}}},
        ]
    )


def test_interrupted_schedule_read_preserves_cancellation_when_connection_closes():
    system = make_system(
        multi_set_point=True,
        day_group=RinnaiScheduleDayGroup.ALL_DAYS,
        zones={"A"},
    )
    system._schedule_condition = threading.Condition()
    system._schedule_generation = 0
    system.send_command.side_effect = [
        True,
        asyncio.CancelledError(),
        RinnaiConnectionNotReadyError("Bridge status stream is not ready"),
    ]

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(system.async_read_schedule(zone="A"))
