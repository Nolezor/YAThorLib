"""Elliptec ELLx ASCII protocol: ELLx manual issue 12 plus Thorlabs.Elliptec.ELLO_DLL 1.6.0.0.

Frames are `<address><2-letter command><upper-case hex data>`, replies end in CR LF. Not APT.
Positions are device pulses; `ElliptecInfo.pulses_per_unit` gives the device-reported scale.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .connection import ConnectionClosed, StreamTransport, Transport

ADDRESSES = "0123456789ABCDEF"
STATUS = {0: "OK", 1: "communication time out", 2: "mechanical time out", 3: "command error or not supported",
          4: "value out of range", 5: "module isolated", 6: "module out of isolation", 7: "initializing error",
          8: "thermal error", 9: "busy", 10: "sensor error", 11: "motor error", 12: "out of range",
          13: "over current", 14: "general error"}  # 14 is only in the vendor DLL; the manual reserves it
ROTARY = {4, 8, 14, 16, 18, 21, 22}  # device types measured in degrees (DLL DeviceID)
TWO_MOTOR = {4, 7, 8, 9, 10, 12, 14, 15, 16, 17, 18, 20, 21, 22}
SLIDER_STEP = {9: 32, 12: 19}  # ELL9/ELL12 pulses per slider position (DLL ELLDevice.MoveToPosition)


class ElliptecError(RuntimeError):
    def __init__(self, code: int, line: str = ""):
        self.code, self.line = code, line
        super().__init__(f"device status {code}: {STATUS.get(code, 'reserved')}")


def _signed(text: str) -> int:
    value = int(text, 16)
    return value - (1 << len(text) * 4) if value >> (len(text) * 4 - 1) else value


def _hex(value: int, digits: int) -> str:
    return f"{value & (1 << digits * 4) - 1:0{digits}X}"


def _address(address: str) -> str:
    address = address.upper()
    if len(address) != 1 or address not in ADDRESSES:
        raise ValueError("address must be one hex digit 0..F")
    return address


@dataclass(frozen=True, slots=True)
class ElliptecInfo:
    address: str
    device_type: int
    serial: str
    year: int
    firmware: float
    hardware: int
    imperial: bool
    travel: int  # mm or degrees; micrometres for the ELL15 iris
    pulses: int  # per mm/revolution, or per position for sliders (device-reported)

    @classmethod
    def parse(cls, line: str) -> ElliptecInfo:
        if len(line) != 33 or line[1:3] != "IN":
            raise ValueError(f"not an IN reply: {line!r}")
        hardware = int(line[19:21], 16)
        return cls(line[0], int(line[3:5], 16), line[5:13], int(line[13:17]), int(line[17:19]) / 10,
                   hardware & 0x7F, hardware >= 0x80, int(line[21:25], 16), int(line[25:33], 16))

    @property
    def motors(self) -> int:
        """Motor count as inferred by the vendor DLL's DeviceID."""
        if self.device_type == 3:
            return 3
        if self.device_type == 6:
            return 2 if self.hardware == 2 else 1
        return 2 if self.device_type in TWO_MOTOR else 1

    @property
    def unit(self) -> str:
        return "deg" if self.device_type == 3 or self.device_type in ROTARY else "in" if self.imperial else "mm"

    @property
    def pulses_per_unit(self) -> float:
        if self.device_type == 3:
            return (self.pulses - 1) / self.travel
        if self.device_type in ROTARY:
            return self.pulses / 360
        return self.pulses * 25.4 if self.imperial else float(self.pulses)


@dataclass(frozen=True, slots=True)
class MotorInfo:
    loop: bool
    running: bool
    current: float  # amperes
    ramp_up: int  # 0xFFFF: undefined
    ramp_down: int
    forward_hz: float | None
    backward_hz: float | None

    @classmethod
    def parse(cls, line: str) -> MotorInfo:
        if len(line) != 25 or line[1] != "I":
            raise ValueError(f"not an I1/I2 reply: {line!r}")
        def hz(text: str) -> float | None:
            return 14_740_000 / int(text, 16) if int(text, 16) else None

        return cls(line[3] == "1", line[4] == "1", int(line[5:9], 16) / 1866, int(line[9:13], 16),
                   int(line[13:17], 16), hz(line[17:21]), hz(line[21:25]))


