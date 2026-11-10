"""First-contact check for a real controller. Logs every raw frame to a JSONL capture.

Read-only by default. Anything that energizes or moves the stage needs an explicit flag:
  python tools/hw_check.py /dev/ttyUSB0 KDC101 --kind dc
  python tools/hw_check.py /dev/ttyUSB0 KDC101 --kind dc --enable --home
  python tools/hw_check.py /dev/ttyUSB0 KDC101 --kind dc --enable --move-relative 34555   # about 1 mm on an MTS-Z8 stage
  python tools/hw_check.py /dev/ttyUSB0 KDC101 --kind dc --enable --move-absolute 69110     # ~2 mm; homed stage only
  python tools/hw_check.py /dev/ttyUSB0 KDC101 --kind dc --enable --stop-test 138220        # start ~4 mm move, stop it
  python tools/hw_check.py /dev/ttyUSB0 KDC101 --kind dc --updates 3                       # 3 s of status updates + ACKs
  python tools/hw_check.py /dev/ttyUSB0 KDC101 --kind dc --listen 2                        # passive: any unsolicited traffic?
  python tools/hw_check.py /dev/ttyUSB0 KDC101 --kind dc --enable --jog forward            # one jog step (stored step size)
  python tools/hw_check.py /dev/ttyUSB0 KDC101 --kind dc --enable --stop-test 138220 --stop-immediate
  python tools/hw_check.py /dev/ttyUSB0 KDC101 --kind dc --timeout-test                    # ends the session by design
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
    ap.add_argument("--stop-immediate", action="store_true", help="use the immediate stop in --stop-test")
    ap.add_argument("--jog", choices=["forward", "reverse"], help="one jog step with the stored settings (requires --enable)")
    ap.add_argument("--listen", type=float, metavar="SECONDS", help="first listen without sending anything")
    ap.add_argument("--stop-updates", action="store_true", help="send HW_STOP_UPDATEMSGS before anything else")
    ap.add_argument("--timeout-test", action="store_true",
                    help="ask a non-existent bay for info: expect a timeout that closes the connection")
    ap.add_argument("--capture", type=Path, default=Path(f"capture-{int(time.time())}.jsonl"))
    args = ap.parse_args()
    moves = args.home or args.move_relative is not None or args.move_absolute is not None
    if (moves or args.stop_test is not None or args.jog) and not args.enable:
        ap.error("--home, --move-*, --jog and --stop-test require --enable")
    if args.updates is not None and not 0 < args.updates <= 60:
        ap.error("--updates must be between 0 and 60 seconds")

    log_traffic(args.capture)
    print(f"capture: {args.capture}")
    async with await Connection.open_serial(args.port) as connection:
        motor = device(connection, args.model)
        if args.listen:
            seen: dict[int, int] = {}
            async with connection.events() as events:
                try:
                    async with asyncio.timeout(args.listen):
                        async for message in events:
                            seen[message.message_id] = seen.get(message.message_id, 0) + 1
                except TimeoutError:
                    pass
            print("unsolicited before any request:", {hex(k): v for k, v in seen.items()} or "none")
        if args.stop_updates:
            await motor.stop_updates()
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
            if args.jog:
                async with connection.events(predicate=lambda m: m.message_id in (0x0464, 0x0466)) as done:
                    await motor.jog(1 if args.jog == "forward" else 2)
                    async with asyncio.timeout(30):
                        end = await anext(done)
                print(f"jog ended with {end.message_id:#06x}; position:", await motor.position())
            if args.stop_test is not None:
                move = asyncio.create_task(motor.move_absolute(args.stop_test, timeout=120))
                await asyncio.sleep(args.stop_after)
                await motor.stop(immediate=args.stop_immediate)
                try:
                    await move
                    print("stop test: the move finished before the stop took effect; use a longer move")
                except MotionInterrupted:
                    print("stop test: move interrupted as expected")
                print("position after stop:", await motor.position())
            if args.timeout_test:
                ghost = device(connection, args.model, destination=0x51)  # no such bay
                try:
                    await ghost.request("HW_REQ_INFO", "HW_GET_INFO", timeout=1.0)
                    print("timeout test: unexpected reply from a non-existent bay")
                except TimeoutError:
                    print("timeout test: timed out as expected")
                try:
                    await motor.position()
                    print("timeout test: connection still usable (unexpected)")
                except ConnectionError as exc:
                    print("timeout test: connection closed as designed:", type(exc).__name__)
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
