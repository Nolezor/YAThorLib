# Reverse engineering record

This repository uses the supplied APT protocol PDF and static REA analysis of the supplied Kinesis artifacts. No physical controller was available for validation. Recovered pseudocode is evidence about this Kinesis build, not original source or proof of compatibility with all firmware.

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