class ElliptecBus:
    """Multidrop ASCII bus. Requests serialize; a timeout closes the connection so a late reply cannot be misread."""

    def __init__(self, transport: Transport, *, timeout: float = 3.0, terminator: bytes = b""):
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.transport, self.timeout, self.terminator = transport, timeout, terminator
        self._buffer = bytearray()
        self._lock = asyncio.Lock()
        self._closed = False

    @classmethod
    async def open_serial(cls, port: str, *, timeout: float = 3.0, terminator: bytes = b"") -> ElliptecBus:
        import serial
        import serial_asyncio
        # 9600 8N1, no handshake (manual p.5). The vendor DLL also appends BEL after each command; the
        # manual defines no terminator, so none is sent unless `terminator` asks for one.
        serial_port = serial.Serial(port, baudrate=9600, bytesize=8, parity="N", stopbits=1, rtscts=False,
                                    exclusive=True, timeout=0, write_timeout=0)
        try:
            await asyncio.sleep(0.05)
            serial_port.reset_input_buffer()
            serial_port.reset_output_buffer()
            loop = asyncio.get_running_loop()
            reader = asyncio.StreamReader()
            protocol = asyncio.StreamReaderProtocol(reader)
            transport, _ = await serial_asyncio.connection_for_serial(loop, lambda: protocol, serial_port)
            writer = asyncio.StreamWriter(transport, protocol, reader, loop)
            return cls(StreamTransport(reader, writer), timeout=timeout, terminator=terminator)
        except BaseException:
            serial_port.close()
            raise

    async def _line(self) -> str:
        while (end := self._buffer.find(b"\n")) < 0:
            chunk = await self.transport.read(256)
            if not chunk:
                raise ConnectionClosed("transport reached EOF")
            self._buffer.extend(chunk)
        line = bytes(self._buffer[:end])
        del self._buffer[:end + 1]
        return line.decode("ascii", "replace").strip()

    async def request(self, address: str, command: str, data: str = "", expect: str = "GS", *,
                      reply_address: str | None = None, timeout: float | None = None,
                      raise_status: bool = True, _keep_open: bool = False) -> str:
        """Send one command and return the first `expect` reply line.

        GS busy (9) keeps waiting; any other GS error raises ElliptecError. For `expect="GS"` a code 0
        completes the request; for other replies (PO, HO, ...) a GS 0 is ignored and the data reply awaited.
        """
        address, reply = _address(address), _address(reply_address or address)
        if self._closed:
            raise ConnectionClosed("connection closed")
        delay = self.timeout if timeout is None else timeout
        async with self._lock:
            self._buffer.clear()  # the vendor DLL also discards queued replies before every command
            try:
                async with asyncio.timeout(delay):
                    await self.transport.write(f"{address}{command}{data}".encode("ascii") + self.terminator)
                    while True:
                        line = await self._line()
                        if len(line) < 3 or line[0] != reply:
                            continue  # other device, button message or noise
                        tag = line[1:3]
                        if tag == "GS":
                            code = int(line[3:5], 16)  # hex: the manual lists 10..14 in decimal
                            if expect == "GS" and not raise_status:
                                return line
                            if code not in (0, 9):
                                raise ElliptecError(code, line)
                            if code == 0 and expect == "GS":
                                return line
                        elif tag == expect:
                            return line
            except TimeoutError as exc:
                if not _keep_open:
                    await self.close()
                raise TimeoutError(f"no {expect} reply from address {reply} to {command!r} within {delay:g} s"
                                   + ("" if _keep_open else "; connection closed. Check the port, power and address")) from exc
            except (ValueError, ConnectionClosed, asyncio.CancelledError):
                await self.close()
                raise

    async def scan(self, first: str = "0", last: str = "F", *, timeout: float = 1.0) -> list[ElliptecInfo]:
        """Ask every address in range for `in`; silent addresses are skipped (vendor timeout 1 s)."""
        found = []
        for address in ADDRESSES[ADDRESSES.index(_address(first)):ADDRESSES.index(_address(last)) + 1]:
            try:
                found.append(ElliptecInfo.parse(await self.request(address, "in", expect="IN", timeout=timeout,
                                                                   _keep_open=True)))
            except TimeoutError:
                pass
        return found

    async def close(self) -> None:
        self._closed = True
        await self.transport.close()

    async def __aenter__(self) -> ElliptecBus:
        return self

    async def __aexit__(self, *_):
        await self.close()


class Elliptec:
    """One ELLx module. Closing the bus does not stop a moving stage; call `stop()` first if needed."""

    MOVE_TIMEOUT = 30.0
    LONG_TIMEOUT = 600.0  # optimize/clean run for minutes

    def __init__(self, bus: ElliptecBus, address: str = "0"):
        self.bus, self.address = bus, _address(address)
        self.info: ElliptecInfo | None = None

    async def identify(self) -> ElliptecInfo:
        self.info = ElliptecInfo.parse(await self.bus.request(self.address, "in", expect="IN"))
        return self.info

    async def status(self) -> int:
        """Current status code; reading clears a latched error. Busy (9) is returned, not raised."""
        return int((await self.bus.request(self.address, "gs", raise_status=False))[3:5], 16)

    async def _position(self, command: str, data: str = "", tag: str = "PO", timeout: float | None = None) -> int:
        return _signed((await self.bus.request(self.address, command, data, tag, timeout=timeout or self.MOVE_TIMEOUT))[3:11])

    async def _set(self, command: str, data: str = "", timeout: float | None = None) -> None:
        await self.bus.request(self.address, command, data, timeout=timeout)

    async def position(self) -> int:
        return await self._position("gp")

    async def home(self, clockwise: bool = True) -> int:
        """Home; direction matters for rotary stages only. Not supported by multi-position sliders."""
        return await self._position("ho", "0" if clockwise else "1")

    async def move_absolute(self, pulses: int, *, timeout: float | None = None) -> int:
        return await self._position("ma", _hex(pulses, 8), timeout=timeout)

    async def move_relative(self, pulses: int, *, timeout: float | None = None) -> int:
        return await self._position("mr", _hex(pulses, 8), timeout=timeout)

    async def jog_forward(self) -> int:
        return await self._position("fw")

    async def jog_backward(self) -> int:
        return await self._position("bw")

    async def select_position(self, index: int) -> int:
        """ELL9/ELL12 slider position index, as the vendor DLL does: `ma` with index x 32 (ELL9) or x 19 (ELL12)."""
        info = self.info or await self.identify()
        if info.device_type not in SLIDER_STEP:
            raise ValueError("select_position is only evidenced for ELL9 and ELL12 sliders")
        return await self.move_absolute(index * SLIDER_STEP[info.device_type])

    async def stop(self) -> int:
        """`st`: ends continuous jog (ELL14) or optimize/clean. Returns the first status code (9 or 0).

        The vendor app instead sends the undocumented `ms` to stop a held jog; use `bus.request` for that.
        """
        return int((await self.bus.request(self.address, "st", raise_status=False))[3:5], 16)

    async def home_offset(self) -> int:
        return await self._position("go", tag="HO")

    async def set_home_offset(self, pulses: int) -> None:
        await self._set("so", _hex(pulses, 8))

    async def jog_step(self) -> int:
        return await self._position("gj", tag="GJ")

    async def set_jog_step(self, pulses: int) -> None:
        """Zero makes ELL14 jogs continuous until `stop()`."""
        await self._set("sj", _hex(pulses, 8))

    async def velocity(self) -> int:
        """Percent of maximum."""
        return int((await self.bus.request(self.address, "gv", expect="GV"))[3:5], 16)

    async def set_velocity(self, percent: int) -> None:
        if not 0 <= percent <= 100:
            raise ValueError("percent must be 0..100")
        await self._set("sv", _hex(percent, 2))

    async def zero_offset(self) -> int:
        """ELL22 only (`gz`)."""
        return await self._position("gz", tag="ZO")

    async def set_zero(self) -> None:
        """ELL22 only: make the current position the logical zero."""
        await self._set("sz")

    async def motor_info(self, motor: int = 1) -> MotorInfo:
        if motor not in (1, 2):
            raise ValueError("motor must be 1 or 2")
        return MotorInfo.parse(await self.bus.request(self.address, f"i{motor}", expect=f"I{motor}"))

    async def set_period(self, motor: int, forward: bool, frequency_hz: float | None, *, persist: bool = False) -> None:
        """Set a motor drive frequency, or restore the factory value with None. Not for ELL16/21/22.

        `persist` sets period bit 15, which the manual's examples always set and the vendor app sets for
        "hard save"; without it the effect is unspecified. Follow with `save()`.
        """
        if motor not in (1, 2):
            raise ValueError("motor must be 1 or 2")
        period = 0xFFF if frequency_hz is None else round(14_740_000 / frequency_hz)
        if not 0 < period <= 0x7FFF:
            raise ValueError("frequency out of range")
        await self._set(("f" if forward else "b") + str(motor), _hex(period | (0x8000 if persist or frequency_hz is None else 0), 4))

    async def search_frequency(self, motor: int = 1) -> None:
        await self._set(f"s{motor}", timeout=self.MOVE_TIMEOUT)

    async def scan_current(self, motor: int = 1) -> None:
        await self._set(f"c{motor}", timeout=self.MOVE_TIMEOUT)

    async def skip_frequency_search(self) -> None:
        await self._set("sk")

    async def optimize(self) -> None:
        await self._set("om", timeout=self.LONG_TIMEOUT)

    async def clean(self) -> None:
        await self._set("cm", timeout=self.LONG_TIMEOUT)

    async def save(self) -> None:
        """`us`: store motor and user parameters."""
        await self._set("us")

    async def set_address(self, new: str) -> None:
        new = _address(new)
        await self.bus.request(self.address, "ca", new, reply_address=new)
        self.address = new
