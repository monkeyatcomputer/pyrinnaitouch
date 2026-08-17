"""Tests for mode-aware zone capabilities."""

import asyncio
from unittest.mock import AsyncMock

from pyrinnaitouch.const import RinnaiSystemMode
from pyrinnaitouch.commands import UNIT_ZONE_ADVANCE_CANCEL
from pyrinnaitouch.system import RinnaiSystem
from pyrinnaitouch.system_status import RinnaiSystemStatus
from pyrinnaitouch.topology import RinnaiTopology, ZoneControl


def test_single_set_point_zones_are_dampers_and_common_is_read_only():
    topology = RinnaiTopology()

    topology.observe(
        RinnaiSystemMode.HEATING,
        multi_set_point=False,
        installed_zones={"A", "B", "U"},
        descriptions={"A": "Living", "B": "Bedrooms"},
    )

    assert topology.zone(RinnaiSystemMode.HEATING, "A").control == ZoneControl.ENABLE
    assert topology.zone(RinnaiSystemMode.HEATING, "A").measured_temperature
    assert topology.zone(RinnaiSystemMode.HEATING, "U").control == ZoneControl.READ_ONLY
    assert topology.zone_descriptions == {"A": "Living", "B": "Bedrooms"}


def test_multi_set_point_only_a_to_d_are_thermostats():
    topology = RinnaiTopology()

    topology.observe(
        RinnaiSystemMode.COOLING,
        multi_set_point=True,
        installed_zones={"A", "C", "U"},
    )

    zone_a = topology.zone(RinnaiSystemMode.COOLING, "A")
    assert zone_a.control == ZoneControl.THERMOSTAT
    assert zone_a.has_set_point
    assert zone_a.schedule
    assert zone_a.advance
    assert zone_a.fan_only_enable
    assert topology.zone(RinnaiSystemMode.COOLING, "U").control == ZoneControl.READ_ONLY


def test_evaporative_common_zone_is_writable_but_not_a_thermostat():
    topology = RinnaiTopology()

    topology.observe(
        RinnaiSystemMode.EVAP,
        multi_set_point=False,
        installed_zones={"A", "U"},
    )

    common = topology.zone(RinnaiSystemMode.EVAP, "U")
    assert common.can_enable
    assert common.auto_participation
    assert not common.has_set_point
    assert not common.measured_temperature


def test_topology_preserves_zones_seen_in_other_modes():
    topology = RinnaiTopology()
    topology.observe(RinnaiSystemMode.HEATING, False, {"A", "B"})
    topology.observe(RinnaiSystemMode.EVAP, False, {"A", "U"})

    assert set(topology.zones(RinnaiSystemMode.HEATING)) == {"A", "B"}
    assert set(topology.zones(RinnaiSystemMode.EVAP)) == {"A", "U"}
    assert topology.all_observed_zones() == {"A", "B", "U"}


def test_system_rejects_common_zone_thermostat_commands():
    system = RinnaiSystem.__new__(RinnaiSystem)
    system._status = RinnaiSystemStatus()
    system._status.mode = RinnaiSystemMode.HEATING
    system._topology = RinnaiTopology()
    system._topology.observe(RinnaiSystemMode.HEATING, True, {"A", "U"})

    assert system._zone_supports("A", "has_set_point")
    assert not system._zone_supports("U", "has_set_point")
    assert not system._zone_enable_supported("U")


def test_mtsp_system_uses_zone_schedules_not_a_unit_schedule():
    system = RinnaiSystem.__new__(RinnaiSystem)
    system._status = RinnaiSystemStatus()
    system._status.is_multi_set_point = True

    system._status.mode = RinnaiSystemMode.HEATING
    assert not system._unit_schedule_supported()

    system._status.mode = RinnaiSystemMode.EVAP
    assert system._unit_schedule_supported()


def test_advance_cancel_command_clears_override():
    assert '"AO": "N"' in UNIT_ZONE_ADVANCE_CANCEL


def test_evap_operating_mode_commands_use_ecom():
    system = RinnaiSystem.__new__(RinnaiSystem)
    system._status = RinnaiSystemStatus()
    system._status.mode = RinnaiSystemMode.EVAP
    system.send_command = AsyncMock(return_value=True)

    assert asyncio.run(system.set_evap_auto())
    assert asyncio.run(system.set_evap_manual())

    assert [call.args[0] for call in system.send_command.await_args_list] == [
        '{"ECOM": {"GSO": {"OP": "A" } } }',
        '{"ECOM": {"GSO": {"OP": "M" } } }',
    ]
