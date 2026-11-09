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

No physical Thorlabs device, native Ethernet hub, or Linux USB driver binding was tested. Linux x86-64 is configured in the CI workflow but that remote workflow has not been run in this session. Results demonstrate tested software behavior, not complete per-device compatibility.
