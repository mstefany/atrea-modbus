from __future__ import annotations

import pytest
from modbus_connection.mock import MockModbusUnit, WriteEvent

from atrea_modbus.rd5 import (
    AtreaRD5,
    ControlSource,
    OperatingMode,
    R5Power,
    SeasonMode,
    r5_power_for_mode,
)

Writes = list[tuple[str, int, list[int] | list[bool]]]


@pytest.fixture
def writes(unit: MockModbusUnit) -> Writes:
    """Every write the unit received, and a unit that applies manual values."""
    log: Writes = []

    def record(event: WriteEvent) -> None:
        log.append((event.register_type, event.address, list(event.values)))
        # The unit copies a value set by hand into the value in effect.
        if event.register_type == "holding" and 10708 <= event.address <= 10711:
            unit.holding[event.address - 4] = int(event.values[0])
            unit.holding[event.address + 6] = int(event.values[0])

    unit.on_write(record)
    return log


async def test_manual_mode_writes_the_request_only(
    device: AtreaRD5, writes: Writes
) -> None:
    await device.control.async_set_mode(OperatingMode.VENTILATION)
    assert writes == [("holding", 10709, [2])]
    assert device.control.mode is OperatingMode.VENTILATION


async def test_weekly_program_needs_the_temporary_flag(
    unit: MockModbusUnit, writes: Writes
) -> None:
    for address in range(10700, 10704):
        unit.holding[address] = 1
    device = AtreaRD5(unit)
    await device.async_update()
    assert device.control.follows_schedule is True

    await device.control.async_set_temperature(21.5)
    assert writes == [("holding", 10710, [215]), ("holding", 10702, [2])]
    assert device.control.temperature == 21.5
    assert device.control.temperature_source is ControlSource.TEMPORARY
    assert device.control.mode_source is ControlSource.SCHEDULE


async def test_source_is_read_fresh_before_a_write(
    device: AtreaRD5, unit: MockModbusUnit, writes: Writes
) -> None:
    # The control panel switched to the weekly program after the last poll.
    unit.holding[10700] = 1
    await device.control.async_set_power(R5Power.MAX_MAX)
    assert writes == [("holding", 10708, [38]), ("holding", 10700, [2])]


async def test_follow_schedule_is_one_write(device: AtreaRD5, writes: Writes) -> None:
    await device.control.async_follow_schedule(True)
    assert writes == [("holding", 10700, [1, 1, 1, 1])]
    assert device.control.follows_schedule is True
    await device.control.async_follow_schedule(False)
    assert writes[-1] == ("holding", 10700, [0, 0, 0, 0])


@pytest.mark.parametrize("temperature", [9.9, 40.1])
async def test_temperature_outside_the_range_is_refused(
    device: AtreaRD5, writes: Writes, temperature: float
) -> None:
    with pytest.raises(ValueError):
        await device.control.async_set_temperature(temperature)
    assert writes == []


async def test_unknown_mode_is_refused(device: AtreaRD5, writes: Writes) -> None:
    with pytest.raises(ValueError):
        await device.control.async_set_mode(8)  # type: ignore[arg-type]
    assert writes == []


async def test_settings_and_heat_storage_writes(
    device: AtreaRD5, writes: Writes
) -> None:
    await device.settings.write("season_mode", SeasonMode.T_ODA)
    assert device.heat_storage is not None
    await device.heat_storage.write("target_top", 50)
    await device.heat_storage.write("electric_heater_2", False)
    with pytest.raises(ValueError):
        await device.heat_storage.write("target_middle", 71)
    await device.bms_temperatures.write("indoor_air", 21.3)
    await device.bms_temperatures.write("outdoor_air", -5.5)
    await device.async_reset_filter_interval()
    await device.async_reset_alarms()
    assert writes == [
        ("holding", 11401, [2]),
        ("holding", 12925, [500]),
        ("holding", 12915, [0]),
        ("holding", 10214, [213]),
        ("holding", 10213, [65481]),
        ("coil", 10007, [True]),
        ("coil", 10005, [True]),
    ]


