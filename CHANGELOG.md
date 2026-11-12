# Changelog

## Unreleased

- `LaserSource` (KLS635/KLS1550): typed laser setpoint, readings, status bits, limits, control source, operating mode, trigger IO and display brightness, from the APT PDF plus native `KCube.LaserSource.dll` analysis. First run on a KLS635 (firmware 1.1.2): reads, a 5 % setpoint write and a 3.6 s output-on, replayed in `tests/test_hardware_replay_kls.py`; other setters and the KLS1550 untested. `limits()` adds `max_power_mw` (the unit is microwatts). `KLS101`, the model a KLS635 reports, is accepted. `tools/laser_check.py` for first runs (read-only by default; warns if the output is already on).
- `Elliptec`, `ElliptecBus`: untested-on-hardware support for Elliptec ELLx modules (ASCII protocol), from the ELLx manual and the vendor ELLO_DLL 1.6.0.0.

## 0.2.0 - 2026-11-10

- First hardware validation: KDC101 with an MTS100/M-Z8 stage (details in `docs/validation.md`). Still alpha.
- Vendor files (`REA Source/`) removed from git and ignored; history rewritten.
- `Connection.reserve_updates()` replaces direct access to private state from `Device.updates`.
- `stage_scale()`, `STAGES` and `UnitScale.for_dc_servo()`: KDC101/TDC001 stage scales derived from Kinesis settings by `tools/build_stages.py` (58 stages; `KMTS100E/M` is not listed by Kinesis 1.14.60).
- Real-hardware captures (KDC101 + MTS100/M-Z8: read-only, enable, home, relative and absolute moves, stop mid-move, status updates, `Device.updates()`, jog, immediate stop, timeout) replayed in `tests/test_hardware_replay.py`.
- `Device.stop_updates()` to silence a status stream left running by an earlier session.
- `tools/hw_check.py`: `--listen`, `--stop-updates`, `--jog`, `--stop-immediate`, `--timeout-test`; `tools/redact_fixture.py` (handles replies split across reads).
- `KMTS100E/M` stage alias for `MTS100/M-Z8`.
- `tools/hw_check.py` for first-contact hardware checks with raw frame capture.
- Request timeouts now say which address and message got no reply.
- Ruff and mypy added to development tooling and CI.

## 0.1.0

- Initial alpha: asyncio APT transport, command catalog, selected typed device APIs. No hardware validation.
