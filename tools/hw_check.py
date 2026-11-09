"""First-contact check for a real controller. Logs every raw frame to a JSONL capture.

Read-only by default. Anything that energizes or moves the stage needs an explicit flag:
  python tools/hw_check.py /dev/ttyUSB0 KDC101 --kind dc
  python tools/hw_check.py /dev/ttyUSB0 KDC101 --kind dc --enable --home
  python tools/hw_check.py /dev/ttyUSB0 KDC101 --kind dc --enable --move-relative 2000
Model is the CONTROLLER (check hardware_info), not the stage name. Positions are device units.
"""
import argparse
import asyncio
import json
import time
from pathlib import Path

from yathorlib import Connection, device
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
    ap.add_argument("--capture", type=Path, default=Path(f"capture-{int(time.time())}.jsonl"))
    args = ap.parse_args()
    if (args.home or args.move_relative is not None) and not args.enable:
        ap.error("--home and --move-relative require --enable")

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
        except BaseException:
            await motor.stop(immediate=True)  # closing the connection does not stop motion
            raise


if __name__ == "__main__":
    asyncio.run(main())
