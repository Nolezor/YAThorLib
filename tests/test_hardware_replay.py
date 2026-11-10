"""Replay of raw frames captured from a real KDC101 driving an MTS100/M-Z8 (via tools/hw_check.py).

Each frame the library writes must equal the next captured tx; the captured rx frames after it are the reply.
Timing is not replayed (homing took ~10 s on the real device).
"""
import asyncio
import json
from pathlib import Path

import pytest

from yathorlib import Connection, device

FIXTURES = Path(__file__).parent / "fixtures/hardware/KDC101"


class ReplayTransport:
    def __init__(self, frames):
        self.frames, self.index, self.rx, self.closed = frames, 0, asyncio.Queue(), False

    async def write(self, data):
        direction, expected = self.frames[self.index]
        assert direction == "tx" and data == expected, f"frame {self.index}: sent {data.hex()}, expected {expected.hex()}"
        self.index += 1
        while self.index < len(self.frames) and self.frames[self.index][0] == "rx":
            await self.rx.put(self.frames[self.index][1])
            self.index += 1

    async def read(self, size):
        return await self.rx.get()

    async def close(self):
        self.closed = True


async def identify(motor):
    info = await motor.hardware_info()
    assert info.model == "KDC101" and info.firmware == (2, 2, 11) and info.serial_number == 0  # redacted in the fixtures
    assert await motor.is_enabled() is True
    position = await motor.position()
    assert (await motor.status(kind="dc")).position == position
    return position


async def read_only(motor):
    assert await identify(motor) == -3402019  # power-on counter before homing


async def home(motor):
    await identify(motor)
    await motor.enable(True)
    assert await motor.is_enabled() is True
    await motor.home(timeout=30)
    assert await motor.position() == -2


async def move_relative(motor):
    assert await identify(motor) == -2
    await motor.enable(True)
    assert await motor.is_enabled() is True
    reply = await motor.move_relative(34555, timeout=30)  # about 1 mm on an MTS-Z8 stage
    assert reply.message_id == 0x0464  # MOVE_COMPLETED
    assert await motor.position() == 34551  # 34553 counts moved: a 2-count (~58 nm) difference


@pytest.mark.parametrize("name, scenario", [
    ("readonly-mts100m-z8", read_only), ("home-mts100m-z8", home), ("move-relative-mts100m-z8", move_relative)])
async def test_session_matches_real_device(name, scenario):
    lines = (FIXTURES / f"{name}.jsonl").read_text().splitlines()
    frames = [(r["dir"], bytes.fromhex(r["hex"])) for r in map(json.loads, lines)]
    transport = ReplayTransport(frames)
    async with Connection(transport) as connection:
        await scenario(device(connection, "KDC101"))
    assert transport.index == len(frames)
