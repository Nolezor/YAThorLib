import asyncio
import struct

import pytest

from yathorlib import Connection, LiquidCrystal, MotionInterrupted, Message, device
from test_connection import FakeTransport


async def test_native_encoder_position_has_no_channel_prefix():
    t = FakeTransport()
    async with Connection(t) as c:
        encoder = device(c, "PositionReadoutEncoder")
        request = asyncio.create_task(encoder.position())
        assert (await t.tx.get()).encode().hex() == "a10301005001"
        await t.reply(0x3a2, data=struct.pack("<i", -123456))
        assert await request == -123456
        await encoder.zero()
        assert (await t.tx.get()).encode().hex() == "a00301005001"


async def test_klc_presets_from_native_writer_and_response_handlers():
    t = FakeTransport()
    async with Connection(t) as c:
        klc = device(c, "KLC101")
        assert isinstance(klc, LiquidCrystal)
        request = asyncio.create_task(klc.preset(2))
        assert (await t.tx.get()).encode().hex() == "022001025001"
        await t.reply(0x2003, data=struct.pack("<HHH", 1, 2, 12500))
        assert (await t.tx.get()).encode().hex() == "062001025001"
        await t.reply(0x2007, data=struct.pack("<HHH", 1, 2, 5000))
        assert await request == {"voltage_mv": 12500, "frequency_hz": 5000}
        await klc.set_preset(2, voltage_mv=12500, frequency_hz=5000)
        assert (await t.tx.get()).encode().hex() == "01200600d00101000200d430"
        assert (await t.tx.get()).encode().hex() == "05200600d001010002008813"
        with pytest.raises(ValueError):
            await klc.set_preset(1, voltage_mv=26000, frequency_hz=5000)
        assert t.tx.empty()


async def test_stop_interrupts_motion_without_poisoning_connection():
    t = FakeTransport()
    async with Connection(t) as c:
        motor = device(c, "KDC101")
        move = asyncio.create_task(motor.move_absolute(100))
        assert (await t.tx.get()).message_id == 0x453
        await motor.stop()
        assert (await t.tx.get()).encode().hex() == "650401025001"
        await t.reply(0x466, data=struct.pack("<HiHhI", 1, 75, 0, 0, 0))
        with pytest.raises(MotionInterrupted):
            await move
        await c.send(Message(5))
        assert not t.closed


async def test_stop_interrupts_homing():
    t = FakeTransport()
    async with Connection(t) as c:
        motor = device(c, 'KDC101')
        home = asyncio.create_task(motor.home())
        assert (await t.tx.get()).message_id == 0x443
        await motor.stop()
        await t.tx.get()
        await t.reply(0x466, data=struct.pack('<HiHhI', 1, 0, 0, 0, 0))
        with pytest.raises(MotionInterrupted):
            await home
        assert not t.closed


async def test_update_ownership_is_shared_across_device_objects():
    t = FakeTransport()
    async with Connection(t) as c:
        a, b = device(c, 'KDC101'), device(c, 'KDC101')
        async with a.updates():
            assert (await t.tx.get()).message_id == 0x11
            with pytest.raises(RuntimeError, match='already active'):
                async with b.updates():
                    pytest.fail('duplicate update owner')
            assert t.tx.empty()
        assert (await t.tx.get()).message_id == 0x12
        async with b.updates():
            assert (await t.tx.get()).message_id == 0x11
        assert (await t.tx.get()).message_id == 0x12
