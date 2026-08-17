"""Persistent, mode-aware topology for N-BW2 controlled systems."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

from .const import RinnaiSystemMode


COMMON_ZONE = "U"
THERMOSTAT_ZONES = frozenset({"A", "B", "C", "D"})
VALID_ZONES = THERMOSTAT_ZONES | {COMMON_ZONE}


class ZoneControl(Enum):
    """The primary control exposed by a zone in an operating mode."""

    READ_ONLY = "read_only"
    ENABLE = "enable"
    THERMOSTAT = "thermostat"


@dataclass(frozen=True)
class ZoneCapabilities:
    """Protocol operations supported by an installed zone."""

    zone_id: str
    control: ZoneControl
    measured_temperature: bool = False
    auto_participation: bool = False
    fan_only_enable: bool = False
    schedule: bool = False
    advance: bool = False

    @property
    def common(self) -> bool:
        """Return whether this is the common/spill zone."""
        return self.zone_id == COMMON_ZONE

    @property
    def can_enable(self) -> bool:
        """Return whether its enabled state is writable."""
        return self.control == ZoneControl.ENABLE

    @property
    def has_set_point(self) -> bool:
        """Return whether this zone owns an independent temperature set point."""
        return self.control == ZoneControl.THERMOSTAT


@dataclass
class RinnaiTopology:
    """Accumulate topology observed while the controller changes modes."""

    multi_set_point: bool = False
    zone_descriptions: dict[str, str] = field(default_factory=dict)
    zones_by_mode: dict[RinnaiSystemMode, dict[str, ZoneCapabilities]] = field(
        default_factory=dict
    )

    def observe(
        self,
        mode: RinnaiSystemMode,
        multi_set_point: bool,
        installed_zones: Iterable[str],
        descriptions: dict[str, str | None] | None = None,
    ) -> None:
        """Record the topology reported for one active operating mode."""
        self.multi_set_point = multi_set_point
        if descriptions:
            self.zone_descriptions.update(
                {
                    zone: description.strip()
                    for zone, description in descriptions.items()
                    if description and description.strip()
                }
            )

        self.zones_by_mode[mode] = {
            zone: self._capabilities_for(mode, multi_set_point, zone)
            for zone in installed_zones
            if zone in VALID_ZONES
        }

    def zones(self, mode: RinnaiSystemMode) -> dict[str, ZoneCapabilities]:
        """Return installed zones observed in an operating mode."""
        return self.zones_by_mode.get(mode, {})

    def zone(
        self, mode: RinnaiSystemMode, zone_id: str
    ) -> ZoneCapabilities | None:
        """Return one zone's capabilities, if installed and already observed."""
        return self.zones(mode).get(zone_id)

    def all_observed_zones(self) -> set[str]:
        """Return the union of zones observed across all operating modes."""
        return {
            zone_id
            for mode_zones in self.zones_by_mode.values()
            for zone_id in mode_zones
        }

    @staticmethod
    def _capabilities_for(
        mode: RinnaiSystemMode, multi_set_point: bool, zone_id: str
    ) -> ZoneCapabilities:
        if mode == RinnaiSystemMode.EVAP:
            return ZoneCapabilities(
                zone_id=zone_id,
                control=ZoneControl.ENABLE,
                auto_participation=True,
            )

        if zone_id == COMMON_ZONE:
            return ZoneCapabilities(
                zone_id=zone_id,
                control=ZoneControl.READ_ONLY,
                measured_temperature=not multi_set_point,
            )

        if multi_set_point:
            return ZoneCapabilities(
                zone_id=zone_id,
                control=ZoneControl.THERMOSTAT,
                measured_temperature=True,
                schedule=True,
                advance=True,
                fan_only_enable=True,
            )

        return ZoneCapabilities(
            zone_id=zone_id,
            control=ZoneControl.ENABLE,
            measured_temperature=True,
        )
