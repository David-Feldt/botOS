"""Central message router — asyncio TCP server that enforces channel contracts.

Channel rules (by path prefix):
  /s/  Sensor — one writer (producer), many readers (consumers)
  /c/  Command — one reader (receiver/actuator), many writers (senders)

Run standalone:  python -m pipbot.router --port 5555
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from pipbot.protocol import close_writer, read_message, write_message

log = logging.getLogger("pipbot.router")

VALID_PREFIXES = ("/s/", "/c/")


class Router:
    def __init__(self, host="localhost", port=5555):
        self.host = host
        self.port = port

        # /s/ routing tables
        self._sensor_writer: dict[str, asyncio.StreamWriter] = {}
        self._sensor_readers: dict[str, set[asyncio.StreamWriter]] = {}

        # /c/ routing table
        self._command_receiver: dict[str, asyncio.StreamWriter] = {}

        # bookkeeping for cleanup on disconnect
        self._registrations: dict[str, list[tuple[str, str]]] = {}

        self._server: asyncio.Server | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        self._server = await asyncio.start_server(
            self._handle_client, self.host, self.port,
        )
        log.info("Listening on %s:%s", self.host, self.port)
        async with self._server:
            await self._server.serve_forever()

    # ------------------------------------------------------------------
    # Per-client handler
    # ------------------------------------------------------------------

    async def _handle_client(self, reader: asyncio.StreamReader,
                             writer: asyncio.StreamWriter):
        component: str | None = None
        try:
            msg = await read_message(reader)

            if msg.get("type") != "register":
                await write_message(writer, {
                    "type": "register_ack",
                    "status": "error",
                    "reason": "First message must be type 'register'",
                })
                return

            component = msg.get("component", "")
            paths: dict[str, str] = msg.get("paths", {})

            error = self._validate(paths)
            if error:
                await write_message(writer, {
                    "type": "register_ack",
                    "status": "error",
                    "reason": error,
                })
                return

            self._register(component, writer, paths)
            await write_message(writer, {"type": "register_ack", "status": "ok"})
            log.info("Component '%s' registered: %s", component, paths)

            # data loop
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

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def _validate(self, paths: dict[str, str]) -> str | None:
        for path, mode in paths.items():
            if not any(path.startswith(p) for p in VALID_PREFIXES):
                return f"Invalid prefix in path '{path}'"

            if path.startswith("/s/") and mode == "write":
                if path in self._sensor_writer:
                    return f"/s/ path '{path}' already has a writer"

            if path.startswith("/c/") and mode == "read":
                if path in self._command_receiver:
                    return f"/c/ path '{path}' already has a receiver"

        return None

    def _register(self, component: str, writer: asyncio.StreamWriter,
                  paths: dict[str, str]):
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
            if path.startswith("/s/"):
                if mode == "write":
                    self._sensor_writer.pop(path, None)
            elif path.startswith("/c/"):
                if mode == "read":
                    self._command_receiver.pop(path, None)

        # sweep reader sets to remove any disconnected writers
        for path, reader_set in list(self._sensor_readers.items()):
            dead = {w for w in reader_set if w.is_closing()}
            reader_set -= dead
            if not reader_set:
                del self._sensor_readers[path]

    # ------------------------------------------------------------------
    # Message routing
    # ------------------------------------------------------------------

    async def _route(self, sender: str, msg: dict):
        verb = msg.get("verb")
        path = msg.get("path")

        if verb != "write":
            log.warning("Unknown verb '%s' from '%s'", verb, sender)
            return

        if path is None:
            log.warning("Missing path in message from '%s'", sender)
            return

        if path.startswith("/s/"):
            await self._broadcast_sensor(path, msg)
        elif path.startswith("/c/"):
            await self._forward_command(path, msg)

    async def _broadcast_sensor(self, path: str, msg: dict):
        readers = self._sensor_readers.get(path)
        if not readers:
            return
        writers = list(readers)
        results = await asyncio.gather(
            *[write_message(w, msg) for w in writers],
            return_exceptions=True,
        )
        for writer, result in zip(writers, results):
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


def main():
    parser = argparse.ArgumentParser(description="pipbot message router")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=5555)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(name)s | %(levelname)s | %(message)s",
    )

    router = Router(host=args.host, port=args.port)
    try:
        asyncio.run(router.start())
    except KeyboardInterrupt:
        log.info("Shutting down")


if __name__ == "__main__":
    main()
