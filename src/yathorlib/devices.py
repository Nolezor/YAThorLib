"""Controller endpoints sharing one connection; capabilities come from the PDF."""
from __future__ import annotations

import asyncio
import struct
from contextlib import asynccontextmanager

from .catalog import command, commands_for
from .codecs import HardwareInfo, LAYOUTS, Layout, decode_motor_status
from .connection import Connection
from .protocol import Message, ProtocolError, bay_address


class UnsupportedCommand(ValueError):
    pass


class MotionInterrupted(RuntimeError):
    """The controller reported MOVE_STOPPED before the requested move finished."""
    def __init__(self, message: Message):
        self.message = message
        super().__init__("motion stopped before completion")


class Device:
    """Explicit model and address. Does not assume a stage, home, or enable output."""

    def __init__(self, connection: Connection, model: str, *, destination: int = 0x50,
                 channel: int = 1, source: int = 1):
        Message(0, destination, source, channel)
        if channel == 0:
            raise ValueError("channel must be nonzero")
        self.connection, self.model = connection, model.upper()
        self.destination, self.channel, self.source = destination, channel, source
        self.commands = commands_for(self.model)

    def supports(self, name: str) -> bool:
        return name.removeprefix("MGMSG_").upper() in self.commands

    def packet(self, name: str, *, param1: int = 0, param2: int = 0,
               data: bytes | None = None) -> Message:
        cmd = command(name)
        if cmd.name not in self.commands:
            raise UnsupportedCommand(f"{cmd.name} is not documented for {self.model}")
        return Message(cmd.id, self.destination, self.source, param1, param2, data)

    async def send(self, name: str, **fields) -> None:
        """Raw documented command. Caller supplies its exact payload/header fields."""
        await self.connection.send(self.packet(name, **fields))

    async def request(self, name: str, response: str | tuple[str, ...], *, predicate=None, timeout=None, **fields) -> Message:
        # Some response headings are missing from applicability contents. Require
        # the outgoing command, but resolve the response from the full catalog.
        response_ids = command(response).id if isinstance(response, str) else tuple(command(n).id for n in response)
        return await self.connection.request(self.packet(name, **fields), response_ids,
                                             predicate=predicate, timeout=timeout)

    async def identify(self) -> None:
        await self.send("MOD_IDENTIFY", param1=self.channel)

    async def hardware_info(self) -> HardwareInfo:
        return HardwareInfo.decode(await self.request("HW_REQ_INFO", "HW_GET_INFO"))

    async def enable(self, enabled: bool = True) -> None:
        await self.send("MOD_SET_CHANENABLESTATE", param1=self.channel, param2=1 if enabled else 2)

    async def is_enabled(self) -> bool:
        reply = await self.request("MOD_REQ_CHANENABLESTATE", "MOD_GET_CHANENABLESTATE",
                                   param1=self.channel, predicate=lambda m: m.data is None and m.param1 == self.channel)
        if reply.param2 not in (1, 2):
            raise ProtocolError("invalid channel enable state")
        return reply.param2 == 1

    async def get_parameters(self, key: str) -> dict:
        layout = LAYOUTS[key]
        family, suffix = key.split("_", 1)
        reply = await self.request(f"{family}_REQ_{suffix}", f"{family}_GET_{suffix}",
                                   param1=self.channel, predicate=lambda m: m.word() == self.channel)
        return layout.unpack(reply.data)

    async def set_parameters(self, key: str, **values) -> None:
        family, suffix = key.split("_", 1)
        payload = LAYOUTS[key].pack(channel=self.channel, **values)
        await self.send(f"{family}_SET_{suffix}", data=payload)

    @asynccontextmanager
    async def updates(self, *, acknowledgement: str | None = None, interval: float = 0.5,
                      max_queue: int = 256):
        """Yield all endpoint messages; keep USB server-alive ACKs running.

        Select the documented ACK explicitly for the controller. Set interval
        below one second. This context must not overlap another updates context
        for the same hardware endpoint.
        """
        if not 0 < interval < 1:
            raise ValueError("acknowledgement interval must be between 0 and 1 second")
        if acknowledgement is not None:
            self.packet(acknowledgement)  # validate before starting updates
        endpoint = self.destination, self.source
        if endpoint in self.connection._update_endpoints:
            raise RuntimeError("updates are already active for this endpoint")
        self.connection._update_endpoints.add(endpoint)
        try:
            async with self._updates(acknowledgement, interval, max_queue) as events:
                yield events
        finally:
            self.connection._update_endpoints.discard(endpoint)

    @asynccontextmanager
    async def _updates(self, acknowledgement, interval, max_queue):
        async def heartbeat():
            while True:
                await self.send(acknowledgement)
                await asyncio.sleep(interval)
        async with self.connection.events(
            predicate=lambda m: m.source == self.destination and m.destination == self.source,
            max_queue=max_queue,
        ) as events:
            await self.send("HW_START_UPDATEMSGS")
            task = asyncio.create_task(heartbeat()) if acknowledgement else None
            try:
                yield events
            finally:
                if task:
                    task.cancel()
                    results = await asyncio.gather(task, return_exceptions=True)
                else:
                    results = []
                await self.send("HW_STOP_UPDATEMSGS")
                for result in results:
                    if isinstance(result, Exception):
                        raise result


class Motor(Device):
    """Motor operations in device units; no stage conversion is guessed."""

    async def position(self) -> int:
        return (await self.get_parameters("MOT_POSCOUNTER"))["position"]

    async def status(self, *, kind: str = "dc"):
        stem = "USTATUSUPDATE" if kind == "dc" else "STATUSUPDATE"
        message = await self.request(f"MOT_REQ_{stem}", f"MOT_GET_{stem}", param1=self.channel,
                                     predicate=lambda m: m.word() == self.channel)
        return decode_motor_status(message, kind=kind)[0]

    async def home(self, *, timeout: float = 120.0) -> Message:
        reply = await self.request("MOT_MOVE_HOME", ("MOT_MOVE_HOMED", "MOT_MOVE_STOPPED"), param1=self.channel,
                                  predicate=lambda m: (m.param1 == self.channel if m.data is None
                                                       else m.word() == self.channel), timeout=timeout)
        if reply.message_id == 0x466:
            raise MotionInterrupted(reply)
        return reply

    async def move_absolute(self, position: int, *, timeout: float = 120.0) -> Message:
        return await self._move("MOT_MOVE_ABSOLUTE", position, timeout)

    async def move_relative(self, distance: int, *, timeout: float = 120.0) -> Message:
        return await self._move("MOT_MOVE_RELATIVE", distance, timeout)

    async def _move(self, name: str, value: int, timeout: float) -> Message:
        reply = await self.request(name, ("MOT_MOVE_COMPLETED", "MOT_MOVE_STOPPED"),
                                   data=struct.pack("<Hi", self.channel, value),
                                   predicate=lambda m: m.word() == self.channel, timeout=timeout)
        if reply.message_id == 0x466:
            raise MotionInterrupted(reply)
        return reply

    async def jog(self, direction: int) -> None:
        if direction not in (1, 2):
            raise ValueError("direction must be 1 (forward) or 2 (reverse)")
        await self.send("MOT_MOVE_JOG", param1=self.channel, param2=direction)

    async def stop(self, *, immediate: bool = False) -> None:
        # Bypass request serialization so a pending move can be stopped.
        await self.send("MOT_MOVE_STOP", param1=self.channel, param2=1 if immediate else 2)


class Piezo(Device):
    async def voltage_raw(self) -> int:
        return (await self.get_parameters("PZ_OUTPUTVOLTS"))["voltage"]

    async def set_voltage_raw(self, voltage: int) -> None:
        await self.set_parameters("PZ_OUTPUTVOLTS", voltage=voltage)

    async def position_raw(self) -> int:
        return (await self.get_parameters("PZ_OUTPUTPOS"))["position"]

    async def set_position_raw(self, position: int) -> None:
        if not 0 <= position <= 32767:
            raise ValueError("piezo position must be in 0..32767")
        await self.set_parameters("PZ_OUTPUTPOS", position=position)

    async def set_control_mode(self, mode: int) -> None:
        if mode not in (1, 2, 3, 4):
            raise ValueError("mode must be 1..4 (open/closed loop, optionally smooth)")
        await self.send("PZ_SET_POSCONTROLMODE", param1=self.channel, param2=mode)


class ParameterDevice(Device):
    """LA, TEC, QUAD and PZMOT multiplexed parameters (sub-ID + body).

    Raw bodies are retained so unsupported parameter layouts are never guessed.
    PZMOT p. 407 contradicts its REQ tables. REA/Ghidra confirms the
    header-only sub-ID/channel encoding in the supplied KIM101 implementation.
    """
    family: str

    async def get_subparameter(self, sub_id: int, *, request_channel: int = 0) -> bytes:
        reply = await self.request(f"{self.family}_REQ_PARAMS", f"{self.family}_GET_PARAMS",
                                  param1=sub_id, param2=request_channel,
                                  predicate=lambda m: m.word() == sub_id)
        return reply.data[2:]

    async def set_subparameter(self, sub_id: int, body: bytes) -> None:
        await self.send(f"{self.family}_SET_PARAMS", data=struct.pack("<H", sub_id) + body)


class Laser(ParameterDevice):
    family = "LA"

    async def output(self, enabled: bool) -> None:
        await self.send("LA_ENABLEOUTPUT" if enabled else "LA_DISABLEOUTPUT")


class LiquidCrystal(Device):
    """KLC101 preset access, reconstructed from native Kinesis; hardware unverified."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.channel != 1:
            raise ValueError("the observed KLC101 implementation uses channel 1")

    async def preset(self, index: int) -> dict:
        if index not in (1, 2):
            raise ValueError("preset must be 1 or 2")
        values = {}
        for suffix, field in (("OUTPUTVOLTS", "voltage_mv"), ("OUTPUTFREQ", "frequency_hz")):
            reply = await self.request(f"KLC_REQ_{suffix}", f"KLC_GET_{suffix}",
                                      param1=1, param2=index,
                                      predicate=lambda m: m.word() == 1 and m.word(2) == index)
            values[field] = Layout("HHH", ("channel", "preset", "value"), 0).unpack(reply.data)["value"]
        return values

    async def set_preset(self, index: int, *, voltage_mv: int, frequency_hz: int) -> None:
        """Two independent writes, as in Kinesis; not an atomic hardware operation."""
        if index not in (1, 2):
            raise ValueError("preset must be 1 or 2")
        if not 0 <= voltage_mv <= 25000 or not 2000 <= frequency_hz <= 10000:
            raise ValueError("KLC preset requires 0..25000 mV and 2000..10000 Hz")
        voltage = struct.pack("<HHH", 1, index, voltage_mv)
        frequency = struct.pack("<HHH", 1, index, frequency_hz)
        await self.send("KLC_SET_OUTPUTVOLTS", data=voltage)
        await self.send("KLC_SET_OUTPUTFREQ", data=frequency)


class PositionReadoutEncoder(Device):
    """Native Kinesis encoder family; signed counts, hardware unverified."""

    async def position(self) -> int:
        reply = await self.request("ENC_REQ_POSITION", "ENC_GET_POSITION", param1=self.channel)
        # Unlike motor GET_POSCOUNTER, there is no channel word in this payload.
        return Layout("i", ("position",), 0).unpack(reply.data)["position"]

    async def zero(self) -> None:
        await self.send("ENC_SET_ZERO", param1=self.channel)


class TemperatureController(ParameterDevice):
    family = "TEC"

    async def setpoint_raw(self) -> int:
        body = await self.get_subparameter(1)
        return Layout("h", ("setpoint",), 392).unpack(body)["setpoint"]

    async def set_setpoint_raw(self, value: int) -> None:
        await self.set_subparameter(1, struct.pack("<h", value))

    async def readings(self) -> dict:
        return Layout("Hhh", ("current_ma", "actual_raw", "setpoint_raw"), 393).unpack(
            await self.get_subparameter(3))


class QuadDetector(ParameterDevice):
    family = "QUAD"

    async def readings(self) -> dict:
        message = await self.request("QUAD_REQ_STATUSUPDATE", "QUAD_GET_STATUSUPDATE")
        return Layout("hhHhhI", ("x_difference", "y_difference", "sum", "x_position", "y_position", "status"), 386).unpack(message.data)


class InertialMotor(ParameterDevice):
    family = "PZMOT"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.channel not in (1, 2, 4, 8):
            raise ValueError("inertial channel is a bit mask: 1, 2, 4 or 8")

    async def move_absolute(self, position: int, *, timeout: float = 120.0) -> Message:
        return await self.request("PZMOT_MOVE_ABSOLUTE", "PZMOT_MOVE_COMPLETED",
                                  data=struct.pack("<Hi", self.channel, position),
                                  predicate=lambda m: m.word() == self.channel, timeout=timeout)

    async def stop(self, *, immediate: bool = False) -> None:
        await self.send("MOT_MOVE_STOP", param1=self.channel, param2=1 if immediate else 2)

    async def position(self) -> int:
        # KIM RequestCurrentPosition at 0x180026db0 -> shared serializer
        # at 0x180070060: C1 08 05 <channel-mask> <dest> 01.
        reply = await self.request("PZMOT_REQ_PARAMS", "PZMOT_GET_PARAMS",
                                  param1=5, param2=self.channel,
                                  predicate=lambda m: m.word() == 5 and m.word(2) == self.channel)
        fields = Layout("HHii", ("sub_id", "channel", "position", "encoder"), 408).unpack(reply.data)
        return fields["position"]


class PiezoStage(ParameterDevice):
    """PDXC2/PDXC3 parameter envelope; model-specific bodies use raw access."""
    family = "PZMOT"


class Solenoid(Device):
    async def set_state(self, active: bool) -> None:
        await self.send("MOT_SET_SOL_STATE", param1=self.channel, param2=1 if active else 2)

    async def state(self) -> bool:
        reply = await self.request("MOT_REQ_SOL_STATE", "MOT_GET_SOL_STATE", param1=self.channel,
                                  predicate=lambda m: m.data is None and m.param1 == self.channel)
        if reply.param2 not in (1, 2):
            raise ProtocolError("invalid solenoid state")
        return reply.param2 == 1

    async def set_mode(self, mode: int) -> None:
        if mode not in (1, 2, 3, 4):
            raise ValueError("mode must be 1 manual, 2 single, 3 auto, or 4 triggered")
        await self.send("MOT_SET_SOL_OPERATINGMODE", param1=self.channel, param2=mode)

    async def set_cycle(self, on_ms: int, off_ms: int, cycles: int) -> None:
        if not (100 <= on_ms <= 10_000_000 and 100 <= off_ms <= 10_000_000 and 0 <= cycles <= 1_000_000):
            raise ValueError("cycle parameters exceed documented limits")
        await self.set_parameters("MOT_SOL_CYCLEPARAMS", on_ms=on_ms, off_ms=off_ms, cycles=cycles)


class StrainGauge(Device):
    async def readings(self) -> dict:
        """Raw reading; physical units depend on display mode and calibration."""
        return await self.get_parameters("PZ_TSG_READING")


class NanoTrak(Device):
    async def set_tracking_mode(self, mode: int) -> None:
        if mode not in (2, 3, 4, 5):
            raise ValueError("mode must be 2 latch, 3 track, 4 horizontal, or 5 vertical")
        await self.send("PZ_SET_NTMODE", param1=mode)

    async def readings(self) -> dict:
        reply = await self.request("PZ_REQ_NTTIAREADING", "PZ_GET_NTTIAREADING")
        return Layout("fHHH", ("absolute", "relative", "range", "under_over"), 301).unpack(reply.data)

    async def set_tracking_threshold(self, amperes: float) -> None:
        if not 1e-9 <= amperes <= 1e-3:
            raise ValueError("tracking threshold must be in 1e-9..1e-3 A")
        await self.send("PZ_SET_NTTRACKTHRESHOLD", data=struct.pack("<f", amperes))

    async def status_bits(self) -> int:
        reply = await self.request("PZ_REQ_NTSTATUSBITS", "PZ_GET_NTSTATUSBITS")
        return Layout("I", ("status",), 305).unpack(reply.data)["status"]

    async def set_circle_home(self, x: int, y: int) -> None:
        await self.send("PZ_SET_NTCIRCHOMEPOS", data=struct.pack("<HH", x, y))


class Rack:
    def __init__(self, connection: Connection, *, destination: int = 0x11):
        self.connection, self.destination = connection, destination

    async def occupied(self, index: int) -> bool:
        bay_address(index)
        reply = await self.connection.request(Message(0x60, self.destination, param1=index), 0x61,
                                               predicate=lambda m: m.data is None and m.param1 == index)
        if reply.param2 not in (1, 2):
            raise ProtocolError("invalid rack bay state")
        return reply.param2 == 1

    def bay(self, index: int, model: str, *, channel: int = 1) -> Device:
        return device(self.connection, model, destination=bay_address(index), channel=channel)


def device(connection: Connection, model: str, **addressing) -> Device:
    """Choose convenience API by documented command set, retaining raw access."""
    commands = commands_for(model)
    cls = Device
    if model.upper() == "KLC101":
        cls = LiquidCrystal
    elif model.upper() == "POSITIONREADOUTENCODER":
        cls = PositionReadoutEncoder
    elif model.upper() in ("PDXC2", "PDXC3"):
        cls = PiezoStage
    elif "PZMOT_SET_PARAMS" in commands:
        cls = InertialMotor
    elif "TEC_SET_PARAMS" in commands:
        cls = TemperatureController
    elif "QUAD_SET_PARAMS" in commands:
        cls = QuadDetector
    elif "LA_SET_PARAMS" in commands:
        cls = Laser
    elif "PZ_REQ_NTTIAREADING" in commands:
        cls = NanoTrak
    elif "MOT_SET_SOL_STATE" in commands:
        cls = Solenoid
    elif "PZ_REQ_TSG_READING" in commands and "PZ_SET_OUTPUTVOLTS" not in commands:
        cls = StrainGauge
    elif "PZ_SET_OUTPUTVOLTS" in commands:
        cls = Piezo
    elif "MOT_MOVE_ABSOLUTE" in commands or "MOT_MOVE_JOG" in commands:
        cls = Motor
    return cls(connection, model, **addressing)
