"""Single-reader asyncio transport with ordered requests and bounded event streams."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from typing import Protocol

from .protocol import FrameDecoder, Message


class ConnectionClosed(ConnectionError):
    pass


class EventOverflow(ConnectionError):
    pass


class DeviceError(RuntimeError):
    def __init__(self, message: Message):
        self.message = message
        self.command_id = message.word() if message.message_id == 0x81 else None
        self.code = message.word(2) if message.message_id == 0x81 else message.param1
        self.notes = (message.data[4:].split(b"\0", 1)[0].decode("ascii", "replace")
                      if message.message_id == 0x81 and message.data else "")
        super().__init__(f"controller 0x{message.source:02x}: code {self.code}: {self.notes}")


class Transport(Protocol):
    async def read(self, size: int) -> bytes: ...
    async def write(self, data: bytes) -> None: ...
    async def close(self) -> None: ...


class StreamTransport:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader, self.writer = reader, writer

    async def read(self, size: int) -> bytes:
        return await self.reader.read(size)

    async def write(self, data: bytes) -> None:
        self.writer.write(data)
        await self.writer.drain()

    async def close(self) -> None:
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except (ConnectionError, NotImplementedError):
            pass


@dataclass(eq=False)
class Subscription:
    queue: asyncio.Queue
    predicate: Callable[[Message], bool]

    def __aiter__(self) -> AsyncIterator[Message]:
        return self

    async def __anext__(self) -> Message:
        item = await self.queue.get()
        if isinstance(item, BaseException):
            raise item
        return item


class Connection:
    """Owns a transport. Requests serialize because APT has no transaction IDs.

    A timeout or cancellation after sending closes the connection. Reusing it
    would allow a late reply to satisfy a newer request. Closing never stops a
    moving stage; issue an explicit stop command if that is desired.
    """

    def __init__(self, transport: Transport, *, timeout: float = 3.0, max_payload: int = 65535):
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.transport, self.timeout = transport, timeout
        self._decoder = FrameDecoder(max_payload)
        self._request_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._pending: tuple[Message, Callable[[Message], bool], asyncio.Future] | None = None
        self._subscriptions: set[Subscription] = set()
        self._update_endpoints: set[tuple[int, int]] = set()
        self._failure: BaseException | None = None
        self._reader: asyncio.Task | None = None
        self._close_task: asyncio.Task | None = None

    @classmethod
    async def open_serial(cls, port: str, *, timeout: float = 3.0, baudrate: int = 115200,
                          rtscts: bool = True, exclusive: bool = True) -> Connection:
        import serial
        import serial_asyncio
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        serial_port = serial.Serial(port, baudrate=baudrate, bytesize=8, parity="N", stopbits=1,
                                    rtscts=rtscts, exclusive=exclusive, timeout=0, write_timeout=0)
        try:
            # Purge before attaching ANY receive callback, including asyncio's
            # StreamReaderProtocol, otherwise stale bytes survive in its buffer.
            await asyncio.sleep(0.05)
            serial_port.reset_input_buffer()
            serial_port.reset_output_buffer()
            await asyncio.sleep(0.05)
            loop = asyncio.get_running_loop()
            reader = asyncio.StreamReader()
            protocol = asyncio.StreamReaderProtocol(reader)
            transport, _ = await serial_asyncio.connection_for_serial(loop, lambda: protocol, serial_port)
            writer = asyncio.StreamWriter(transport, protocol, reader, loop)
            return cls(StreamTransport(reader, writer), timeout=timeout).start()
        except BaseException:
            serial_port.close()
            raise

    @classmethod
    async def open_tcp(cls, host: str, port: int, *, timeout: float = 3.0) -> Connection:
        """Raw APT byte-stream bridge, not a claim about Kinesis hub TCP framing."""
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        return cls(StreamTransport(reader, writer), timeout=timeout).start()

    @contextmanager
    def reserve_updates(self, endpoint: tuple[int, int]):
        """Claim an endpoint's update stream; two claims on one endpoint would fight over ACKs."""
        if endpoint in self._update_endpoints:
            raise RuntimeError("updates are already active for this endpoint")
        self._update_endpoints.add(endpoint)
        try:
            yield
        finally:
            self._update_endpoints.discard(endpoint)

    def start(self) -> Connection:
        self._check()
        if self._reader is None:
            self._reader = asyncio.create_task(self._read_loop(), name="yathorlib-reader")
        return self

    def _check(self) -> None:
        if self._failure is not None:
            raise ConnectionClosed(str(self._failure)) from self._failure

    async def send(self, message: Message) -> None:
        packet = message.encode()
        async with self._write_lock:
            self._check()
            try:
                await self.transport.write(packet)
            except BaseException:
                # A partial write has an unknowable boundary.
                await self.close()
                raise

    async def request(self, message: Message, response_id: int | tuple[int, ...], *,
                      predicate: Callable[[Message], bool] | None = None,
                      timeout: float | None = None) -> Message:
        delay = self.timeout if timeout is None else timeout
        if delay <= 0:
            raise ValueError("timeout must be positive")
        self.start()
        async with self._request_lock:
            self._check()
            future = asyncio.get_running_loop().create_future()
            response_ids = (response_id,) if isinstance(response_id, int) else response_id
            def matches(reply: Message) -> bool:
                return (reply.message_id in response_ids and reply.source == message.destination
                        and reply.destination == message.source and (predicate is None or predicate(reply)))
            self._pending = message, matches, future
            try:
                async with asyncio.timeout(delay):
                    await self.send(message)
                    return await future
            except (TimeoutError, asyncio.CancelledError):
                await self.close()
                raise
            finally:
                self._pending = None
                if not future.done():
                    future.cancel()
                elif not future.cancelled():
                    future.exception()  # consume failures if send itself raised

    @asynccontextmanager
    async def events(self, *, predicate: Callable[[Message], bool] | None = None,
                     max_queue: int = 256):
        if max_queue < 1:
            raise ValueError("max_queue must be positive")
        self.start()
        sub = Subscription(asyncio.Queue(max_queue), predicate or (lambda _: True))
        self._subscriptions.add(sub)
        try:
            yield sub
        finally:
            self._subscriptions.discard(sub)

    def _notify_failure(self, error: BaseException) -> None:
        if self._failure is not None:
            return
        self._failure = error
        if self._pending and not self._pending[2].done():
            self._pending[2].set_exception(error)
        for sub in self._subscriptions:
            while not sub.queue.empty():
                sub.queue.get_nowait()
            sub.queue.put_nowait(error)

    async def _read_loop(self) -> None:
        try:
            while True:
                chunk = await self.transport.read(4096)
                if not chunk:
                    self._decoder.eof()
                    raise ConnectionClosed("transport reached EOF")
                for message in self._decoder.feed(chunk):
                    if self._pending and not self._pending[2].done():
                        sent, predicate, future = self._pending
                        if (message.message_id in (0x80, 0x81) and message.source == sent.destination
                                and message.destination == sent.source):
                            error = DeviceError(message)
                            if error.command_id in (None, 0, sent.message_id):
                                future.set_exception(error)
                        elif predicate(message):
                            future.set_result(message)
                    for sub in tuple(self._subscriptions):
                        if sub.predicate(message):
                            if sub.queue.full():
                                self._subscriptions.discard(sub)
                                while not sub.queue.empty():
                                    sub.queue.get_nowait()
                                sub.queue.put_nowait(EventOverflow("event consumer fell behind"))
                            else:
                                sub.queue.put_nowait(message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._notify_failure(exc)
            # The reader cannot await a close task which in turn awaits it.
            asyncio.create_task(self.close())

    async def _close(self) -> None:
        self._notify_failure(ConnectionClosed("connection closed"))
        if self._reader:
            self._reader.cancel()
            await asyncio.gather(self._reader, return_exceptions=True)
        await self.transport.close()

    async def close(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close())
        await asyncio.shield(self._close_task)

    async def __aenter__(self) -> Connection:
        return self.start()

    async def __aexit__(self, *_):
        await self.close()
