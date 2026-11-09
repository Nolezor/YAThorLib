"""Read identification only: python examples/read_device.py /dev/ttyUSB0 KDC101"""
import argparse
import asyncio

from yathorlib import Connection, device


async def main(port: str, model: str):
    async with await Connection.open_serial(port) as connection:
        controller = device(connection, model)
        print(await controller.hardware_info())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("port")
    parser.add_argument("model")
    args = parser.parse_args()
    asyncio.run(main(args.port, args.model))
