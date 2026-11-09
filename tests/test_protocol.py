import random
import struct

import pytest

from yathorlib import FrameDecoder, Message, ProtocolError, MessageID, commands_for
from yathorlib.codecs import LAYOUTS, HardwareInfo, decode_motor_status


@pytest.mark.parametrize("message,hex_packet", [
    (Message(0x210, 0x22, param1=1, param2=1), "100201012201"),  # PDF p.52
    (Message(0x643, data=struct.pack("<Hh", 1, 30583)), "43060400d00101007777"),  # p.221
    (Message(0x8d4, data=struct.pack("<Hi", 1, 100)), "d4080600d001010064000000"),  # p.462
    (Message(0x800, data=struct.pack("<HH", 1, 1638)), "00080400d00101006606"),  # p.328
    (Message(0x840, data=struct.pack("<Hh", 1, 6500)), "40080400d00101006419"),  # p.392
])
def test_documented_packets(message, hex_packet):
    assert message.encode() == bytes.fromhex(hex_packet)
    assert Message.decode(bytes.fromhex(hex_packet)) == message


def test_fragmentation_and_coalescing():
    rng = random.Random(5)
    messages = [Message(i, data=rng.randbytes(i % 50)) if i % 2 else Message(i, param1=i % 256) for i in range(500)]
    stream = b"".join(m.encode() for m in messages)
    decoder = FrameDecoder()
    received = []
    while stream:
        size = rng.randrange(1, 100)
        received.extend(decoder.feed(stream[:size]))
        stream = stream[size:]
    decoder.eof()
    assert received == messages


def test_zero_length_data_is_distinct_from_short_packet():
    assert Message(1, data=b"").encode() != Message(1).encode()
    assert Message.decode(Message(1, data=b"").encode()).data == b""


def test_truncation_and_oversize():
    with pytest.raises(ProtocolError):
        Message.decode(b"\x00")
    d = FrameDecoder(10)
    with pytest.raises(ProtocolError):
        d.feed(Message(1, data=bytes(11)).encode()[:6])
    d = FrameDecoder()
    d.feed(b"\x00")
    with pytest.raises(ProtocolError):
        d.eof()
    with pytest.raises(ValueError):
        Message(1, destination=0xd0)
    with pytest.raises(ValueError):
        Message(1, param1=1, data=b"x")


def test_negative_positions_and_hardware_info():
    assert LAYOUTS["MOT_POSCOUNTER"].unpack(bytes.fromhex("0100ffffffff"))["position"] == -1
    raw = struct.pack("<I8sH4B60sHHH", 27000001, b"KDC101", 27, 2, 1, 3, 0, bytes(60), 1, 2, 1)
    info = HardwareInfo.decode(Message(6, 1, 0x50, data=raw))
    assert (info.model, info.firmware, info.channels) == ("KDC101", (3, 1, 2), 1)
    msg = Message(0x491, data=struct.pack("<HiHhI", 1, -100, 250, -25, 0x80000400))
    status = decode_motor_status(msg, kind="dc")[0]
    assert (status.position, status.current_ma) == (-100, -25)


def test_body_overrides_contents_error_and_model_groups():
    assert MessageID.MOT_SET_BOWINDEX == 0x04f4
    assert "MOT_MOVE_ABSOLUTE" in commands_for("KDC101")
    assert "MOT_MOVE_ABSOLUTE" in commands_for("BBD302")
    assert "HW_SET_KCUBEMMILOCK" in commands_for("KLS635")
    assert "TEC_SET_PARAMS" in commands_for("TTC001")
    with pytest.raises(ValueError):
        commands_for("UNKNOWN")
