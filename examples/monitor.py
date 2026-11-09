"""Monitor raw APT events: python examples/monitor.py /dev/ttyUSB0 KDC101 MOT_ACK_USTATUSUPDATE"""
import argparse
import asyncio

from yathorlib import Connection, device


async def main(port, model, acknowledgement):
    async with await Connection.open_serial(port) as connection:
        controller = device(connection, model)
        async with controller.updates(acknowledgement=acknowledgement) as messages:
            async for message in messages:
                print(message)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("port")
    parser.add_argument("model")
    parser.add_argument("acknowledgement")
    args = parser.parse_args()
    asyncio.run(main(args.port, args.model, args.acknowledgement))
