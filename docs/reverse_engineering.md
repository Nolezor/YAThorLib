# Reverse engineering record

This repository uses the supplied APT protocol PDF and static REA analysis of the supplied Kinesis artifacts. The research phase had no physical controller; the first hardware captures (KDC101 with an MTS100/M-Z8 stage) were added later and are described in `docs/validation.md`. Recovered pseudocode is evidence about this Kinesis build, not original source or proof of compatibility with all firmware.

## Inputs and inventory

The vendor files (Kinesis DLLs, headers, XML, drivers) are **not in this repository**. To reproduce the research, install Thorlabs Kinesis on a Windows machine and copy its install folder (normally `C:\Program Files\Thorlabs\Kinesis`) to `REA Source/Thorlabs/` at the repository root; that path is git-ignored. Only the derived evidence under `docs/research/` and `src/yathorlib/data/` is committed. The runtime and the tests never need the vendor files.

The PDF has 494 pages (issue 48). `tools/build_catalog.py` extracts named messages and applicability groups into `src/yathorlib/data/catalog.json`, retaining source pages, the input hash and conflicting observations. It does not infer binary field layouts. The current extraction contains 397 named identifiers and 45 applicability groups, with six recorded discrepancies. Body headings take precedence over incorrect table-of-contents IDs. The ambiguous KVC analog input request is excluded.

`tools/inventory_kinesis.py` inventories 189 top-level DLL/header/XML files, with SHA-256 hashes in `research/inventory.json`. REA exported symbols from 48 DLLs (36,922 symbols); 46 headers were inventoried. An exported function inventory is not a complete decompilation. Managed metadata, including PrivateInternal, was inspected separately; its metadata does not establish the wire implementation of every public API.

## Recovered implementation details

| Evidence | Finding used by the library |
| --- | --- |
| DeviceManager `0x180090e20`, `research/ftdi-init.json` | 115200 baud, eight data bits, one stop bit, RTS/CTS, reset/purge setup |
| DeviceManager `0x18006dd40`, `research/decompiled-write/` | Six-byte little-endian short header with host source 1 |
| DeviceManager `0x18006df30` | Data header length, destination data flag, prepended channel word |
| DeviceManager `0x180070060`, `research/request-submessage.json` | Header-only parameter request with sub-ID in param1, channel in param2 |
| KCube.InertialMotor `0x180026db0`, `research/decompiled-inertial/` | Logical channels 1–4 map to masks 1, 2, 4, 8; current position uses sub-ID 5 |
| LiquidCrystal `0x18001caf0`, `0x18001cb20`, `0x18001eda0`, `research/decompiled-klc-impl/` | Preset voltage/frequency requests and two independent setter writes |
| LiquidCrystal `0x18001f1e0`, `0x18001f040` | Response payload is three words: channel, preset, value |
| PositionReadoutEncoder `0x180018200`, `0x180018090`, `0x18001b030` | Position request 0x03A1, zero 0x03A0, response 0x03A2 with a signed 32-bit count and no channel prefix |
| Encoder `0x18001a5b0`; DeviceManager `0x18006dbb0` | Default channel 1; shared Request serializes destination and param1 separately |

Native-only entries and source hashes are recorded in `src/yathorlib/data/native.json`. Function addresses refer to the supplied x86-64 images. REA manifests retain evidence IDs, input hashes, engine versions and analysis limitations. Decompiled function directories and the large PDF extraction are local research outputs excluded by `.gitignore`; preserve the manifests when sharing results.

The PDF's BOWINDEX contents IDs disagree with its detailed sections. The inertial parameter request prose also disagrees with its short-packet table; the native serializer resolves the latter. These discrepancies are why a mechanically generated message list alone is insufficient for typed device support.

## Project-local Ghidra

The authorized local setup is `.tools/ghidra_12.1.4_PUBLIC`, from the official NSA release archive `ghidra_12.1.4_PUBLIC_20260921.zip`. Archive SHA-256:

```
ddac49f903da9d5bac833e5cc79395098b9c33cfd3279be5f31bd00387d2d4db
```

Download metadata is retained in `.tools/ghidra-release.json`. Java 21 is required for this setup. On this macOS ARM host, the native decompiler was built from the shipped source using `make -j6 ghidra_opt ARCH_TYPE='-arch arm64' OSDIR=mac_arm_64` in `Ghidra/Features/Decompiler/src/decompile/cpp`, then installed as `Ghidra/Features/Decompiler/os/mac_arm_64/decompile`. The launcher scripts must be executable. Other host platforms require their matching native binaries.

`tools/run_rea.sh` sets `GHIDRA_INSTALL_DIR` locally without changing global MCP settings. With REA 6.8.0 on PATH (or `REA_COMMAND` set to its executable):

```sh
tools/run_rea.sh function 'REA Source/Thorlabs/Thorlabs.MotionControl.DeviceManager.dll' 0x18006dbb0 --provider ghidra --json
```

REA's ephemeral import leaves the source DLL unchanged. Ghidra and the vendor files are not included in the Python package.

## Remaining investigation

Full Kinesis parity remains unfinished. Important gaps include model-specific stage settings and unit conversions, network hubs, joystick/TDI behavior, firmware operations, many MMI/trigger/configuration structures, liquid crystal operating-mode transitions, encoder display/calibration/status operations and all physical-device validation. Native exports were inventoried for all supplied DLLs, but native bodies were only investigated for selected transport and device paths. No claim of complete per-device support follows from the inventory.

## Elliptec (ELLx)

