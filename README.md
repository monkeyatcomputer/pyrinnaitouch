
# pyrinnaitouch - python interface to Rinnai Touch Wifi Controllers

![Pylint](https://github.com/monkeyatcomputer/pyrinnaitouch/workflows/Pylint/badge.svg)

This is a python interface to the [Rinnai Touch Wifi Controller](https://www.rinnai.com.au/online/controllers/heating-and-cooling-controllers/rinnai-touch-wi-fi/).

The specifications for the interface are contained in the [included pdf](./NBW2API_Iss1.3.pdf).

## Fork provenance

This repository, [`monkeyatcomputer/pyrinnaitouch`](https://github.com/monkeyatcomputer/pyrinnaitouch), is a direct fork of the original [`funtastix/pyrinnaitouch`](https://github.com/funtastix/pyrinnaitouch) project. It retains the original project's Git history, MIT licence, and contributor attribution. Changes made in this fork build on that work.

The original project also credits [`lazdavila/pescea`](https://github.com/lazdavila/pescea) as a template and source of inspiration. `pescea` is an acknowledged influence, not the direct GitHub parent of this fork.

## Usage

This package is not a standalone application for end user implementation.

The aim of this package is to be used by software developers and integrators to implement
the Rinnai Touch Wifi interface on home automation platforms (principally Home Assistant )

## Connection behavior

`RinnaiSystem.async_get_status()` opens the TCP session and waits for `*HELLO*` plus a valid status frame. The connection parser accepts fragmented and combined frames. It rejects invalid sequence numbers, oversized buffers, and malformed status payloads.

Command coroutines complete after the controller acknowledges the matching sequence number. The library keeps one command in flight, limits the pending queue, wraps the sequence after 255, and fails pending work on timeout or disconnect.

## Zone topology

`RinnaiSystem.get_topology()` returns the zones observed in each operating mode. Use `CFG.MTSP` through this model when choosing controls:

| Mode and setup | Zone A-D control | Common zone U control |
|---|---|---|
| Heating or refrigerated cooling, `MTSP=N` | Enable/disable damper | Read-only |
| Heating or refrigerated cooling, `MTSP=Y` | Thermostat, schedule and advance | Read-only |
| Evaporative cooling | Enable and auto-participation | Enable and auto-participation |

The topology object retains zones from earlier modes because the bridge can report a different list after a mode change.

## Schedule programming

`RinnaiSystem.set_schedule_period()` programs one period in the active heating
or add-on cooling schedule. Pass a `RinnaiScheduleDay`,
`RinnaiSchedulePeriod`, 24-hour start time, and integer setpoint. MTSP systems
also require a zone. Single-set-point systems can optionally receive a list of
zones enabled for the period.

The library validates the day against the grouping reported by the controller,
serializes concurrent schedule changes, and exits programming mode even when a
field update fails. Values below 8 disable the period, matching the bridge API.

```python
await system.set_schedule_period(
    RinnaiScheduleDay.WEEKDAYS,
    RinnaiSchedulePeriod.RETURN,
    "17:30",
    22,
    zone="A",
)
```

## Credits

Thank you to the maintainers and contributors of [`funtastix/pyrinnaitouch`](https://github.com/funtastix/pyrinnaitouch) and [`lazdavila/pescea`](https://github.com/lazdavila/pescea), whose work forms the foundation of this project.
