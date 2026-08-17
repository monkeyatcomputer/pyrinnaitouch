""" Interface to the Rinnai Touch Controller
    The primary purpose of this is to be integrated into Home Assistant.
"""

from .system import RinnaiSystemStatus, RinnaiSystem
from .unit_status import RinnaiUnitStatus
from .topology import RinnaiTopology, ZoneCapabilities, ZoneControl
from .const import (
    RinnaiSchedulePeriod,
    RinnaiScheduleDay,
    RinnaiScheduleDayGroup,
    RinnaiCapabilities,
    RinnaiOperatingMode,
    RinnaiSystemMode,
    TEMP_FAHRENHEIT,
    TEMP_CELSIUS
)

__all__ = [
    "RinnaiCapabilities",
    "RinnaiOperatingMode",
    "RinnaiSchedulePeriod",
    "RinnaiScheduleDay",
    "RinnaiScheduleDayGroup",
    "RinnaiSystem",
    "RinnaiSystemMode",
    "RinnaiSystemStatus",
    "RinnaiTopology",
    "RinnaiUnitStatus",
    "TEMP_CELSIUS",
    "TEMP_FAHRENHEIT",
    "ZoneCapabilities",
    "ZoneControl",
]