Evidence: `docs/ell_communications_protocol.pdf` (ELLx manual issue 12); vendor C# source in `REA Source/Elliptec/Source Code/ELLO_DLL` (assembly 1.6.0.0). REA `inspect_managed_artifact` on `Thorlabs.Elliptec.ELLO_DLL.dll` (SHA-256 `94e0ba4a931ac2b7a39d5453fa74611cb9e173813adff6a8fcc557efffa0ce4a`, evidence `ev_7b51bc6adfd4cf02c49f835f73a3f7a7aed7581439391c31110dab9337316a89`) confirmed assembly version 1.6.0.0, .NET 4.5.2. A scan of its UTF-16 string heap found every command literal used by the source (`in gs us ca i f b s c ho so go sj gj fw bw ms gp ma mr sk om cm st sz ga` and the reply tags `IN GS PO HO GJ`), so the source matches the binary at that level. No method bodies were decompiled. Nothing here was observed on a device.

The library follows the manual unless the DLL shows a better reading:

| Finding | Source |
| --- | --- |
| ASCII frames: address `0`-`F`, two-letter command, upper-case hex data; replies end CR LF | manual p.5-7, DLL `ELLDevicePort` |
| Status code is hex (`GS0A` = 10); the manual table is decimal | DLL `DeviceStatus` (`ToInt(true)`) |
| `I1`/`I2` reply is 25 characters (manual says 23) | DLL `MotorInfo` struct, manual example |
| Period = 14,740,000 / Hz; the manual's `0f1804E` "78 kHz" example is really a period of 78, while the `I1` example `00BD` is 78 kHz | arithmetic, DLL `SetPeriod` |
| Period bit 15 is set only for "hard save" in the DLL, always in the manual's examples; semantics unverified | DLL `SetPeriod`, manual p.15 |
| Scale: rotary `pulses/360`; imperial `pulses x 25.4` per inch; otherwise `pulses` per mm; paddle `(pulses-1)/travel` (the manual table gives 2048 pulses/mm in prose but 1024 in the table) | DLL `DeviceID` |
| ELL9/ELL12 sliders are moved with `ma` at index x 32 / x 19 although the manual says `ma` does not apply to sliders | DLL `ELLDevice.MoveToPosition` |
| Vendor stops a held jog with undocumented `ms`; the manual documents `st` | DLL `JogStop` |
| The DLL ends every command with BEL (`NewLine = "\a"`); the manual defines no terminator | DLL `ELLDevicePort` |
| A move completes on `PO`; `GS09` is progress, other non-zero `GS` is failure | DLL `WaitForPositions` |
| DLL group-home sends `ho` + `(int)direction` (`48`), probably a vendor bug | DLL `Home(List<char>)` |

Not implemented: group addressing (`ga`), `is`, `ah`, `rd`, current-curve download, the paddle polariser commands (`pN aN rN tN`, nibble-packed positions), ELL6 shutters beyond `fw`/`bw`. Their bytes are in the DLL source and the manual; they use `bus.request()`.

## KLS635 / KLS1550 laser source

Evidence: `docs/useful/etn039196-d03.pdf` (user guide, no wire protocol), APT PDF pp.327-356 (`LA_*` sub-messages), `Thorlabs.MotionControl.KCube.LaserSource.h`, and REA 6.8.0 + Ghidra 12.1.4 pseudocode of `Thorlabs.MotionControl.KCube.LaserSource.dll` (`docs/research/decompiled-kls/`, local only): the reply dispatcher `0x1800204a0` and the setters `0x18001fe30` (op mode), `0x180020080` (power), `0x18001ff60` (trigger IO), `0x18001faa0` (control source), `0x18001fd20` (MMI). Nothing here was observed on a device.

| Finding | Source |
| --- | --- |
| Setters write `LA_SET_PARAMS` with the sub-ID as first data word: setpoint 1, control source 5, trigger IO 0x10 (14 data bytes), op mode 0x12 (12 data bytes), MMI 0x14 (10 data bytes) | setters above |
| Op mode (0x12) is not in the PDF; first word is the mode (0 constant power, 1 constant current), four more words are kept as reported | `0x18001fe30`, `LS_GetOPMode` |
| Display brightness is sub-ID 0x14 in the DLL; the PDF says 0x0E (and 0x0B, which it marks not applicable) | `0x18001fd20`, dispatcher `case 0x14` |
| Replies decode: limits 9 = max current, max power, wavelength (words at offsets 8, 10, 12); readings 3 = current, power; status update 0x821 = current, power, status dword at 6, 8, 10; the DLL answers every 0x821 with 0x822 | dispatcher |
| Setpoint, current and power are 0..32767 = 0..100 % of full scale | PDF, header |
| Max power units are unresolved: the header says 0..6.5535 mW (0.0001 mW), the PDF example reads 5 for 5 mW, and the 8 mW rating does not fit 16 bits at 0.0001 mW. The library returns the raw word | header, PDF, datasheet |
| Display brightness range: header 30..100, PDF 20..100; the library accepts 30..100 | header, PDF |
| Status bits 0x1 output, 0x2 keyswitch, 0x4 power mode, 0x8 interlock agree with the PDF example `0x2B`; the PDF's ADC bit numbers are inconsistent, so the ext-input reading is not decoded | PDF |

Not implemented: `HW_SET_KCUBEMMILOCK`, `RESTOREFACTORYSETTINGS`, the ext-input ADC field, mW/dBm conversion, the stability trigger modes beyond passing their numbers. The user guide documents the key switch and interlock: the output cannot be enabled without both.
