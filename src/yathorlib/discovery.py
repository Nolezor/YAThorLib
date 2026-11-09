"""Read-only Linux VCP discovery; never opens a device during enumeration."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Port:
    path: str
    serial_number: str | None
    description: str
    vid: int | None
    pid: int | None


def discover(*, include_other: bool = False) -> list[Port]:
    from serial.tools.list_ports import comports
    # FTDI includes non-Thorlabs products: the caller must verify model/serial.
    return [Port(p.device, p.serial_number, p.description, p.vid, p.pid)
            for p in comports() if include_other or
            (p.vid == 0x0403 and p.pid == 0xFAF0) or
            (p.vid == 0x26D1 and p.pid is not None and 0x64 <= p.pid <= 0xFF)]