async def test_mode_the_unit_does_not_accept_now_is_refused(
    device: AtreaRD5, writes: Writes
) -> None:
    # Night precooling needs the non-heating season.
    with pytest.raises(ValueError):
        await device.async_set_mode(OperatingMode.NIGHT_PRECOOLING)
    assert writes == []
    await device.async_set_mode(OperatingMode.CIRCULATION)
    # The power follows the mode: Norm/Max becomes circulation Norm.
    assert writes == [("holding", 10709, [4]), ("holding", 10708, [21])]


async def test_vav_unit_takes_off_and_ventilation_only(
    unit: MockModbusUnit, writes: Writes
) -> None:
    unit.coil[10508] = True
    device = AtreaRD5(unit)
    await device.async_update()
    assert device.available_modes == (OperatingMode.OFF, OperatingMode.VENTILATION)
    with pytest.raises(ValueError):
        await device.async_set_mode(OperatingMode.AUTOMATIC)
    assert writes == []


@pytest.mark.parametrize("power", [0, 5, 13, 39, 100])
async def test_r5_unit_refuses_a_power_that_is_not_a_level(
    device: AtreaRD5, writes: Writes, power: int
) -> None:
    with pytest.raises(ValueError):
        await device.async_set_power(power)
    assert writes == []


async def test_direct_regulation_takes_percent(
    unit: MockModbusUnit, writes: Writes
) -> None:
    unit.holding[10510] = 0
    device = AtreaRD5(unit)
    await device.async_update()
    with pytest.raises(ValueError):
        await device.async_set_power(11)
    await device.async_set_power(12)
    assert writes == [("holding", 10708, [12])]


async def test_mode_under_the_weekly_program_and_temporary_source(
    unit: MockModbusUnit, writes: Writes
) -> None:
    unit.holding[10701] = 2  # already temporary
    device = AtreaRD5(unit)
    await device.async_update()
    await device.async_set_mode(OperatingMode.VENTILATION)
    assert writes == [
        ("holding", 10709, [2]),
        ("holding", 10701, [2]),
        ("holding", 10708, [12]),
    ]


@pytest.mark.parametrize("temperature", [10.0, 40.0])
async def test_temperature_at_the_limits_is_written(
    device: AtreaRD5, writes: Writes, temperature: float
) -> None:
    await device.control.async_set_temperature(temperature)
    assert writes == [("holding", 10710, [round(temperature * 10)])]


# What a DUPLEX RB5 did with a level of another family (register H10704).
@pytest.mark.parametrize(
    ("mode", "power", "effective"),
    [
        (OperatingMode.VENTILATION, 11, 11),
        (OperatingMode.VENTILATION, 21, 10),
        (OperatingMode.VENTILATION, 34, 11),
        (OperatingMode.CIRCULATION, 21, 21),
        (OperatingMode.CIRCULATION, 11, 20),
        (OperatingMode.CIRCULATION, 34, 21),
        (OperatingMode.UNBALANCED, 21, 10),
        (OperatingMode.UNBALANCED, 34, 11),
        (OperatingMode.OVERPRESSURE, 21, 10),
        (OperatingMode.OVERPRESSURE, 34, 11),
        (OperatingMode.CIRCULATION_WITH_VENTILATION, 34, 34),
        (OperatingMode.CIRCULATION_WITH_VENTILATION, 11, 31),
        (OperatingMode.CIRCULATION_WITH_VENTILATION, 21, 33),
    ],
)
def test_power_translation_matches_the_unit(
    mode: OperatingMode, power: int, effective: int
) -> None:
    assert r5_power_for_mode(R5Power(power), mode) == effective


def test_off_takes_no_power() -> None:
    assert r5_power_for_mode(R5Power.NORM_MAX, OperatingMode.OFF) is None


async def test_power_of_another_family_is_translated_on_write(
    device: AtreaRD5, writes: Writes
) -> None:
    # The unit is in circulation with ventilation.
    await device.async_set_power(R5Power.VENTILATION_MAX)
    assert writes == [("holding", 10708, [32])]
