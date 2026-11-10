# YAThorLib

Python 3.13+ asynchronous Thorlabs APT communications, implemented directly over Linux serial ports. The runtime uses neither Windows DLLs nor Kinesis, Wine, .NET or Ghidra.

**Work in progress:** this is a protocol implementation with selected typed device APIs, not yet a complete replacement for Kinesis. Hardware validation so far: two KDC101 units with an MTS100/M-Z8 stage (read, enable, home, moves, jog, stops, status updates, timeouts); no other model has been tested. Device error replies and a mid-move unplug are untested. The command catalog records documentation applicability; it does not certify a controller or firmware version. See [support coverage](https://github.com/Nolezor/YAThorLib/blob/main/docs/support.md) and [reverse engineering evidence](https://github.com/Nolezor/YAThorLib/blob/main/docs/reverse_engineering.md).

## Install

```sh
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install .
```

The controller must already appear as a Linux serial device (usually `/dev/ttyUSB*`). Use the appropriate distribution serial-device permissions and ensure another process is not using the port. `discover()` enumerates candidate ports without opening them. Its USB ID filter comes from the supplied driver INF files; a matching ID does not establish model compatibility. Devices without a working kernel serial interface need further driver work.

```python
import asyncio
from yathorlib import Connection, device, discover

async def main():
    print(discover())
    async with await Connection.open_serial('/dev/ttyUSB0') as connection:
        motor = device(connection, 'KDC101')
        print(await motor.hardware_info())
        print(await motor.position())  # integer device units

asyncio.run(main())
```

Opening uses 115200 baud, 8N1, RTS/CTS, exclusive serial access and an initial buffer purge. Model, channel, and rack bay are explicit. Opening or constructing an endpoint does not enable outputs, home a stage, or move it.

## Device APIs

`device(connection, model, channel=1, destination=0x50)` chooses a convenience class from documented capabilities. `Motor` supplies position, status, home, move_absolute, move_relative, jog and stop; `Piezo` supplies raw voltage/position and control mode. Other APIs cover selected inertial motor, NanoTrak, solenoid, strain gauge, detector, temperature, laser, liquid crystal and encoder operations. Their exact scope is in [support.md](https://github.com/Nolezor/YAThorLib/blob/main/docs/support.md).

Motion values are device units. Stage scaling is not inferred from a controller model. `UnitScale` accepts explicit, independently established conversion factors. Configure the stage, limits and homing parameters as required by its documentation before moving. In particular, a controller supporting a command does not prove it has the correct settings for the attached stage.

```python
# Explicit motion operation, only after configuring the actual stage:
await motor.move_absolute(1000, timeout=30)
# Another coroutine can interrupt a pending move:
await motor.stop()
```

Requests serialize on each connection because APT has no transaction identifiers. Events and stop writes remain concurrent. A request timeout or cancellation after sending closes the connection to prevent a late response satisfying a later request. **Closing a connection does not stop hardware motion.** A motor MOVE_STOPPED response raises `MotionInterrupted` during a waiting move.

Select the motor status layout explicitly (`await motor.status(kind='dc')` or `kind='stepper'`). A shared message identifier can have different payload layouts across controller families.

## Elliptec (ELLx) modules

Elliptec modules use a different, ASCII protocol (9600 8N1, no handshake) through an FTDI adapter. It is **not tested on hardware**; it follows the ELLx manual (issue 12) cross-checked with the vendor DLL, see [reverse engineering](https://github.com/Nolezor/YAThorLib/blob/main/docs/reverse_engineering.md#elliptec-ellx).

```python
from yathorlib import Elliptec, ElliptecBus

async with await ElliptecBus.open_serial('/dev/ttyUSB0') as bus:
    print(await bus.scan())            # IN reply of every responding address 0..F
    stage = Elliptec(bus, '0')
    info = await stage.identify()      # device-reported scale: info.pulses_per_unit, info.unit
    await stage.home()
    await stage.move_absolute(round(10 * info.pulses_per_unit))
```

Positions are device pulses. Requests serialize, and a timeout closes the bus, as for APT. Closing does not stop motion. `bus.request()` sends any other command.

## Raw messages and events

```python
from yathorlib import Message, command

print(command('MOT_REQ_POSCOUNTER'))  # ID, source page and evidence basis
reply = await connection.request(Message(0x0411, param1=1), 0x0412)

# Subscribe before starting the operation producing the events.
async with connection.events(max_queue=256) as events:
    await connection.send(Message(0x0411, param1=1))
    message = await anext(events)
```

`Device.send` and `Device.request` check model applicability; callers supply exact raw fields. `Connection` permits arbitrary `Message` packets for further investigation. Layouts not implemented as typed APIs are not automatically decoded by the catalog. Unknown or ambiguous numeric identifiers are rejected by catalog lookup.

`device.updates(acknowledgement='MOT_ACK_USTATUSUPDATE')` manages start/stop and an ACK heartbeat; choose the ACK documented for the actual controller. Overlapping update contexts for one hardware endpoint are rejected. Queue overflow raises `EventOverflow` rather than silently losing messages. Raw `events()` does not start polling or send ACKs.

`Rack(connection).bay(index, model)` addresses rack bays starting at index zero. Bay address and device channel are distinct. `Connection.open_tcp` is for a transparent APT byte-stream bridge; native Kinesis network hub discovery and negotiation are not implemented. A custom asynchronous `Transport` can also be supplied.

## Development

```sh
python -m pip install '.[dev]'
python -m pytest -q
python tools/build_catalog.py
python -m build
```

Tests include golden wire packets, fragmented reads, cancellation, error routing, unsolicited events, a TCP loopback and a Linux pseudo-terminal using the real serial transport. They do not substitute for physical-device tests. The local REA/Ghidra setup is used only to investigate supplied artifacts; see the research guide for reproduction.

## License

YAThorLib code is MIT licensed. Thorlabs software and reference materials used for the research (Kinesis DLLs, headers, drivers) are third-party, are not part of this repository (`REA Source/` is git-ignored) and are not included in the PyPI distributions. See [reverse engineering](https://github.com/Nolezor/YAThorLib/blob/main/docs/reverse_engineering.md) for how to obtain them.

Release instructions: [publishing guide](https://github.com/Nolezor/YAThorLib/blob/main/docs/publishing.md).
