"""First-contact check for a KLS635/KLS1550 laser source. Logs raw frames to JSONL (as hw_check.py).

Read-only by default, the laser cannot emit:
  python tools/laser_check.py /dev/ttyUSB0 KLS635
Changing the setpoint does not emit either, but is a write:
  python tools/laser_check.py /dev/ttyUSB0 KLS635 --setpoint 0.05
The laser emits only with --on SECONDS. 635 nm is class 3B: eye protection, fibre connected or capped,
interlock fitted and key on. The output is switched off again even if the check fails.
  python tools/laser_check.py /dev/ttyUSB0 KLS635 --setpoint 0.05 --on 3
"""
import argparse
import asyncio
import time
from pathlib import Path

from hw_check import log_traffic

from yathorlib import Connection, device


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("port")
    ap.add_argument("model", choices=["KLS635", "KLS1550"])
    ap.add_argument("--setpoint", type=float, metavar="FRACTION", help="power setpoint, 0..1 of maximum")
    ap.add_argument("--on", type=float, metavar="SECONDS", help="enable the laser output for this long (max 30)")
    ap.add_argument("--capture", type=Path, default=Path(f"capture-{int(time.time())}.jsonl"))
    args = ap.parse_args()
    if args.on is not None and not 0 < args.on <= 30:
        ap.error("--on must be between 0 and 30 seconds")
    log_traffic(args.capture)
    print(f"capture: {args.capture}")
    async with await Connection.open_serial(args.port) as connection:
        laser = device(connection, args.model)
        print("hardware_info:", await laser.hardware_info())
        print("limits:", await laser.limits())
        print("setpoint:", await laser.setpoint())
        print("control_source:", await laser.control_source())
        print("status:", await laser.status())
        for name in ("op_mode", "trigger_io", "display_brightness"):  # sub-IDs 0x12/0x10/0x14: native-only or contested
            print(f"{name}:", await getattr(laser, name)())
        if args.setpoint is not None:
            await laser.set_setpoint(args.setpoint)
            print("setpoint now:", await laser.setpoint())
        if args.on is not None:
            try:
                await laser.output(True)
                await asyncio.sleep(0.5)
                print("output on; status:", await laser.status())
                await asyncio.sleep(args.on)
                print("status before off:", await laser.status())
            finally:
                await laser.output(False)
            await asyncio.sleep(0.3)
            print("output off; status:", await laser.status())


if __name__ == "__main__":
    asyncio.run(main())
