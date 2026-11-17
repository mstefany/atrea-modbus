from __future__ import annotations

import pytest
from modbus_connection import IllegalDataAddressError, ModbusTimeoutError
from modbus_connection.mock import MockModbusUnit

from atrea_modbus.rd5 import (
    AtreaRD5,
    ControlSource,
    Cooling,
    FanRegulation,
    IndoorTemperatureSource,
    OperatingMode,
    PrimaryHeating,
    R5Power,
    Season,
    SeasonMode,
)


async def test_decodes_a_captured_rb5(device: AtreaRD5) -> None:
    assert device.is_r5
    assert device.model == "DUPLEX R_5"
    assert device.serial_number == "0A1234567"
    assert device.firmware_version == "2.03.41"
    config = device.configuration
    assert config.fan_regulation is FanRegulation.R5_CONSTANT_FLOW
    assert config.primary_heating is PrimaryHeating.WATER_ANALOG
    assert config.cooling is Cooling.DIRECT
    assert config.indoor_temperature_source is IndoorTemperatureSource.BMS
    assert config.circulation_damper is True
    assert config.automatic_ventilation_interval == 15
    assert config.supply_fan_correction == 0
    assert device.r5_flows is not None
    assert device.r5_flows.circulation_norm == 420
    assert device.r5_flows.ventilation_max == 180

    control = device.control
    assert control.mode is OperatingMode.CIRCULATION_WITH_VENTILATION
    assert control.requested_mode is OperatingMode.CIRCULATION_WITH_VENTILATION
    assert control.requested_temperature == 22.5
    assert control.power == 35
    assert device.r5_power is R5Power.NORM_MAX
    assert control.temperature == 22.5
    assert control.mode_source is ControlSource.MANUAL
    assert control.follows_schedule is False

    sensors = device.sensors
    assert sensors.outdoor_air == 6.9
    assert sensors.supply_air == 22.0
    assert sensors.indoor_air == 22.5
    assert sensors.ta2 is None  # no sensor connected
    assert sensors.season is Season.HEATING
    assert sensors.outdoor_air_average == 4.1
    assert sensors.supply_flow == 422
    assert sensors.outdoor_flow == 176

    assert device.outputs.m1 == 6.848
    assert device.outputs.sv is True
    assert device.settings.season_mode is SeasonMode.HEATING
    assert device.settings.season_temperature == 11.0


async def test_heat_storage_follows_the_fitted_board(device: AtreaRD5) -> None:
    assert device.rg_inputs is None
    assert device.tz_inputs is not None
    assert device.storage_inputs is device.tz_inputs
    assert device.tz_inputs.t1 == 47.1
    assert device.tz_inputs.t2 == 38.1
    assert device.tz_inputs.t3 is None
    assert device.heat_storage is not None
    assert device.heat_storage.target_top == 48.0
    assert device.heat_storage.target_middle == 20.0
    assert device.heat_storage.electric_heater_2 is True


async def test_unit_without_boards_has_no_heat_storage(unit: MockModbusUnit) -> None:
    unit.discrete[10212] = False
    device = AtreaRD5(unit)
    report = await device.async_update()
    assert device.tz_inputs is None
    assert device.heat_storage is None
    assert device.storage_inputs is None
    assert report.complete


async def test_alarms(device: AtreaRD5, unit: MockModbusUnit) -> None:
    assert device.alarms.active == {"filter_change_due"}
    assert device.alarms.faults == set()
    unit.discrete[11117] = True
    await device.async_update()
    assert device.alarms.faults == {"recuperator_frozen"}


async def test_available_modes(device: AtreaRD5, unit: MockModbusUnit) -> None:
    assert OperatingMode.CIRCULATION in device.available_modes
    assert OperatingMode.NIGHT_PRECOOLING not in device.available_modes
    unit.input[11401] = 1
    await device.async_update()
    assert OperatingMode.NIGHT_PRECOOLING in device.available_modes


async def test_poll_is_a_handful_of_reads(unit: MockModbusUnit) -> None:
    device = AtreaRD5(unit)
    await device.async_update()
    setup_and_poll = len(unit.read_events)
    unit.read_events.clear()
    await device.async_update()
    assert len(unit.read_events) < setup_and_poll
    assert len(unit.read_events) <= 12
    assert all(event.count <= 125 for event in unit.read_events)


async def test_one_failing_sub_system_does_not_fail_the_poll(
    device: AtreaRD5, unit: MockModbusUnit
) -> None:
    unit.fail_read(11100, IllegalDataAddressError(), register_type="discrete")
    report = await device.async_update()
    assert set(report.failed) == {"alarms"}
    assert "control" in report.updated


async def test_silent_unit_raises(unit: MockModbusUnit) -> None:
    unit.fail_requests(ModbusTimeoutError())
    with pytest.raises(ModbusTimeoutError):
        await AtreaRD5(unit).async_update()


async def test_raw_dump_has_the_registers_as_read(device: AtreaRD5) -> None:
    raw = await device.async_read_raw()
    assert raw["holding"][10705] == 3
    assert raw["input"][10211] == 69
    assert raw["discrete"][11183] is True


async def test_unit_without_identity_registers_still_sets_up(
    unit: MockModbusUnit,
) -> None:
    unit.fail_read(12300, IllegalDataAddressError())
    unit.fail_read(20, IllegalDataAddressError(), register_type="input")
    device = AtreaRD5(unit)
    report = await device.async_update()
    assert report.complete
    assert device.serial_number is None
    assert device.firmware_version is None


async def test_raw_dump_leaves_the_serial_number_out(device: AtreaRD5) -> None:
    raw = await device.async_read_raw()
    assert 12300 not in raw["holding"]
    assert raw["input"][20] == 2


async def test_unit_that_is_not_r5_has_no_level_flows(unit: MockModbusUnit) -> None:
    unit.holding[10510] = 1
    device = AtreaRD5(unit)
    await device.async_update()
    assert not device.is_r5
    assert device.r5_flows is None
    assert device.r5_power is None
