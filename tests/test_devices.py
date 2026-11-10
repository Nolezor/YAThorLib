import asyncio
import struct

import pytest

from yathorlib import Connection, InertialMotor, Laser, Motor, NanoTrak, Piezo, PiezoStage, QuadDetector, Solenoid, StrainGauge, TemperatureController, UnsupportedCommand, device
from test_connection import FakeTransport


@pytest.mark.parametrize("model,cls", [
    ("KDC101", Motor), ("TDC001", Motor), ("BBD301", Motor), ("BSC203", Motor),
    ("KST101", Motor), ("LTS150", Motor), ("MLJ150", Motor), ("MPC320", Motor),
    ("KVS30", Motor), ("KVC101", Motor), ("MFF102", Motor), ("K10CR1", Motor),
    ("KPZ101", Piezo), ("BPC303", Piezo), ("PPC102", Piezo), ("MPZ601", Piezo),
    ("KPC101", Piezo), ("KSG101", StrainGauge), ("TSG001", StrainGauge),
    ("KNA101", NanoTrak), ("MNA601", NanoTrak), ("TNA001", NanoTrak),
    ("KSC101", Solenoid), ("TSC001", Solenoid),
    ("KLS635", Laser), ("KLD101", Laser), ("TLD001", Laser), ("TLS001", Laser),
    ("TTC001", TemperatureController), ("KPA101", QuadDetector), ("TQD001", QuadDetector),
    ("KIM101", InertialMotor), ("TIM101", InertialMotor), ("PDXC2", PiezoStage),
])
def test_documented_family_selection(model, cls):
    assert isinstance(device(Connection(FakeTransport()), model), cls)


async def test_submessage_channel_mask_from_native_kinesis():
    t = FakeTransport()
    async with Connection(t) as c:
        motor = device(c, "KIM101", channel=4)
        pending = asyncio.create_task(motor.position())
        assert (await t.tx.get()).encode().hex() == "c10805045001"
        await t.reply(0x8c2, data=struct.pack("<HHii", 5, 1, 20, 0))
        await asyncio.sleep(0)
        assert not pending.done()
        await t.reply(0x8c2, data=struct.pack("<HHii", 5, 4, -123, 0))
        assert await pending == -123


async def test_solenoid_cycle_golden_packet():
    t = FakeTransport()
    async with Connection(t) as c:
        await device(c, "KSC101").set_cycle(1000, 1000, 20)
        assert (await t.tx.get()).encode().hex() == "c3040e00d0010100e8030000e803000014000000"


async def test_nanotrak_float_and_temperature_negative():
    t = FakeTransport()
    async with Connection(t) as c:
        req = asyncio.create_task(device(c, "KNA101").readings())
        assert (await t.tx.get()).encode().hex() == "390600005001"
        await t.reply(0x63a, data=struct.pack("<fHHH", 1e-6, 16384, 8, 1))
        assert (await req)["absolute"] == pytest.approx(1e-6)
        req = asyncio.create_task(device(c, "TTC001").setpoint_raw())
        assert (await t.tx.get()).encode().hex() == "410801005001"
        await t.reply(0x842, data=struct.pack("<Hh", 1, -4500))
        assert await req == -4500


async def test_capability_rejection_before_any_write():
    t = FakeTransport()
    async with Connection(t) as c:
        with pytest.raises(UnsupportedCommand):
            await device(c, "TTC001").send("MOT_MOVE_HOME")
        assert t.tx.empty()


async def test_stop_updates_sends_hw_stop_updatemsgs():
    t = FakeTransport()
    async with Connection(t) as c:
        await device(c, "KDC101").stop_updates()
        assert (await t.tx.get()).message_id == 0x12


async def test_update_start_ack_stop():
    t = FakeTransport()
    async with Connection(t) as c:
        motor = device(c, "KDC101")
        async with motor.updates(acknowledgement="MOT_ACK_USTATUSUPDATE", interval=0.01):
            assert (await t.tx.get()).message_id == 0x11
            assert (await t.tx.get()).message_id == 0x492
        assert (await t.tx.get()).message_id == 0x12
