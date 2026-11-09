"""Reviewed binary layouts. Integers remain in device units unless explicit."""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from enum import IntFlag

from .protocol import Message, ProtocolError


@dataclass(frozen=True)
class Layout:
    format: str
    fields: tuple[str, ...]
    page: int

    def pack(self, **values: int | float | bytes) -> bytes:
        if values.keys() != set(self.fields):
            raise ValueError(f"expected fields {self.fields}; got {tuple(values)}")
        return struct.pack("<" + self.format, *(values[name] for name in self.fields))

    def unpack(self, data: bytes | None) -> dict:
        if data is None:
            raise ProtocolError("expected a data packet; got a header-only reply")
        if len(data) != struct.calcsize("<" + self.format):
            raise ProtocolError(f"expected {struct.calcsize('<' + self.format)} payload bytes; got {len(data)}")
        return dict(zip(self.fields, struct.unpack("<" + self.format, data), strict=True))


# Keys are suffixes shared by the SET and GET commands. Signedness follows
# individual field descriptions, not the ambiguous generic C word 'long'.
LAYOUTS = {
    "MOT_POSCOUNTER": Layout("Hi", ("channel", "position"), 73),
    "MOT_ENCCOUNTER": Layout("Hi", ("channel", "encoder"), 75),
    "MOT_VELPARAMS": Layout("HIII", ("channel", "minimum_velocity", "acceleration", "maximum_velocity"), 77),
    "MOT_JOGPARAMS": Layout("HHIIIIH", ("channel", "mode", "step_size", "minimum_velocity", "acceleration", "maximum_velocity", "stop_mode"), 79),
    "MOT_GENMOVEPARAMS": Layout("Hi", ("channel", "backlash"), 84),
    "MOT_MOVERELPARAMS": Layout("Hi", ("channel", "distance"), 85),
    "MOT_MOVEABSPARAMS": Layout("Hi", ("channel", "position"), 86),
    "MOT_HOMEPARAMS": Layout("HHHII", ("channel", "direction", "limit_switch", "velocity", "offset"), 87),
    "MOT_LIMSWITCHPARAMS": Layout("HHHIIH", ("channel", "clockwise_hardware", "counterclockwise_hardware", "clockwise_position", "counterclockwise_position", "software_mode"), 89),
    "MOT_STATUSBITS": Layout("HI", ("channel", "status"), 148),
    "PZ_OUTPUTVOLTS": Layout("Hh", ("channel", "voltage"), 221),
    "PZ_OUTPUTPOS": Layout("Hh", ("channel", "position"), 222),
    "PZ_INPUTVOLTSSRC": Layout("HH", ("channel", "source"), 224),
    "PZ_PICONSTS": Layout("HHH", ("channel", "proportional", "integral"), 226),
    "PZ_PZSTATUSBITS": Layout("HI", ("channel", "status"), 228),
    "PZ_PZSTATUSUPDATE": Layout("HhhI", ("channel", "voltage", "position", "status"), 230),
    "PZ_MAXTRAVEL": Layout("HH", ("channel", "travel_100nm"), 255),
    "PZ_OUTPUTMAXVOLTS": Layout("HHH", ("channel", "voltage_tenths", "flags"), 259),
    "PZ_TSG_READING": Layout("HhH", ("channel", "reading", "smoothed"), 271),
    "MOT_SOL_CYCLEPARAMS": Layout("HIII", ("channel", "on_ms", "off_ms", "cycles"), 211),
}


@dataclass(frozen=True)
class HardwareInfo:
    serial_number: int
    model: str
    hardware_type: int
    firmware: tuple[int, int, int]
    hardware_version: int
    modification_state: int
    channels: int
    reserved: bytes

    @classmethod
    def decode(cls, message: Message) -> HardwareInfo:
        data = message.data
        if message.message_id != 0x0006 or data is None or len(data) != 84:
            raise ProtocolError("HW_GET_INFO requires an 84-byte payload (pp. 59–60)")
        serial, model, kind = struct.unpack_from("<I8sH", data)
        hw_version, modification, channels = struct.unpack_from("<HHH", data, 78)
        return cls(serial, model.split(b"\0", 1)[0].decode("ascii", "replace").strip(), kind,
                   (data[16], data[15], data[14]), hw_version, modification, channels, data[18:78])


class MotorStatusBits(IntFlag):
    FORWARD_HARD_LIMIT = 0x1
    REVERSE_HARD_LIMIT = 0x2
    FORWARD_SOFT_LIMIT = 0x4
    REVERSE_SOFT_LIMIT = 0x8
    MOVING_FORWARD = 0x10
    MOVING_REVERSE = 0x20
    JOGGING_FORWARD = 0x40
    JOGGING_REVERSE = 0x80
    CONNECTED = 0x100
    HOMING = 0x200
    HOMED = 0x400
    INITIALIZING = 0x800
    CHANNEL_ENABLED = 0x80000000


@dataclass(frozen=True)
class MotorStatus:
    channel: int
    position: int
    status: MotorStatusBits
    encoder: int | None = None
    velocity: int | None = None
    current_ma: int | None = None


def decode_motor_status(message: Message, *, kind: str) -> tuple[MotorStatus, ...]:
    """Require a layout choice: MOVE_COMPLETED uses different layouts by family."""
    data = message.data
    if data is None:
        raise ProtocolError("status has no payload")
    if kind == "dc":
        if len(data) != 14:
            raise ProtocolError("DC status must contain 14 bytes")
        channel, position, velocity, current, bits = struct.unpack("<HiHhI", data)
        return (MotorStatus(channel, position, MotorStatusBits(bits), velocity=velocity, current_ma=current),)
    if kind not in ("stepper", "inertial"):
        raise ValueError("kind must be dc, stepper, or inertial")
    if (kind == "stepper" and len(data) not in (14, 28)) or (kind == "inertial" and len(data) not in (14, 56)):
        raise ProtocolError("unexpected motor status size")
    blocks = [data[:14]] if kind == "stepper" else [data[i:i+14] for i in range(0, len(data), 14)]
    return tuple(MotorStatus(ch, pos, MotorStatusBits(bits), encoder=enc)
                 for ch, pos, enc, bits in (struct.unpack("<HiiI", block) for block in blocks))


@dataclass(frozen=True)
class UnitScale:
    """Explicit controller+stage conversion, including a separate telemetry scale."""
    position: float
    velocity: float
    acceleration: float
    reported_velocity: float | None = None

    def __post_init__(self):
        for value in (self.position, self.velocity, self.acceleration, self.reported_velocity):
            if value is not None and (not math.isfinite(value) or value <= 0):
                raise ValueError("conversion factors must be finite and positive")

    def to_device(self, quantity: str, value: float) -> int:
        if quantity not in ("position", "velocity", "acceleration", "reported_velocity"):
            raise ValueError("unknown quantity")
        scale = getattr(self, quantity)
        if scale is None or not math.isfinite(value):
            raise ValueError("missing scale or non-finite value")
        return round(value * scale)

    def from_device(self, quantity: str, value: int) -> float:
        if quantity not in ("position", "velocity", "acceleration", "reported_velocity"):
            raise ValueError("unknown quantity")
        scale = getattr(self, quantity)
        if scale is None:
            raise ValueError("scale is unspecified")
        return value / scale
