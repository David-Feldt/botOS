"""Client library for botOS components.

Usage in a component file:
    import botos, asyncio

    async def main():
        await botos.publish("/s/example/data", {"count": 1})

    if __name__ == "__main__":
        botos.run(main())
"""

import asyncio
import json
import os
import struct

HEADER_FORMAT = "!I"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

_reader = None
_writer = None
_subscriptions: dict[str, asyncio.Queue] = {}


async def _read_message() -> dict:
    header = await _reader.readexactly(HEADER_SIZE)
    (length,) = struct.unpack(HEADER_FORMAT, header)
    data = await _reader.readexactly(length)
    return json.loads(data.decode())


async def _write_message(msg: dict) -> None:
    data = json.dumps(msg, separators=(",", ":")).encode()
    _writer.write(struct.pack(HEADER_FORMAT, len(data)) + data)
    await _writer.drain()


async def _connect():
    global _reader, _writer
    host = os.environ.get("BOTOS_ROUTER_HOST", "localhost")
    port = int(os.environ.get("BOTOS_ROUTER_PORT", "5555"))
    name = os.environ.get("BOTOS_COMPONENT_NAME", "unknown")
    channels = json.loads(os.environ.get("BOTOS_CHANNELS", "{}"))

    _reader, _writer = await asyncio.open_connection(host, port)
    await _write_message({"type": "register", "component": name, "paths": channels})
    ack = await _read_message()
    if ack.get("status") != "ok":
        raise RuntimeError(f"Registration failed: {ack.get('reason')}")


async def _message_loop():
    try:
        while True:
            msg = await _read_message()
            path = msg.get("path")
            if path in _subscriptions:
                await _subscriptions[path].put(msg.get("body"))
    except (asyncio.IncompleteReadError, ConnectionError, asyncio.CancelledError):
        pass


async def publish(path: str, data) -> None:
    await _write_message({"verb": "write", "path": path, "body": data})


def subscribe(path: str):
    if path not in _subscriptions:
        _subscriptions[path] = asyncio.Queue()

    async def _iter():
        q = _subscriptions[path]
        while True:
            yield await q.get()

    return _iter()


def run(coro):
    async def _run():
        await _connect()
        reader_task = asyncio.get_event_loop().create_task(_message_loop())
        try:
            await coro
        finally:
            reader_task.cancel()
            if _writer:
                _writer.close()
                try:
                    await _writer.wait_closed()
                except Exception:
                    pass

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass
