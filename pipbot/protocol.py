"""Length-prefixed JSON framing over TCP.

Wire format: [4-byte big-endian length][JSON payload]
Shared by both the router and component connections.
"""

import asyncio
import json
import struct

HEADER_FORMAT = "!I"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
MAX_MESSAGE_SIZE = 16 * 1024 * 1024  # 16 MB safety limit


async def read_message(reader: asyncio.StreamReader) -> dict:
    header = await reader.readexactly(HEADER_SIZE)
    (length,) = struct.unpack(HEADER_FORMAT, header)
    if length > MAX_MESSAGE_SIZE:
        raise ValueError(f"Message too large: {length} bytes")
    data = await reader.readexactly(length)
    return json.loads(data.decode("utf-8"))


async def write_message(writer: asyncio.StreamWriter, msg: dict) -> None:
    data = json.dumps(msg, separators=(",", ":")).encode("utf-8")
    header = struct.pack(HEADER_FORMAT, len(data))
    writer.write(header + data)
    await writer.drain()


async def close_writer(writer: asyncio.StreamWriter) -> None:
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass
