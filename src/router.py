"""Central message router — asyncio TCP server.

Channel rules:
  /s/  Sensor — one writer, many readers
  /c/  Command — one reader, many writers
"""

from __future__ import annotations

import asyncio
import logging

from protocol import close_writer, read_message, write_message

log = logging.getLogger("bot.router")

VALID_PREFIXES = ("/s/", "/c/")


class Router:
    def __init__(self, host="localhost", port=5555):
        self.host = host
        self.port = port
        self._sensor_writer: dict[str, asyncio.StreamWriter] = {}
        self._sensor_readers: dict[str, set[asyncio.StreamWriter]] = {}
        self._command_receiver: dict[str, asyncio.StreamWriter] = {}
        self._registrations: dict[str, list[tuple[str, str]]] = {}
        self._server: asyncio.Server | None = None

    async def start(self):
        self._server = await asyncio.start_server(self._handle_client, self.host, self.port)
        log.info("Router listening on %s:%s", self.host, self.port)
        async with self._server:
            await self._server.serve_forever()

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        component: str | None = None
        try:
            msg = await read_message(reader)
            if msg.get("type") != "register":
                await write_message(writer, {"status": "error", "reason": "First message must be type 'register'"})
                return

            component = msg.get("component", "")
            paths: dict[str, str] = msg.get("paths", {})

            error = self._validate(paths)
            if error:
                await write_message(writer, {"status": "error", "reason": error})
                return

            self._register(component, writer, paths)
            await write_message(writer, {"status": "ok"})
            log.info("Component '%s' registered: %s", component, paths)

            while True:
                msg = await read_message(reader)
                await self._route(component, msg)

        except asyncio.IncompleteReadError:
            if component:
                log.info("Component '%s' disconnected", component)
        except ConnectionError:
            if component:
                log.info("Component '%s' connection lost", component)
        finally:
            if component:
                self._unregister(component)
            await close_writer(writer)

    def _validate(self, paths: dict[str, str]) -> str | None:
        for path, mode in paths.items():
            if not any(path.startswith(p) for p in VALID_PREFIXES):
                return f"Invalid prefix in path '{path}'"
            if path.startswith("/s/") and mode == "write" and path in self._sensor_writer:
                return f"/s/ path '{path}' already has a writer"
            if path.startswith("/c/") and mode == "read" and path in self._command_receiver:
                return f"/c/ path '{path}' already has a receiver"
        return None

    def _register(self, component: str, writer: asyncio.StreamWriter, paths: dict[str, str]):
        entries: list[tuple[str, str]] = []
        for path, mode in paths.items():
            if path.startswith("/s/"):
                if mode == "write":
                    self._sensor_writer[path] = writer
                else:
                    self._sensor_readers.setdefault(path, set()).add(writer)
            elif path.startswith("/c/"):
                if mode == "read":
                    self._command_receiver[path] = writer
            entries.append((path, mode))
        self._registrations[component] = entries

    def _unregister(self, component: str):
        entries = self._registrations.pop(component, [])
        for path, mode in entries:
            if path.startswith("/s/") and mode == "write":
                self._sensor_writer.pop(path, None)
            elif path.startswith("/c/") and mode == "read":
                self._command_receiver.pop(path, None)
        for path, reader_set in list(self._sensor_readers.items()):
            reader_set -= {w for w in reader_set if w.is_closing()}
            if not reader_set:
                del self._sensor_readers[path]

    async def _route(self, sender: str, msg: dict):
        verb = msg.get("verb")
        path = msg.get("path")
        if verb != "write" or path is None:
            return
        if path.startswith("/s/"):
            await self._broadcast_sensor(path, msg)
        elif path.startswith("/c/"):
            await self._forward_command(path, msg)

    async def _broadcast_sensor(self, path: str, msg: dict):
        readers = self._sensor_readers.get(path)
        if not readers:
            return
        results = await asyncio.gather(
            *[write_message(w, msg) for w in list(readers)],
            return_exceptions=True,
        )
        for writer, result in zip(list(readers), results):
            if isinstance(result, (ConnectionError, OSError)):
                readers.discard(writer)

    async def _forward_command(self, path: str, msg: dict):
        receiver = self._command_receiver.get(path)
        if receiver is None:
            return
        try:
            await write_message(receiver, msg)
        except (ConnectionError, OSError):
            self._command_receiver.pop(path, None)
