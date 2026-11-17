"""Fixtures: an Atrea unit on modbus-connection's in-memory mock backend."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from modbus_connection.mock import MockModbusUnit

from atrea_modbus.rd5 import AtreaRD5

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    """A raw register dump captured from a real unit."""
    raw: dict[str, Any] = json.loads((FIXTURES / name).read_text())
    return raw


@pytest.fixture
def unit(mock_modbus_unit: MockModbusUnit) -> MockModbusUnit:
    """A DUPLEX RB5 with a heat pump and an integrated heat storage tank."""
    mock_modbus_unit.load_raw(load_fixture("rb5_heat_pump_izt.json"))
    return mock_modbus_unit


@pytest.fixture
async def device(unit: MockModbusUnit) -> AtreaRD5:
    """The unit, read once."""
    device = AtreaRD5(unit)
    await device.async_update()
    return device
