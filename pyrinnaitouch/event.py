"""Module to capture event handling."""

import logging

try:
    from typing import Self
except ImportError:
    from typing_extensions import Self

_LOGGER = logging.getLogger(__name__)


class Event:
    """Simple event class."""

    def __init__(self) -> None:
        self.__eventhandlers = []

    def __iadd__(self, handler) -> Self:
        """Add event handler."""
        self.__eventhandlers.append(handler)
        return self

    def __isub__(self, handler) -> Self:
        """Remove event handler."""
        self.__eventhandlers.remove(handler)
        return self

    def __call__(self, *args, **keywargs) -> None:
        """Call event handler."""
        for eventhandler in tuple(self.__eventhandlers):
            if eventhandler is not None:
                try:
                    eventhandler(*args, **keywargs)
                except Exception:  # pylint: disable=broad-exception-caught
                    _LOGGER.exception("Unhandled exception in event handler")
