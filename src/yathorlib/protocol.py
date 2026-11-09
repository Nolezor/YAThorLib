"""APT framing, DOC-103274 issue 48, pp. 36–40. No DLL dependencies."""
from __future__ import annotations

import struct
from dataclasses import dataclass


class ProtocolError(ValueError):
    """Malformed or unsupported packet; bytes cannot safely be resynchronized."""


@dataclass(frozen=True, slots=True)
class Message:
    message_id: int
    destination: int = 0x50
    source: int = 0x01
    param1: int = 0
    param2: int = 0
    data: bytes | None = None

    def __post_init__(self) -> None:
        for name, maximum in (("message_id", 65535), ("destination", 127),
                              ("source", 127), ("param1", 255), ("param2", 255)):
            value = getattr(self, name)
            if not isinstance(value, int) or not 0 <= value <= maximum:
                raise ValueError(f"{name} must be an integer in 0..{maximum}")
        if self.data is not None:
            if not isinstance(self.data, bytes):
                raise TypeError("data must be immutable bytes or None")
            if len(self.data) > 65535:
                raise ValueError("APT payload exceeds the 16-bit length field")
            if self.param1 or self.param2:
                raise ValueError("data packets do not have header parameters")

    def encode(self) -> bytes:
        if self.data is None:
            return struct.pack("<HBBBB", self.message_id, self.param1, self.param2,
                               self.destination, self.source)
        return struct.pack("<HHBB", self.message_id, len(self.data),
                           self.destination | 0x80, self.source) + self.data

    @classmethod
    def decode(cls, packet: bytes) -> Message:
        if len(packet) < 6:
            raise ProtocolError("truncated APT header")
        mid, p1, p2, dest, source = struct.unpack_from("<HBBBB", packet)
        length = (p1 | p2 << 8) if dest & 0x80 else 0
        if len(packet) != 6 + length:
            raise ProtocolError(f"expected {6 + length} bytes, received {len(packet)}")
        try:
            return cls(mid, dest & 0x7f, source, data=packet[6:]) if dest & 0x80 else cls(mid, dest, source, p1, p2)
        except ValueError as exc:
            raise ProtocolError(str(exc)) from exc

    def word(self, offset: int = 0) -> int:
        if self.data is None or len(self.data) < offset + 2 or offset < 0:
            raise ProtocolError("missing payload word")
        return struct.unpack_from("<H", self.data, offset)[0]


class FrameDecoder:
    """Incremental decoder. APT has no sync marker/checksum: never guess alignment."""

    def __init__(self, max_payload: int = 65535):
        if not 0 <= max_payload <= 65535:
            raise ValueError("invalid maximum payload")
        self.max_payload = max_payload
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[Message]:
        self._buffer.extend(data)
        result = []
        while len(self._buffer) >= 6:
            length = int.from_bytes(self._buffer[2:4], "little") if self._buffer[4] & 0x80 else 0
            if length > self.max_payload:
                raise ProtocolError(f"payload length {length} exceeds configured maximum")
            if len(self._buffer) < length + 6:
                break
            result.append(Message.decode(bytes(self._buffer[:length + 6])))
            del self._buffer[:length + 6]
        return result

    def eof(self) -> None:
        if self._buffer:
            raise ProtocolError(f"stream ended with {len(self._buffer)} incomplete bytes")


def bay_address(index: int) -> int:
    """Zero-based bay index, as defined on protocol page 39."""
    if not isinstance(index, int) or not 0 <= index <= 9:
        raise ValueError("bay index must be 0..9")
    return 0x21 + index
