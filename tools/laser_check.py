"""First-contact check for a KLS635/KLS1550 laser source. Logs raw frames to JSONL (as hw_check.py).

Read-only by default, the laser cannot emit:
  python tools/laser_check.py /dev/ttyUSB0 KLS635
Changing the setpoint does not emit either, but is a write:
  python tools/laser_check.py /dev/ttyUSB0 KLS635 --setpoint 0.05
The laser emits only with --on SECONDS. 635 nm is class 3B: eye protection, fibre connected or capped,
interlock fitted and key on. The output is switched off again even if the check fails.
  python tools/laser_check.py /dev/ttyUSB0 KLS635 --setpoint 0.05 --on 3

Open-question tests. Each writes a value, reads it back, and restores the original even on failure.
The first four refuse to run while the output is enabled and never emit:
  --op-mode-test            flip constant power/current; shows op_mode next to status bit 0x4 (do they agree?)
  --brightness-test PERCENT set the display brightness (30..100): does the display change? (sub-ID 0x14)
  --control-source-test     switch software/wheel+software and back
  --trigger-test            flip both trigger polarities (refuses unless both trigger modes are 0)
--sweep SECONDS emits: output on at setpoints 0.2, 0.5 and 0.8 for SECONDS each (max 30), printing the status
every second. Read the unit's display (mA and mW) during each step, to compare with the printed current/power.
Output off and the original setpoint are restored at the end.
"""
import argparse
import asyncio
import time
from pathlib import Path

from hw_check import log_traffic

from yathorlib import Connection, device


async def change(read, write, value, same=lambda a, b: a == b):
    """Write, then poll the readback: it lags a write on this unit. Returns the last readback."""
    await write(value)
    for _ in range(30):
        got = await read()
        if same(got, value):
            break
        await asyncio.sleep(0.1)
    return got


async def trial(name, read, write, new, *, probe=None, look=0.0):
    """Set `new`, show the readback (and `probe`, if any, before and after), wait `look` s, then restore."""
    old = await read()
    before = await probe() if probe else None
    try:
        got = await change(read, write, new)
        await asyncio.sleep(0.5)
        after = await probe() if probe else None
        print(f"{name}: {old} -> {got} (wanted {new})" + (f"; probe {before} -> {after}" if probe else ""))
        await asyncio.sleep(look)
    finally:
        await change(read, write, old)
        print(f"{name}: restored to {await read()}")


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("port")
    ap.add_argument("model", choices=["KLS635", "KLS1550", "KLS101"])
    ap.add_argument("--setpoint", type=float, metavar="FRACTION", help="power setpoint, 0..1 of maximum")
    ap.add_argument("--on", type=float, metavar="SECONDS", help="enable the laser output for this long (max 30)")
    ap.add_argument("--op-mode-test", action="store_true")
    ap.add_argument("--brightness-test", type=int, metavar="PERCENT")
    ap.add_argument("--control-source-test", action="store_true")
    ap.add_argument("--trigger-test", action="store_true")
    ap.add_argument("--sweep", type=int, metavar="SECONDS", help="emit at 3 setpoints for this long each (max 30)")
    ap.add_argument("--capture", type=Path, default=Path(f"capture-{int(time.time())}.jsonl"))
    args = ap.parse_args()
    if args.on is not None and not 0 < args.on <= 30:
        ap.error("--on must be between 0 and 30 seconds")
    if args.sweep is not None and not 1 <= args.sweep <= 30:
        ap.error("--sweep must be between 1 and 30 seconds")
    if args.brightness_test is not None and not 30 <= args.brightness_test <= 100:
        ap.error("--brightness-test must be 30..100")
    log_traffic(args.capture)
    print(f"capture: {args.capture}")
    async with await Connection.open_serial(args.port) as connection:
        laser = device(connection, args.model)
        print("hardware_info:", await laser.hardware_info())
        print("limits:", await laser.limits())
        print("setpoint:", await laser.setpoint())
        print("control_source:", await laser.control_source())
        status = await laser.status()
        print("status:", status)
        if status["output"]:
            print("WARNING: the laser output is already ENABLED (it may be emitting). --on will switch it off at the end.")
        for name in ("op_mode", "trigger_io", "display_brightness"):  # sub-IDs 0x12/0x10/0x14: native-only or contested
            print(f"{name}:", await getattr(laser, name)())
        config_tests = args.op_mode_test or args.brightness_test is not None or args.control_source_test or args.trigger_test
        if config_tests and status["output"]:
            raise SystemExit("refusing configuration tests while the output is enabled; switch it off first")
        if args.op_mode_test:
            async def power_bit():
                return (await laser.status())["power_mode"]
            current = await laser.op_mode()
            other = "constant_current" if current == "constant_power" else "constant_power"
            await trial("op_mode", laser.op_mode, laser.set_op_mode, other, probe=power_bit)
        if args.brightness_test is not None:
            await trial("display_brightness", laser.display_brightness, laser.set_display_brightness,
                        args.brightness_test, look=3)  # look at the unit's display now
        if args.control_source_test:
            current = await laser.control_source()
            other = "software" if current != "software" else "wheel+software"
            await trial("control_source", laser.control_source, laser.set_control_source, other)
        if args.trigger_test:
            async def write_trigger(d):
                await laser.set_trigger_io(d["mode1"], d["polarity1"], d["mode2"], d["polarity2"])
            io = await laser.trigger_io()
            if io["mode1"] or io["mode2"]:
                raise SystemExit(f"trigger ports are in use ({io}); not touching them")
            flipped = {**io, "polarity1": 3 - io["polarity1"], "polarity2": 3 - io["polarity2"]}
            await trial("trigger_io", laser.trigger_io, write_trigger, flipped)
        if args.sweep is not None:
            original = await laser.setpoint()
            close = lambda a, b: abs(a - b) < 1e-3  # noqa: E731
            try:
                await laser.output(True)
                for fraction in (0.2, 0.5, 0.8):
                    await change(laser.setpoint, laser.set_setpoint, fraction, close)
                    print(f"setpoint {fraction}: READ THE DISPLAY (mA and mW) now")
                    for _ in range(args.sweep):
                        await asyncio.sleep(1)
                        print("  status:", await laser.status())
            finally:
                await laser.output(False)
                await change(laser.setpoint, laser.set_setpoint, original, close)
                print("output off; setpoint restored to", await laser.setpoint())
        if args.setpoint is not None:
            await laser.set_setpoint(args.setpoint)
            start = time.monotonic()
            while True:  # an immediate readback returned the OLD value on a real unit, so poll for the new one
                now = await laser.setpoint()
                if abs(now - args.setpoint) < 1e-3 or time.monotonic() - start > 3:
                    break
                await asyncio.sleep(0.1)
            print(f"setpoint now: {now} after {time.monotonic() - start:.2f} s")
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
