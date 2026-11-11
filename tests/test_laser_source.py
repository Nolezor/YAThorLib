"""KLS635/KLS1550 packets. Golden bytes come from the APT PDF examples (pp.327-355); replies use the
real 0x81/0x50 addressing, which the PDF examples garble."""
import asyncio
import struct

import pytest

from yathorlib import Connection, LaserSource, device
from test_connection import FakeTransport


async def exchange(t, call, reply_id, body):
    task = asyncio.create_task(call)
    sent = await t.tx.get()
    await t.reply(reply_id, source=0x50, data=body)
    return sent, await task


def test_factory_selects_typed_class_only_for_kls():
    c = Connection(FakeTransport())
    assert isinstance(device(c, "KLS635"), LaserSource) and isinstance(device(c, "KLS1550"), LaserSource)
    assert not isinstance(device(c, "TLS001"), LaserSource)


async def test_setpoint_five_percent_matches_pdf_bytes():
    t = FakeTransport()
    async with Connection(t) as c:
        laser = device(c, "KLS635")
        await laser.set_setpoint(0.05)
        assert (await t.tx.get()).encode().hex() == "00080400d0010100" "6606"
        sent, value = await exchange(t, laser.setpoint(), 0x802, struct.pack("<HH", 1, 0x666))
        assert sent.encode().hex() == "010801005001" and value == pytest.approx(0.05, abs=1e-4)
        with pytest.raises(ValueError):
            await laser.set_setpoint(1.1)


async def test_limits_readings_and_status_bits():
    t = FakeTransport()
    async with Connection(t) as c:
        laser = device(c, "KLS1550")
        _, limits = await exchange(t, laser.limits(), 0x802, struct.pack("<HHHH", 9, 200, 5, 1550))
        assert limits == {"max_current_raw": 200, "max_power_raw": 5, "wavelength_nm": 1550}
        _, read = await exchange(t, laser.readings(), 0x802, struct.pack("<HHH", 3, 0x1990, 0x0666))
        assert read["current"] == pytest.approx(0.2, abs=1e-3) and read["power"] == pytest.approx(0.05, abs=1e-3)
        _, bits = await exchange(t, laser.status_bits(), 0x802, struct.pack("<HHI", 7, 0, 0x2B))
        assert (bits["output"], bits["keyswitch"], bits["power_mode"], bits["interlock"]) == (True, True, False, True)


async def test_status_update_is_acknowledged():
    t = FakeTransport()
    async with Connection(t) as c:
        laser = device(c, "KLS635")
        sent, status = await exchange(t, laser.status(), 0x821, struct.pack("<HHI", 0x1990, 0x1990, 0x2B))
        assert sent.message_id == 0x820 and status["output"] and status["power"] == pytest.approx(0.2, abs=1e-3)
        assert (await t.tx.get()).message_id == 0x822


async def test_read_modify_write_keeps_reserved_words_and_uses_native_sub_ids():
    t = FakeTransport()
    async with Connection(t) as c:
        laser = device(c, "KLS635")
        task = asyncio.create_task(laser.set_op_mode("constant_current"))
        await t.tx.get()
        await t.reply(0x802, source=0x50, data=struct.pack("<H5H", 0x12, 0, 7, 8, 9, 10))
        sent = await t.tx.get()
        await task
        assert sent.data == struct.pack("<H5H", 0x12, 1, 7, 8, 9, 10)
        task = asyncio.create_task(laser.set_trigger_io(0x0B, 1, 1, 2))
        await t.tx.get()
        await t.reply(0x802, source=0x50, data=struct.pack("<7H", 0x10, 0, 1, 11, 0, 1, 12))
        assert (await t.tx.get()).data == struct.pack("<7H", 0x10, 0x0B, 1, 11, 1, 2, 12)
        await task
        for bad in (lambda: laser.set_trigger_io(5, 1, 1, 1), lambda: laser.set_trigger_io(1, 3, 1, 1),
                    lambda: laser.set_display_brightness(10), lambda: laser.set_control_source("pot")):
            with pytest.raises(ValueError):
                await bad()
