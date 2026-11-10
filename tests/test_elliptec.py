import asyncio

import pytest

from yathorlib import Elliptec, ElliptecBus, ElliptecError, ElliptecInfo
from yathorlib.connection import ConnectionClosed


class Fake:
    def __init__(self):
        self.rx, self.tx, self.closed = asyncio.Queue(), [], False

    async def read(self, size):
        return await self.rx.get()

    async def write(self, data):
        self.tx.append(data)

    async def close(self):
        self.closed = True

    def reply(self, *lines):
        for line in lines:
            self.rx.put_nowait(line.encode() + b"\r\n")



def test_info_parse_manual_example_and_scales():
    info = ElliptecInfo.parse("0IN06123456782015018100 1F00000001".replace(" ", ""))
    assert (info.device_type, info.serial, info.year, info.firmware) == (6, "12345678", 2015, 0.1)
    assert (info.hardware, info.imperial, info.travel, info.pulses, info.motors) == (1, True, 31, 1, 1)
    ell14 = ElliptecInfo.parse("2IN0E123456782023" "17" "01" "0168" "00023000")
    assert (ell14.unit, ell14.pulses, ell14.motors) == ("deg", 143360, 2)
    assert ell14.pulses_per_unit == pytest.approx(398.22, abs=0.01)
    ell20 = ElliptecInfo.parse("0IN14123456782024" "10" "01" "003C" "00000400")
    assert ell20.device_type == 0x14 and ell20.unit == "mm" and ell20.pulses_per_unit == 1024
    with pytest.raises(ValueError):
        ElliptecInfo.parse("0GS00")


async def test_move_ignores_busy_and_other_addresses_and_encodes_signed_hex():
    t = Fake()
    stage = Elliptec(ElliptecBus(t), "a")
    task = asyncio.create_task(stage.move_absolute(-1))
    await asyncio.sleep(0)
    assert t.tx == [b"Ama" b"FFFFFFFF"]
    t.reply("BPO00000001", "AGS09", "AGS00", "ABO00000002", "APO00002000")
    assert await task == 0x2000


async def test_status_error_raises_but_status_command_returns_code():
    t = Fake()
    stage = Elliptec(ElliptecBus(t))
    task = asyncio.create_task(stage.home())
    await asyncio.sleep(0)
    t.reply("0GS0C")  # hex: 12 = out of range
    with pytest.raises(ElliptecError) as err:
        await task
    assert err.value.code == 12 and t.tx == [b"0ho0"]
    task = asyncio.create_task(stage.status())
    await asyncio.sleep(0)
    t.reply("0GS03")
    assert await task == 3


async def test_set_commands_wait_for_ok_through_busy_and_address_change():
    t = Fake()
    stage = Elliptec(ElliptecBus(t), "0")
    task = asyncio.create_task(stage.optimize())
    await asyncio.sleep(0)
    t.reply("0GS09", "0GS09", "0GS00")
    await task
    assert t.tx == [b"0om"]
    task = asyncio.create_task(stage.set_address("b"))
    await asyncio.sleep(0)
    t.reply("BGS00")
    await task
    assert stage.address == "B" and t.tx[-1] == b"0caB"


async def test_motor_info_manual_example_and_period_encoding():
    t = Fake()
    stage = Elliptec(ElliptecBus(t))
    task = asyncio.create_task(stage.motor_info(1))
    await asyncio.sleep(0)
    t.reply("0I1100428FFFFFFFF00BD008B")
    info = await task
    assert info.loop and not info.running and info.current == pytest.approx(0.57, abs=0.005)
    assert info.forward_hz == pytest.approx(78_000, rel=0.01) and info.backward_hz == pytest.approx(106_000, rel=0.01)
    # The manual's "0f1804E" example treats 78 (kHz) as the period; 14740000/78 kHz is 189 = 0xBD, as in I1.
    for call, wire in ((lambda: stage.set_period(1, True, 78_000, persist=True), b"0f180BD"),
                       (lambda: stage.set_period(2, False, None), b"0b28FFF")):
        task = asyncio.create_task(call())
        await asyncio.sleep(0)
        t.reply("0GS00")
        await task
        assert t.tx[-1] == wire
    with pytest.raises(ValueError):
        await stage.set_period(3, True, 78_000)


async def test_slider_position_uses_vendor_step():
    t = Fake()
    stage = Elliptec(ElliptecBus(t), "1")
    task = asyncio.create_task(stage.select_position(2))
    await asyncio.sleep(0)
    t.reply("1IN0912345678202301810 01F00000001".replace(" ", ""))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    t.reply("1PO00000040")
    assert await task == 64 and t.tx[-1] == b"1ma00000040"


async def test_scan_skips_silent_addresses_and_timeout_closes_otherwise():
    t = Fake()
    bus = ElliptecBus(t)
    task = asyncio.create_task(bus.scan("0", "1", timeout=0.02))
    await asyncio.sleep(0)
    t.reply("0IN06123456782015018100 1F00000001".replace(" ", ""))
    found = await task
    assert [i.address for i in found] == ["0"] and not t.closed
    with pytest.raises(TimeoutError, match="no PO reply from address 0"):
        await bus.request("0", "gp", expect="PO", timeout=0.01)
    assert t.closed
    with pytest.raises(ConnectionClosed):
        await bus.request("0", "gp", expect="PO")
