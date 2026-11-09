"""Real pyserial-asyncio transport against a Linux pseudoterminal controller."""
import asyncio
import os
import sys

import pytest

from yathorlib import Connection, Message


@pytest.mark.skipif(sys.platform != "linux", reason="Linux PTY integration")
async def test_serial_transport_pty():
    import pty
    master, slave = pty.openpty()
    try:
        path = os.ttyname(slave)
        async with await Connection.open_serial(path, rtscts=False) as connection:
            task = asyncio.create_task(connection.request(Message(5), 6))
            request = await asyncio.wait_for(asyncio.to_thread(os.read, master, 6), 2)
            assert request == Message(5).encode()
            reply = Message(6, 1, 0x50, data=b"linux-serial").encode()
            os.write(master, reply[:3])
            await asyncio.sleep(0.005)
            os.write(master, reply[3:])
            assert (await task).data == b"linux-serial"
    finally:
        os.close(master)
        os.close(slave)
