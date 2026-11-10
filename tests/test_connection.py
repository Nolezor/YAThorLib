import asyncio
import struct

import pytest

from yathorlib import Connection, ConnectionClosed, DeviceError, EventOverflow, Message, device


class FakeTransport:
    def __init__(self):
        self.rx = asyncio.Queue()
        self.tx = asyncio.Queue()
        self.closed = False

    async def read(self, size):
        return await self.rx.get()

    async def write(self, data):
        await self.tx.put(Message.decode(data))

    async def close(self):
        self.closed = True

    async def reply(self, mid=6, source=0x50, data=b"", destination=1):
        await self.rx.put(Message(mid, destination, source, data=data).encode())


async def test_immediate_reply_matching_and_events():
    transport = FakeTransport()
    async with Connection(transport) as conn, conn.events() as events:
        pending = asyncio.create_task(conn.request(Message(5), 6))
        await transport.tx.get()
        await transport.reply(source=0x21)
        assert (await anext(events)).source == 0x21
        assert not pending.done()
        await transport.reply(data=b"answer")
        assert (await pending).data == b"answer"
        assert (await anext(events)).data == b"answer"
    assert transport.closed


async def test_requests_are_serialized():
    t = FakeTransport()
    async with Connection(t) as c:
        first = asyncio.create_task(c.request(Message(5), 6))
        second = asyncio.create_task(c.request(Message(5), 6))
        await t.tx.get()
        await asyncio.sleep(0)
        assert t.tx.empty()
        await t.reply(data=b"first")
        assert (await first).data == b"first"
        await t.tx.get()
        await t.reply(data=b"second")
        assert (await second).data == b"second"


async def test_timeout_closes_to_prevent_stale_reply_reuse():
    t = FakeTransport()
    c = Connection(t, timeout=0.01)
    with pytest.raises(TimeoutError, match="no reply from 0x50 to message 0x0005"):
        await c.request(Message(5), 6)
    assert t.closed
    await t.reply()
    with pytest.raises(ConnectionClosed):
        await c.request(Message(5), 6)


async def test_cancel_in_flight_closes_but_cancel_queued_does_not():
    t = FakeTransport()
    async with Connection(t) as c:
        first = asyncio.create_task(c.request(Message(5), 6))
        await t.tx.get()
        queued = asyncio.create_task(c.request(Message(5), 6))
        await asyncio.sleep(0)
        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued
        assert not t.closed
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert t.closed


async def test_eof_and_rich_errors():
    t = FakeTransport()
    async with Connection(t) as c:
        req = asyncio.create_task(c.request(Message(5), 6))
        await t.tx.get()
        await t.reply(0x81, data=struct.pack("<HH64s", 5, 9, b"fault"))
        with pytest.raises(DeviceError, match="fault"):
            await req
        req = asyncio.create_task(c.request(Message(5), 6))
        await t.tx.get()
        await t.rx.put(b"")
        with pytest.raises(ConnectionClosed):
            await req


async def test_overflow_is_explicit():
    t = FakeTransport()
    async with Connection(t) as c, c.events(max_queue=1) as events:
        await t.rx.put(Message(6, 1, 0x50).encode() * 3)
        await asyncio.sleep(0)
        with pytest.raises(EventOverflow):
            await anext(events)


async def test_device_signed_position_and_move_completion_channel():
    t = FakeTransport()
    async with Connection(t) as c:
        motor = device(c, "KDC101")
        req = asyncio.create_task(motor.position())
        packet = await t.tx.get()
        assert packet.encode().hex() == "110401005001"
        await t.reply(0x412, data=struct.pack("<Hi", 1, -10))
        assert await req == -10
        req = asyncio.create_task(motor.move_absolute(123))
        assert (await t.tx.get()).encode().hex() == "53040600d00101007b000000"
        await t.reply(0x464, data=struct.pack("<HiHhI", 2, 123, 0, 0, 0))
        await asyncio.sleep(0)
        assert not req.done()
        await t.reply(0x464, data=struct.pack("<HiHhI", 1, 123, 0, 0, 0))
        assert (await req).word() == 1


async def test_tcp_loopback_integration():
    async def controller(reader, writer):
        assert await reader.readexactly(6) == Message(5).encode()
        reply = Message(6, 1, 0x50, data=b"abc").encode()
        writer.write(reply[:4])
        await writer.drain()
        await asyncio.sleep(0.005)
        writer.write(reply[4:])
        await writer.drain()
        writer.close()
        await writer.wait_closed()
    server = await asyncio.start_server(controller, "127.0.0.1", 0)
    async with server:
        port = server.sockets[0].getsockname()[1]
        async with await Connection.open_tcp("127.0.0.1", port) as c:
            assert (await c.request(Message(5), 6)).data == b"abc"
