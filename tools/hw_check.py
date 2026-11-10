"""First-contact check for a real controller. Logs every raw frame to a JSONL capture.

Read-only by default. Anything that energizes or moves the stage needs an explicit flag:
  python tools/hw_check.py /dev/ttyUSB0 KDC101 --kind dc
  python tools/hw_check.py /dev/ttyUSB0 KDC101 --kind dc --enable --home
  python tools/hw_check.py /dev/ttyUSB0 KDC101 --kind dc --enable --move-relative 34555   # about 1 mm on an MTS-Z8 stage
  python tools/hw_check.py /dev/ttyUSB0 KDC101 --kind dc --enable --move-absolute 69110     # ~2 mm; homed stage only
  python tools/hw_check.py /dev/ttyUSB0 KDC101 --kind dc --enable --stop-test 138220        # start ~4 mm move, stop it
  python tools/hw_check.py /dev/ttyUSB0 KDC101 --kind dc --updates 3                       # 3 s of status updates + ACKs
Absolute moves and stop tests assume a homed stage: absolute targets are in device units from home, so
choose them inside the stage's travel (MTS100/M-Z8: 0 to ~3.45 million counts).
Model is the CONTROLLER (check hardware_info), not the stage name. Positions are device units.
"""
import argparse
import asyncio
import json
import time
from pathlib import Path

from yathorlib import Connection, MotionInterrupted, device
from yathorlib.connection import StreamTransport


def log_traffic(path: Path) -> None:
    """Patch the transport class so the reader task's very first read is captured too."""
    out = path.open("a", buffering=1)
    start = time.monotonic()

    def record(direction: str, data: bytes) -> None:
        out.write(json.dumps({"t": round(time.monotonic() - start, 4), "dir": direction, "hex": data.hex()}) + "\n")

    read, write = StreamTransport.read, StreamTransport.write

    async def logged_read(self, size):
        data = await read(self, size)
        record("rx", data)
        return data

    async def logged_write(self, data):
        record("tx", data)
        await write(self, data)

    StreamTransport.read, StreamTransport.write = logged_read, logged_write  # type: ignore[method-assign]


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("port")
    ap.add_argument("model", help="controller model, e.g. KDC101 or KST101")
    ap.add_argument("--kind", choices=["dc", "stepper"], required=True, help="motor status layout")
    ap.add_argument("--enable", action="store_true", help="enable the channel output")
    ap.add_argument("--home", action="store_true", help="home the stage (requires --enable)")
    ap.add_argument("--move-relative", type=int, metavar="UNITS", help="small relative move (requires --enable)")
    ap.add_argument("--move-absolute", type=int, metavar="UNITS", help="absolute move (requires --enable)")
    ap.add_argument("--stop-test", type=int, metavar="UNITS",
                    help="start an absolute move then stop it mid-way (requires --enable)")
    ap.add_argument("--stop-after", type=float, default=0.7, metavar="SECONDS", help="delay before the stop")
    ap.add_argument("--updates", type=float, metavar="SECONDS", help="collect unsolicited status updates")
    ap.add_argument("--capture", type=Path, default=Path(f"capture-{int(time.time())}.jsonl"))
    args = ap.parse_args()
    moves = args.home or args.move_relative is not None or args.move_absolute is not None
    if (moves or args.stop_test is not None) and not args.enable:
        ap.error("--home, --move-* and --stop-test require --enable")
    if args.updates is not None and not 0 < args.updates <= 60:
        ap.error("--updates must be between 0 and 60 seconds")

    log_traffic(args.capture)
    print(f"capture: {args.capture}")
    async with await Connection.open_serial(args.port) as connection:
        motor = device(connection, args.model)
        print("hardware_info:", await motor.hardware_info())
        print("enabled:", await motor.is_enabled())
        print("position:", await motor.position())
        print("status:", await motor.status(kind=args.kind))
        if args.enable:
            await motor.enable(True)
            print("enabled:", await motor.is_enabled())
        try:
            if args.home:
                await motor.home(timeout=120)
                print("homed; position:", await motor.position())
            if args.move_relative is not None:
                await motor.move_relative(args.move_relative, timeout=60)
                print("moved; position:", await motor.position())
            if args.move_absolute is not None:
                await motor.move_absolute(args.move_absolute, timeout=120)
                print("moved; position:", await motor.position())
            if args.stop_test is not None:
                move = asyncio.create_task(motor.move_absolute(args.stop_test, timeout=120))
                await asyncio.sleep(args.stop_after)
                await motor.stop()  # controlled stop
                try:
                    await move
                    print("stop test: the move finished before the stop took effect; use a longer move")
                except MotionInterrupted:
                    print("stop test: move interrupted as expected")
                print("position after stop:", await motor.position())
            if args.updates is not None:
                counts: dict[int, int] = {}
                async with motor.updates(acknowledgement="MOT_ACK_USTATUSUPDATE") as events:
                    try:
                        async with asyncio.timeout(args.updates):
                            async for message in events:
                                counts[message.message_id] = counts.get(message.message_id, 0) + 1
                    except TimeoutError:
                        pass
                print("updates received by message id:", {hex(k): v for k, v in counts.items()})
        except BaseException:
            await motor.stop(immediate=True)  # closing the connection does not stop motion
            raise


if __name__ == "__main__":
    asyncio.run(main())
