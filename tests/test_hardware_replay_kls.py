"""Replay of raw frames captured from a real KLS635 (reports itself as KLS101, firmware 1.1.2) via tools/laser_check.py.

Same rules as test_hardware_replay.py: every frame the library writes must equal the next captured tx; timing is not replayed.
The unit's output was already enabled when the first capture began.
"""
import asyncio
import json
import struct
from pathlib import Path

import pytest
from test_hardware_replay import ReplayTransport

from yathorlib import Connection, device

FIXTURES = Path(__file__).parent / "fixtures/hardware/KLS"


async def first_contact(laser, setpoint_raw):
    """The calls tools/laser_check.py makes before any write."""
    info = await laser.hardware_info()
    assert (info.model, info.firmware, info.serial_number) == ("KLS101", (1, 1, 2), 0)  # serial redacted
    assert await laser.limits() == {"max_current_raw": 9400, "max_power_raw": 8000, "max_power_mw": 8.0, "wavelength_nm": 635}
    assert await laser.setpoint() == pytest.approx(setpoint_raw / 32767)
    assert await laser.control_source() == "wheel+software"
    status = await laser.status()
    assert (status["output"], status["keyswitch"], status["interlock"], status["power_mode"]) == (True, True, True, False)
    assert status["raw"] == 0x8000022B  # output, keyswitch, interlock, mW display (0x20), and the ADC bits
    assert await laser.op_mode() == "constant_power"
    assert await laser.trigger_io() == {"mode1": 0, "polarity1": 1, "mode2": 0, "polarity2": 1}
    assert await laser.display_brightness() == 30
    return status


async def read_only(laser):
    status = await first_contact(laser, 0x1B32)
    assert status["current"] == pytest.approx(0x1238 / 32767) and status["power"] == pytest.approx(0x1B32 / 32767)


async def write_without_emitting(laser):
    await first_contact(laser, 0x1B32)
    await laser.set_setpoint(0.05)
    # Sent straight after the write, the readback still returned the old value (reply took 63 ms, not the usual 16).
    assert await laser.setpoint() == pytest.approx(0x1B32 / 32767)


async def output_on_for_three_seconds(laser):
    """Run after the write above, so the unit already held 5 %. While the output was on it pushed an unsolicited
    LA_GET_STATUSUPDATE every ~1.2 s, although HW_START_UPDATEMSGS was never sent."""
    await first_contact(laser, 0x0666)
    await laser.set_setpoint(0.05)
    assert await laser.setpoint() == pytest.approx(0x0666 / 32767)
    async with laser.connection.events(predicate=lambda m: m.message_id == 0x0821) as pushes:
        await laser.output(True)
        assert (await laser.status())["output"] is True
        await asyncio.sleep(0.01)  # the capture waits 3 s here
        # the events also carry the reply to our own status(): 0x111a, then the two pushes
        currents = [struct.unpack_from("<H", (await anext(pushes)).data)[0] for _ in range(3)]
    assert currents == [0x111A, 0x1119, 0x1117]
    assert (await laser.status())["current"] == pytest.approx(0x1116 / 32767)
    await laser.output(False)
    off = await laser.status()
    assert (off["output"], off["current"], off["raw"]) == (False, 0, 0x8000012A)


@pytest.mark.parametrize("name, scenario", [
    ("readonly-kls101", read_only), ("setpoint-write-no-emit", write_without_emitting),
    ("setpoint-and-output-on-3s", output_on_for_three_seconds)])
async def test_session_matches_real_device(name, scenario):
    lines = (FIXTURES / f"{name}.jsonl").read_text().splitlines()
    frames = [(r["dir"], bytes.fromhex(r["hex"])) for r in map(json.loads, lines)]
    transport = ReplayTransport(frames)
    async with Connection(transport) as connection:
        await scenario(device(connection, "KLS635"))
    assert transport.index == len(frames)
