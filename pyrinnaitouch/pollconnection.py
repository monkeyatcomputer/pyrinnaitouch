"""Handle connectivity with non-blocking sockets and connection reporting."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from concurrent.futures import Future
from dataclasses import dataclass
import enum
import logging
from queue import Empty, Full, Queue, SimpleQueue
import selectors
import socket
import threading
import time

from .protocol import ProtocolError, StatusFrameParser, encode_command, next_sequence

_LOGGER = logging.getLogger(__name__)


class RinnaiConnectionState(enum.Enum):
    """Possible connection states for this class."""

    IDLE = 1
    CONNECTING = 2
    CONNECTED = 3
    REFUSED = 4
    TIMEOUT = 5
    ERROR = 6


class RinnaiConnectionError(ConnectionError):
    """Base error for transport and command failures."""


class RinnaiConnectionNotReadyError(RinnaiConnectionError):
    """Raised when a command is issued without a live status stream."""


class RinnaiCommandTimeoutError(RinnaiConnectionError):
    """Raised when the bridge does not acknowledge a command."""


@dataclass
class _CommandRequest:
    """A command waiting to be sent and acknowledged."""

    command: str
    result: Future


class RinnaiPollConnection:  # pylint: disable=too-many-instance-attributes,too-many-branches,too-many-statements
    """Manage the non-blocking connection to the unit."""

    # Global map of IP addresses currently in use. Only used to track when multiple
    # connections are attempted, since we know how poorly the hardware handles this.
    clients = defaultdict(int)
    _clients_lock = threading.Lock()

    def __init__(
        self, ip_address: str, status_queue: SimpleQueue, port: int = 27847
    ) -> None:
        """Initialise the connection object."""
        self._ip_address = ip_address
        self._port = port
        self._command_sequence = 1
        self._last_command_time = 0
        self._last_received_time = 0
        self._command_timeout_seconds = 10
        self._last_received_sequence_num = 0
        self._command_wait = False
        self._command_wait_timeout_seconds = 5
        with RinnaiPollConnection._clients_lock:
            if RinnaiPollConnection.clients[ip_address] > 0:
                _LOGGER.error(
                    "Attempting duplicate connection to unit at %s, which the hardware "
                    "will not support",
                    ip_address,
                )
                raise RuntimeError("Cannot have two connections to the same address")
            RinnaiPollConnection.clients[ip_address] += 1

        # Queue of commands (each as a string) to send to the unit.
        self._sendqueue = Queue(maxsize=32)
        self._inflight_command: _CommandRequest | None = None
        self._ready_event = threading.Event()

        # Checked in all manner of places, should only be set on shutdown.
        self._thread_exit_flag = False
        self._stop_event = threading.Event()
        self._stopped = False

        # These don't get created until start_thread is called
        self._socket: socket.socket = None
        self._socketthread: threading.Thread = None
        self._socketstate = RinnaiConnectionState.IDLE

        self._readbuffer = bytearray()
        self._writebuffer = bytearray()
        self._frame_parser = StatusFrameParser()

        # List of functions to call whenever _socketstate changes
        # Provides a single argument, RinnaiConnectionState
        self._connection_state_handlers = []

        # Outbound queue of JSON status
        self._status_queue = status_queue

        _LOGGER.debug("Poll connection inited")

    def send_command(self, command: str) -> Future:
        """Queue a command and return a future resolved by its sequence ack."""
        result = Future()
        if not self._ready_event.is_set():
            result.set_exception(
                RinnaiConnectionNotReadyError("Bridge status stream is not ready")
            )
            return result

        try:
            self._sendqueue.put_nowait(_CommandRequest(command, result))
        except Full:
            result.set_exception(RinnaiConnectionError("Command queue is full"))
        return result

    async def async_send_command(self, command: str) -> bool:
        """Send a command and wait for the bridge sequence acknowledgement."""
        return await asyncio.wrap_future(self.send_command(command))

    def __del__(self):
        """Destructor to ensure the thread is stopped and the socket closed."""
        if not getattr(self, "_stopped", True):
            self.stop_thread()

    def stop_thread(self) -> None:
        """Stop the thread, close the socket, and decrement the connection tracker."""
        if self._stopped:
            return
        self._stopped = True
        self._thread_exit_flag = True
        self._stop_event.set()
        self._ready_event.clear()
        self._fail_queued_commands(RinnaiConnectionError("Connection stopped"))

        # Closing first wakes a thread blocked in select/recv/connect.
        self._close_socket()
        if self._socketthread is not None and self._socketthread.is_alive():
            self._socketthread.join(5)
            if self._socketthread.is_alive():
                _LOGGER.error("Could not stop monitoring thread")
            else:
                self._socketthread = None
                _LOGGER.debug("Monitoring thread confirmed stopped")

        # Let anybody listening to the status know that we're exiting.
        self._status_queue.put("sys.exit")

        with RinnaiPollConnection._clients_lock:
            RinnaiPollConnection.clients[self._ip_address] -= 1
            if RinnaiPollConnection.clients[self._ip_address] < 0:
                _LOGGER.error(
                    "Somehow we have a negative number of connections; something has "
                    "gone very wrong"
                )
                # Try to restore some sanity
                RinnaiPollConnection.clients[self._ip_address] = 0

    def _update_socket_state(self, socketstate: RinnaiConnectionState) -> None:
        """Update the connection state and call all registered handlers."""
        # Ignore unchanged states.
        if not isinstance(socketstate, RinnaiConnectionState):
            raise TypeError("Invalid socket state")

        if self._socketstate != socketstate:
            previous_state = self._socketstate
            self._socketstate = socketstate
            if socketstate != RinnaiConnectionState.CONNECTED:
                self._ready_event.clear()
                if previous_state == RinnaiConnectionState.CONNECTED:
                    self._fail_queued_commands(
                        RinnaiConnectionError(
                            f"Connection lost ({socketstate.name.lower()})"
                        )
                    )
            for handler in tuple(self._connection_state_handlers):
                try:
                    handler(self._socketstate)
                except Exception:  # pylint: disable=broad-exception-caught
                    _LOGGER.exception("Unhandled exception in socket state handler")
            _LOGGER.debug("Socket state is now %s", self._socketstate)

    def socket_state(self) -> RinnaiConnectionState:
        """Return the current state of the socket."""
        return self._socketstate

    def wait_ready(self, timeout: float | None = None) -> bool:
        """Wait until HELLO and a complete status frame have been received."""
        return self._ready_event.wait(timeout)

    def register_socket_state_handler(self, handler) -> None:
        """Register a new handler interested in socket state updates.

        The new handler immediately gets called with the current status, and if
        successfully executed is added to the handler list. Duplicate handlers are
        ignored.
        """
        if handler not in self._connection_state_handlers:
            try:
                handler(self._socketstate)
                self._connection_state_handlers.append(handler)
            except TypeError as te:
                _LOGGER.error(
                    "Registration failed - could not call socket handler: %s", te
                )

    def unregister_socket_state_handler(self, handler) -> None:
        """Unregister a socket state handler."""
        if handler in self._connection_state_handlers:
            self._connection_state_handlers.remove(handler)

    def start_thread(self) -> None:
        """Attempt connection to the unit. Results are reflected via connection_state
        property."""

        if self._stopped:
            raise RinnaiConnectionError("A stopped connection cannot be restarted")
        if self._socketthread is None or not self._socketthread.is_alive():
            _LOGGER.debug("Starting connection thread")
            self._socketthread = threading.Thread(
                target=self._event_loop, name="RinnaiPollConnection", daemon=True
            )
            self._socketthread.start()
        else:
            _LOGGER.debug("Connection thread is already running")

    def _event_loop(self) -> None:
        """Thread that polls the socket and command queue and reacts accordingly."""
        _LOGGER.debug("Starting event loop within thread")
        while not self._thread_exit_flag:
            # Connect, then monitor. Repeat ad infinitum, unless we've been told
            # to exit.
            self._create_socket_and_connect()
            if self._thread_exit_flag or self._socket is None:
                break
            # Note that this only returns on disconnect/socket error, or when the thread
            # exit flag is set.
            self._monitor_socket_and_queue()

    def _close_socket(self) -> None:
        """Close the current TCP socket, if any."""
        if self._socket is None:
            return
        try:
            self._socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self._socket.close()
        except OSError:
            pass
        self._socket = None

    def _monitor_socket_and_queue(self) -> None:
        # Create the selector and register for read events on the socket and the send
        # queue.  Write events on the socket aren't selected for until we have something
        # to say.
        monitored_socket = self._socket
        if monitored_socket is None:
            return

        selector = selectors.DefaultSelector()
        try:
            selector.register(monitored_socket, selectors.EVENT_READ)
        except (OSError, ValueError):
            selector.close()
            if not self._thread_exit_flag:
                self._update_socket_state(RinnaiConnectionState.IDLE)
            return

        self._readbuffer.clear()
        self._writebuffer.clear()

        while (
            not self._thread_exit_flag
            and self._socketstate
            in (RinnaiConnectionState.CONNECTING, RinnaiConnectionState.CONNECTED)
        ):
            mask = selectors.EVENT_READ
            if len(self._writebuffer) > 0:
                mask |= selectors.EVENT_WRITE
                _LOGGER.debug("Selecting for write")

            try:
                selector.modify(monitored_socket, mask)
            except (KeyError, OSError, ValueError):
                if not self._thread_exit_flag:
                    self._update_socket_state(RinnaiConnectionState.IDLE)
                break

            try:
                events = selector.select(0.1)
            except (OSError, ValueError):
                if not self._thread_exit_flag:
                    self._update_socket_state(RinnaiConnectionState.IDLE)
                break
            for _key, mask in events:
                if mask & selectors.EVENT_READ:
                    # There is data available on the socket. Receive it into the buffer
                    # for now, process after we've been through all the events.
                    self._last_received_time = time.time()
                    try:
                        newbytes = monitored_socket.recv(8096)
                        _LOGGER.debug("Read %d bytes from socket", len(newbytes))

                        if len(newbytes) == 0:
                            # The socket has disconnected. This will be caught on the
                            # next loop and reconnection attempted.
                            _LOGGER.info("Socket disconnected. Reconnecting")
                            self._update_socket_state(RinnaiConnectionState.IDLE)
                        else:
                            self._readbuffer.extend(newbytes)
                            _LOGGER.debug(
                                "Receive buffer now has %d bytes of data to process",
                                len(self._readbuffer),
                            )

                    except OSError as ose:
                        _LOGGER.error("Socket error on recv: %s. Reconnecting", ose)
                        self._update_socket_state(RinnaiConnectionState.IDLE)

                if mask & selectors.EVENT_WRITE:
                    # We are able to write to the socket, and have something to say.
                    self._attempt_send(monitored_socket)

            if (
                self._thread_exit_flag
                or self._socketstate
                not in (RinnaiConnectionState.CONNECTING, RinnaiConnectionState.CONNECTED)
            ):
                break

            # Now process the command queue. We don't wait for anything to arrive here,
            # the waiting only happens in the select socket call.

            while True:
                try:
                    if self._command_wait:
                        if (
                            time.time() - self._last_command_time
                            < self._command_wait_timeout_seconds
                        ):
                            break
                        self._fail_inflight(
                            RinnaiCommandTimeoutError(
                                f"Command {self._command_sequence} was not acknowledged"
                            )
                        )
                        self._update_socket_state(RinnaiConnectionState.TIMEOUT)
                        break

                    request = self._sendqueue.get_nowait()
                    # A command is ready to be sent. Format it, place it into the
                    # writebuffer and attempt to send it.
                    self._command_sequence = next_sequence(
                        self._last_received_sequence_num
                    )
                    self._writebuffer.extend(
                        encode_command(self._command_sequence, request.command)
                    )
                    self._inflight_command = request
                    _LOGGER.debug("Sending command %d", self._command_sequence)
                    self._attempt_send(monitored_socket)
                    self._command_wait = True
                except Empty:
                    # Nothing in the queue for now. Consider sending an empty command
                    # if it's been long enough, and then break out of this loop.
                    if (
                        time.time() - self._last_command_time
                        > self._command_timeout_seconds
                    ):
                        self._command_sequence = next_sequence(
                            self._last_received_sequence_num
                        )
                        self._writebuffer.extend(
                            encode_command(self._command_sequence, "NA")
                        )
                        _LOGGER.debug("Sending idle command %d", self._command_sequence)
                        self._attempt_send(monitored_socket)

                        # Update the time here in case the socket doesn't become
                        # write available quickly.
                        self._last_command_time = time.time()
                        self._command_wait = True
                    break

            if time.time() - self._last_received_time > 30:
                _LOGGER.error(
                    "Resetting connection as no data received for at least 30 seconds"
                )
                self._update_socket_state(RinnaiConnectionState.TIMEOUT)

            self._process_received_data()

        selector.close()

    def _attempt_send(self, target_socket: socket.socket | None = None) -> None:
        # Attempt to send the contents of the write buffer. Only remove bytes that are
        # successfully sent,  which may not be all that we requested. Any bytes
        # remaining in the buffer will be caught in the next select call.
        target_socket = target_socket or self._socket
        if target_socket is None:
            if not self._thread_exit_flag:
                self._update_socket_state(RinnaiConnectionState.IDLE)
            return
        try:
            num_sent = target_socket.send(self._writebuffer)
            _LOGGER.debug("Sent %d of %d bytes", num_sent, len(self._writebuffer))
            self._writebuffer = self._writebuffer[num_sent:]

            self._last_command_time = time.time()
            if len(self._writebuffer) > 0:
                _LOGGER.warning(
                    "There are %d bytes remaining to send. There may be network "
                    "congestion, or the connection is about to fail",
                    len(self._writebuffer),
                )
        except OSError as ose:
            _LOGGER.error("Socket error on send: %s. Reconnecting", ose)
            self._update_socket_state(RinnaiConnectionState.IDLE)

    def _process_received_data(self) -> None:
        received = bytes(self._readbuffer)
        self._readbuffer.clear()
        hello_before = self._frame_parser.hello_received
        try:
            frames = self._frame_parser.feed(received)
        except ProtocolError as err:
            _LOGGER.error("Invalid status stream: %s; reconnecting", err)
            self._update_socket_state(RinnaiConnectionState.ERROR)
            return

        if self._frame_parser.hello_received and not hello_before:
            _LOGGER.info("Hello message successfully received from unit")

        for frame in frames:
            self._last_received_sequence_num = frame.sequence
            _LOGGER.debug(
                "Received sequence number %d", self._last_received_sequence_num
            )
            if self._command_wait and frame.sequence == self._command_sequence:
                self._command_wait = False
                if (
                    self._inflight_command is not None
                    and not self._inflight_command.result.done()
                ):
                    self._inflight_command.result.set_result(True)
                self._inflight_command = None
                _LOGGER.debug("Command wait end")
            self._status_queue.put(frame.payload)
            if self._frame_parser.hello_received:
                self._update_socket_state(RinnaiConnectionState.CONNECTED)
                self._ready_event.set()

    def _fail_inflight(self, error: Exception) -> None:
        """Fail the current command, if any, without replaying it."""
        if (
            self._inflight_command is not None
            and not self._inflight_command.result.done()
        ):
            self._inflight_command.result.set_exception(error)
        self._inflight_command = None
        self._command_wait = False

    def _fail_queued_commands(self, error: Exception) -> None:
        """Fail commands queued against a connection that has gone away."""
        self._fail_inflight(error)
        while True:
            try:
                request = self._sendqueue.get_nowait()
            except Empty:
                break
            if not request.result.done():
                request.result.set_exception(error)

    def _create_socket_and_connect(self) -> None:
        """Connect directly to a configured bridge with bounded backoff."""
        attempt = 0
        self._close_socket()
        while not self._thread_exit_flag:
            try:
                self._update_socket_state(RinnaiConnectionState.CONNECTING)
                self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._socket.settimeout(5)
                self._socket.connect((self._ip_address, self._port))

                # Reset the timestamps and command sequence number
                self._last_command_time = time.time()
                self._last_received_time = self._last_command_time
                self._command_sequence = 1
                self._last_received_sequence_num = 0
                self._command_wait = False
                self._frame_parser.reset()

                # Switch to non-blocking mode.
                self._socket.settimeout(0)
                return

            except ConnectionRefusedError:
                self._update_socket_state(RinnaiConnectionState.REFUSED)
            except TimeoutError:
                self._update_socket_state(RinnaiConnectionState.TIMEOUT)
            except (ConnectionError, BlockingIOError, InterruptedError):
                self._update_socket_state(RinnaiConnectionState.ERROR)
            except OSError as e:
                self._update_socket_state(RinnaiConnectionState.ERROR)
                _LOGGER.error('Unexpected connection error: "%s", will retry', e)
            self._close_socket()
            delay = min(30, 2 ** min(attempt, 5))
            attempt += 1
            _LOGGER.debug("Retrying bridge connection in %d seconds", delay)
            self._stop_event.wait(delay)
