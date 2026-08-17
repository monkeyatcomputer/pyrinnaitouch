"""Controller schedule data models."""

from dataclasses import dataclass
from datetime import time

from .const import (
    RinnaiScheduleDay,
    RinnaiScheduleDayGroup,
    RinnaiSchedulePeriod,
    RinnaiSystemMode,
)


@dataclass(frozen=True)
class RinnaiScheduleEntry:
    """One controller schedule period."""

    day: RinnaiScheduleDay
    period: RinnaiSchedulePeriod
    start_time: time
    temperature: int
    enabled_zones: frozenset[str] = frozenset()

    @property
    def enabled(self) -> bool:
        """Return whether this period has an active setpoint."""
        return self.temperature >= 8


@dataclass(frozen=True)
class RinnaiSchedule:
    """A complete schedule for one unit or MTSP zone."""

    mode: RinnaiSystemMode
    day_group: RinnaiScheduleDayGroup
    entries: tuple[RinnaiScheduleEntry, ...]
    temperature_unit: str
    zone: str | None = None
    pre_sleep_enabled: bool = False
