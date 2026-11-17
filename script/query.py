#!/usr/bin/env python3

"""Query an Atrea DUPLEX unit with RD5 control and print every value. Read-only."""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys

from modbus_connection import ModbusError
from modbus_connection.cli_helper import (
    CountingUnit,
    add_connection_args,
    connect_from_args,
    print_component,
)

from atrea_modbus.rd5 import ALL, AtreaRD5

EXAMPLES = """examples:
  uv run script/query.py 192.168.1.50
  # also dump every register read, for an issue report or a test fixture
  uv run script/query.py 192.168.1.50 --raw
"""


async def main() -> int:
    """Read the unit once and print it."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # The RD5 control speaks native Modbus TCP only.
    add_connection_args(parser, connections=(("tcp", None),))
    parser.add_argument("--unit", type=int, default=1, help="Modbus unit id")
    parser.add_argument(
        "--raw", action="store_true", help="also dump every register read as JSON"
    )
    args = parser.parse_args()
    # Units such as °C and m³ do not fit the default encoding of every console.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")

    try:
        conn = await connect_from_args(args)
    except ModbusError as err:
        print(f"Could not connect: {err}")
        return 1

    counting = CountingUnit(conn.for_unit(args.unit))
    device = AtreaRD5(counting)
    raw = None
    try:
        report = await device.async_update()
        reads = counting.reads
        if args.raw:
            raw = await device.async_read_raw()
    except ModbusError as err:
        print(f"Could not read the unit: {err or type(err).__name__}")
        return 1
    finally:
        await conn.close()

    print(f"{device.model}, firmware {device.firmware_version}")
    modes = ", ".join(mode.name.lower() for mode in device.available_modes)
    print(f"Available modes: {modes}")
    for name in ALL:
        component = getattr(device, name)
        if component is not None:
            print()
            print_component(component, title=name)
    for name, failure in report.failed.items():
        print(f"\n{name} failed: {failure or type(failure).__name__}")
    print(f"\n{reads} Modbus reads for setup and one poll")
    if raw is not None:
        print(json.dumps(raw, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
