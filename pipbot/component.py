"""Component base class and port descriptors.

Port descriptors live on the class and use __set_name__ for automatic naming.
When accessed on an instance, the descriptor's __get__ returns a BoundPort
that exposes write() for producers and __aiter__() for consumers.
"""

from __future__ import annotations

import asyncio

from pipbot.protocol import close_writer, read_message, write_message

_STOP = object()


# ------------------------------------------------------------------
# Bound port — the runtime handle a component interacts with
# ------------------------------------------------------------------

class BoundPort:
    """Wired port with a concrete path and TCP connection."""

    __slots__ = ("path", "mode", "_writer", "_queue")

    def __init__(self, path: str, mode: str):
        self.path = path
        self.mode = mode
        self._writer: asyncio.StreamWriter | None = None
        self._queue: asyncio.Queue | None = (
            asyncio.Queue() if mode == "read" else None
        )

    async def write(self, value):
        """Send a value through this port (producer side)."""
        if self.mode != "write":
            raise RuntimeError(
                f"Cannot write to port '{self.path}' (mode='{self.mode}')"
            )
        if self._writer is None:
            raise RuntimeError(
                f"Port '{self.path}' is not connected — "
                "load this component through config.yaml before writing."
            )
        await write_message(self._writer, {
            "verb": "write",
            "path": self.path,
            "body": value,
        })

    def __aiter__(self):
        if self.mode != "read":
            raise RuntimeError(
                f"Cannot iterate port '{self.path}' (mode='{self.mode}')"
            )
        return self

    async def __anext__(self):
        value = await self._queue.get()
        if value is _STOP:
            raise StopAsyncIteration
        return value

    async def _deliver(self, value):
        if self._queue is not None:
            await self._queue.put(value)

    def _stop(self):
        if self._queue is not None:
            self._queue.put_nowait(_STOP)


# ------------------------------------------------------------------
# Port descriptors — declared on Component subclasses
# ------------------------------------------------------------------

class _PortDescriptor:
    """Base descriptor for channel ports."""

    prefix: str = ""
    default_mode: str = "write"

    def __init__(self, mode: str | None = None):
        self.mode = mode or self.default_mode
        self.name: str | None = None

    def __set_name__(self, owner, name):
        self.name = name

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        try:
            return obj._bound_ports[self.name]
        except (AttributeError, KeyError):
            raise RuntimeError(
                f"Port '{self.name}' is not wired — load this component "
                "through config.yaml before accessing its ports."
            )


class SensorPort(_PortDescriptor):
    """Declares a /s/ channel.

    Default mode is 'write' (this component produces sensor data).
    Use mode='read' for components that consume sensor data.
    """
    prefix = "/s/"
    default_mode = "write"


class CommandPort(_PortDescriptor):
    """Declares a /c/ channel.

    Default mode is 'read' (this component receives commands).
    Use mode='write' for components that send commands.
    """
    prefix = "/c/"
    default_mode = "read"


# ------------------------------------------------------------------
# Component base class
# ------------------------------------------------------------------

class Component:
    """Base class for all pipbot components.

    Subclasses declare ports as class attributes and override start().
    """

    def __init__(self):
        self._bound_ports: dict[str, BoundPort] = {}
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task | None = None

    # -- user-facing hooks ------------------------------------------

    async def start(self):
        """Override this with the component's main loop."""

    async def stop(self):
        """Override this for cleanup on shutdown."""

    # -- port introspection -----------------------------------------

    @classmethod
    def _get_ports(cls) -> dict[str, _PortDescriptor]:
        ports: dict[str, _PortDescriptor] = {}
        for klass in reversed(cls.__mro__):
            for name, attr in vars(klass).items():
                if isinstance(attr, _PortDescriptor):
                    ports[name] = attr
        return ports

    # -- framework internals (called by Bot) ------------------------

    async def _connect(self, host: str, port: int, component_name: str):
        self._reader, self._writer = await asyncio.open_connection(host, port)

        paths: dict[str, str] = {}
        for bp in self._bound_ports.values():
            bp._writer = self._writer
            paths[bp.path] = bp.mode

        await write_message(self._writer, {
            "type": "register",
            "component": component_name,
            "paths": paths,
        })

        ack = await read_message(self._reader)
        if ack.get("status") != "ok":
            raise RuntimeError(
                f"Registration failed for '{component_name}': "
                f"{ack.get('reason')}"
            )

    def _start_message_reader(self):
        path_to_port = {
            bp.path: bp
            for bp in self._bound_ports.values()
            if bp.mode == "read"
        }
        if not path_to_port:
            return
        self._reader_task = asyncio.create_task(self._message_loop(path_to_port))

    async def _message_loop(self, path_to_port: dict[str, BoundPort]):
        try:
            while True:
                msg = await read_message(self._reader)
                path = msg.get("path")
                body = msg.get("body")
                if path in path_to_port:
                    await path_to_port[path]._deliver(body)
        except (asyncio.IncompleteReadError, ConnectionError,
                asyncio.CancelledError):
            pass

    async def _shutdown(self):
        for bp in self._bound_ports.values():
            bp._stop()

        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass

        if self._writer:
            await close_writer(self._writer)
