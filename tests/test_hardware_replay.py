"""Replay of raw frames captured from a real KDC101 driving an MTS100/M-Z8 (via tools/hw_check.py).

Each frame the library writes must equal the next captured tx; the captured rx frames after it are the reply.
Timing is not replayed (homing took ~10 s on the real device).
"""
import asyncio
import json
from pathlib import Path

import pytest

from yathorlib import Connection, ConnectionClosed, MotionInterrupted, device
from yathorlib.codecs import MotorStatusBits, decode_motor_status

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


async def move_absolute(motor):
    assert await identify(motor) == 34551
    await motor.enable(True)
    assert await motor.is_enabled() is True
    assert (await motor.move_absolute(69110, timeout=30)).message_id == 0x0464  # MOVE_COMPLETED
    assert await motor.position() == 69108  # 2 counts short of the target, as with the relative move


async def stop_mid_move(motor):
    assert await identify(motor) == 69108
    await motor.enable(True)
    assert await motor.is_enabled() is True
    move = asyncio.create_task(motor.move_absolute(138220, timeout=30))
    await asyncio.sleep(0.01)  # the stop must be written after the move command
    await motor.stop()  # controlled stop, as in the capture
    with pytest.raises(MotionInterrupted):
        await move
    assert await motor.position() == 94400  # stopped partway to 138220


async def status_updates(motor):
    """Raw HW_START_UPDATEMSGS stream with the ACK heartbeat; updates() itself is not replayed (it is timing based)."""
    assert await identify(motor) == 1810268  # a different unit from the other captures
    async with motor.connection.events(predicate=lambda m: m.message_id == 0x0491) as events:
        await motor.send("HW_START_UPDATEMSGS")
        for batch in (4, 5, 5, 5, 5, 5):  # updates arriving between consecutive ACKs in the capture
            await motor.send("MOT_ACK_USTATUSUPDATE")
            for _ in range(batch):
                status = decode_motor_status(await anext(events), kind="dc")[0]
                assert status.position == 1810268 and MotorStatusBits.HOMED in status.status
        await motor.send("HW_STOP_UPDATEMSGS")


async def listen_then_read(motor):
    """hw_check --listen: nothing arrives unprompted from this unit (the capture starts 2 s before the first tx)."""
    async with motor.connection.events() as events:
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.05):
                await anext(events)
    assert await identify(motor) == 94398


async def listen_second_unit(motor):
    """The unit that streamed updates in the status-updates capture is quiet now: that stream was left over."""
    async with motor.connection.events() as events:
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.05):
                await anext(events)
    assert await identify(motor) == 1810268


async def listen_after_power_cycle(motor):
    """Second unit after a power cycle: quiet again, position counter back to 0 and not homed."""
    async with motor.connection.events() as events:
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.05):
                await anext(events)
    assert await identify(motor) == 0


async def updates_context_manager(motor):
    """Device.updates(): start, ACK heartbeat, stop. 28 updates arrive across six ACK intervals in the capture."""
    assert await identify(motor) == 0
    async with motor.updates(acknowledgement="MOT_ACK_USTATUSUPDATE", interval=0.1) as events:
        for _ in range(28):  # the capture's sixth ACK is its last; leave before a seventh would be sent
            status = decode_motor_status(await anext(events), kind="dc")[0]
            assert status.position == 0 and MotorStatusBits.HOMED not in status.status


async def jog(motor):
    assert await identify(motor) == 94398
    await motor.enable(True)
    assert await motor.is_enabled() is True
    async with motor.connection.events(predicate=lambda m: m.message_id in (0x0464, 0x0466)) as done:
        await motor.jog(1)  # direction 1 moved the stage towards LOWER counts on this unit (-17276 counts, ~0.5 mm)
        assert (await anext(done)).message_id == 0x0464
    assert await motor.position() == 77122


async def stop_immediate(motor):
    assert await identify(motor) == 77122
    await motor.enable(True)
    assert await motor.is_enabled() is True
    move = asyncio.create_task(motor.move_absolute(138220, timeout=30))
    await asyncio.sleep(0.01)
    await motor.stop(immediate=True)  # stop mode 1; the controller answered after ~0.15 s (profiled stop: ~0.8 s)
    with pytest.raises(MotionInterrupted):
        await move
    assert await motor.position() == 89750


async def timeout_closes_connection(motor):
    """A request to a bay that does not exist gets no reply; the library must then refuse further requests."""
    assert await identify(motor) == 89750
    ghost = device(motor.connection, "KDC101", destination=0x51)
    with pytest.raises(TimeoutError):
        await ghost.request("HW_REQ_INFO", "HW_GET_INFO", timeout=0.05)
    with pytest.raises(ConnectionClosed):
        await motor.position()


@pytest.mark.parametrize("name, scenario", [
    ("readonly-mts100m-z8", read_only), ("home-mts100m-z8", home), ("move-relative-mts100m-z8", move_relative),
    ("move-absolute-mts100m-z8", move_absolute), ("stop-mid-move-mts100m-z8", stop_mid_move),
    ("status-updates", status_updates), ("listen-then-readonly-mts100m-z8", listen_then_read),
    ("listen-second-unit", listen_second_unit), ("listen-after-power-cycle", listen_after_power_cycle),
    ("updates-context-manager", updates_context_manager), ("jog-direction1-mts100m-z8", jog), ("stop-immediate-mts100m-z8", stop_immediate),
    ("timeout-nonexistent-bay", timeout_closes_connection)])
async def test_session_matches_real_device(name, scenario):
    lines = (FIXTURES / f"{name}.jsonl").read_text().splitlines()
    frames = [(r["dir"], bytes.fromhex(r["hex"])) for r in map(json.loads, lines)]
    transport = ReplayTransport(frames)
    async with Connection(transport) as connection:
        await scenario(device(connection, "KDC101"))
    assert transport.index == len(frames)
