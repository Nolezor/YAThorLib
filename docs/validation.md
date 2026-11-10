# Validation record

Validated on 2026-11-09 in Linux ARM64 Docker containers on the development host:

| Environment | Result |
| --- | --- |
| Python 3.13, `python:3.13-slim` | 63 tests passed |
| Python 3.14, `python:3.14-slim` | 63 tests passed |
| Python 3.13 Linux wheel build/install/import | Passed; package data loaded, 406 command names |
| Final portable wheel build | `dist/yathorlib-0.1.0-py3-none-any.whl` |

Both Linux runs included the real pyserial-asyncio transport over a pseudo-terminal, TCP loopback, packet fixtures, fragmented frames, request serialization, cancellation, event overflow, device errors, native-derived KLC/encoder packets, interrupted motion/homing, and update ownership.

The final wheel SHA-256 is `070f14dc31f075f29d519e1f2ade9d429f7dc17d4338baa2ae5a5dbe545c23e7`. The wheel contains Python modules, protocol JSON and the typing marker; no vendor DLL, Ghidra or PDF is required at runtime. The wheel installation/import check preceded the final two lifecycle regression tests; the final source passed all 63 tests on both versions and the final wheel rebuilt successfully.

## Hardware record

| Date | Controller | Stage | Firmware | Exercised | Not exercised |
| --- | --- | --- | --- | --- | --- |
| 2026-11-10 | KDC101 (serial 27xxxxxx), Linux serial | KMTS100E/M = MTS100/M-Z8 | 2.2.11 | `hardware_info`, `is_enabled`, `position`, `status(kind="dc")`, `enable`, `home` (about 10 s, ended at position -2), `move_relative(34555)` (completed in about 1.7 s, moved 34553 counts), `move_absolute(69110)` (settled at 69108), controlled `stop()` mid-move (MOVE_STOPPED about 0.8 s after the stop, raised `MotionInterrupted`), raw `HW_START_UPDATEMSGS` status stream with the ACK heartbeat (about 10 updates/s; ACK every 0.5 s), one jog step (`jog(1)`: -17276 counts, about 0.5 mm, the stored step size), immediate stop (`MOVE_STOPPED` about 0.15 s after the request, against about 0.8 s for the controlled stop), a 2 s passive listen on the first unit (no unsolicited traffic), `Device.updates()` (start, ACK every 0.5 s, stop; 28 updates over 3 s, replayed with a shortened interval), a 2 s passive listen on the second unit (also quiet, including after a power cycle, when its counter was back to 0 and it was not homed), and a request to a non-existent bay (no reply, so the request times out and the connection closes); frames in `tests/fixtures/hardware/KDC101/`, replayed by `tests/test_hardware_replay.py` | device error replies, unplug mid-move, jog in the other direction, a move rejected for being out of travel |

Scale: the owner measured the carriage travel physically on 2026-11-10 and confirmed 34555 counts per mm for this stage (figures and method not recorded). The status-update capture came from a second KDC101 unit (also firmware 2.2.11), already homed; its serial, like the first unit's, is redacted in the fixtures. Jog direction 1 moved the stage towards lower counts on the first unit, so do not assume "forward" means increasing position; the mapping depends on the stage and its stored direction sense. In that capture the controller was already streaming status updates before the library asked for anything. A later 2 s passive listen on the same unit found it quiet, and that capture ended with `HW_STOP_UPDATEMSGS`, so the stream was a leftover from an earlier interrupted session, not normal behaviour. The first capture was taken before homing: position -3402019 counts (about -98.45 mm at 34554.96 counts/mm) with the forward hard limit flag set. This is a power-on counter, not a calibrated position.

No other physical device, native Ethernet hub, or Linux USB driver binding was tested. Linux x86-64 is configured in the CI workflow but that remote workflow has not been run in this session. Results demonstrate tested software behavior, not complete per-device compatibility.
