# atrea-modbus

Read and control Atrea DUPLEX ventilation units with **RD5** control over
Modbus TCP, as typed Python objects.

The library is built on
[modbus-connection](https://home-assistant-libs.github.io/modbus-connection/).
It takes a `ModbusUnit` and does not open a connection itself. It does not
depend on Home Assistant.

Atrea units with the newer **aMotion** control use a different register map.
This library does not support them yet. They would get their own sub-package next to `atrea_modbus.rd5`.

## Status

Alpha. Developed and tested against one unit: a DUPLEX RB5 with a heat pump and
an integrated heat storage tank, firmware 2.03.41. Other RD5 units should work
for everything that does not depend on the R_5 series, but nobody has tested
them yet.

## Before you start

Enable Modbus TCP on the unit: service parameter **3.15.1 Modbus TCP**. The
unit listens on port 502 and answers every unit id from 1 to 255.

## Use

```python
import asyncio

from modbus_connection import ModbusTcpParams
from modbus_connection.tmodbus import ModbusConnection

from atrea_modbus.rd5 import AtreaRD5, OperatingMode, R5Power


async def main() -> None:
    connection = ModbusConnection(ModbusTcpParams(host="192.168.1.50", port=502))
    try:
        device = AtreaRD5(connection.for_unit(1))
        await device.async_update()

        print(device.model, device.firmware_version)
        print("Outdoor air:", device.sensors.outdoor_air)
        print("Requested mode:", device.control.requested_mode)

        await device.control.async_set_mode(OperatingMode.VENTILATION)
        await device.control.async_set_power(R5Power.VENTILATION_NORM)
        await device.control.async_set_temperature(22.5)
    finally:
        await connection.close()


asyncio.run(main())
```

## What the device object holds

| Attribute | Content |
| --- | --- |
| `control` | Requested mode, power, temperature and zone, and who decides them (manual or the weekly program) |
| `sensors` | Air temperatures, air flows, the current season |
| `outputs` | Fans, valves, heat pump and relay outputs |
| `digital_inputs` | Digital inputs, and which extension boards are fitted |
| `alarms` | Every alarm and notice flag; `faults` names the active faults |
| `settings` | Season mode and its changeover temperature |
| `configuration` | Service settings that describe the installation; read once |
| `heat_storage` | Integrated heat storage tank: targets and electric heaters; `None` if not fitted |
| `tz_inputs`, `rg_inputs` | Inputs of the RD5-TZ and RD5-RG boards; `None` if not fitted |
| `bms_temperatures` | Room and outdoor temperature sent to the unit from outside |

`async_update_readings()` and `async_update_settings()` poll the two groups
apart. Each returns an `UpdateReport` that names the sub-systems that refreshed
and the ones that failed.

## How a change is written

The unit keeps four registers for each of mode, power, temperature and zone.
The library writes the "last manual value" register. If the weekly program
decides that value, the library then marks the change as temporary, as the
manufacturer prescribes. The change then holds until the next interval of the
weekly program. `control.async_follow_schedule()` hands control to the weekly
program or takes it back.

## How the modes behave

Some modes look broken over Modbus when they are only waiting. The help texts
of the unit's own web interface, and measurements on a DUPLEX RB5, say this:

- **Automatic**: the unit ventilates for `automatic_ventilation_interval`
  minutes of every hour and stands still for the rest, unless an input or a
  heating or cooling demand starts it.
- **Night precooling**: only in the non-heating season. The unit ventilates
  only while the room is warmer than the requested temperature and the
  outdoor air is cooler than the room; otherwise it stands still, and every
  `night_cooling_test_interval` minutes it runs the fans for five minutes to
  measure the real air temperatures. Measured on a DUPLEX RB5 with the room
  at 22.2 °C, 18 °C requested and 12 °C outdoors: after the switch the fans
  stood still for about 90 seconds, then ran without a break at the
  requested ventilation level (about 98 m³/h supply, 120 m³/h extract at
  Norm) for the 12 minutes of the test, and the supply air fell from 22.1 to
  18.4 °C. The requested flow registers read 0 m³/h supply in this mode.
- **Any mode change**: the fans stop for about 90 seconds before the new
  mode runs. A season change takes effect within 15 seconds.
- **Unbalanced**: the supply fan runs `supply_fan_correction` percent faster
  or slower than the extract fan. At 0 the mode equals ventilation.
- **Overpressure**: the supply fan runs at the power level and the extract fan
  is off.
- **R_5 power levels**: a level stands for the air flows in `r5_flows`. Given
  a level of another family, the unit runs the matching level of the family
  the mode takes: circulation levels for circulation, combined levels for
  automatic and circulation with ventilation, ventilation levels for the
  rest. The unit's web interface offers the same sets. `async_set_mode()` and
  `async_set_power()` write that matching level, so the request says what the
  unit will do.
- **Available modes**: register I12004 is a bit mask of the modes the unit
  lets a user request. `available_modes` combines it with the conditions of
  the source document.

## Query a unit

```bash
uv run script/query.py 192.168.1.50          # print every value; read-only
uv run script/query.py 192.168.1.50 --raw    # also dump the raw registers
```

A raw dump loads into the mock of modbus-connection, so a dump from an issue
report becomes a test. The dump leaves the production number of the unit out.

## Known gaps

- The power levels 10 to 38 are those of an R_5 unit set up for two-zone
  operation, measured on a DUPLEX RB5. The web interface of the unit gives an
  R_5 unit without two-zone operation the values 1 to 9 in the automatic mode
  and 1 to 3 in the other modes. The library accepts these values for such a
  unit, but nobody tested them.
- Night precooling is offered only in the non-heating season, as the source
  document says. The unit itself reports the mode as accepted in the heating
  season too; what it does then is untested.
- The alarm names from D11156 on are paired with their addresses by their
  order in the source table.
- The zone values are untested: the test unit has one zone.
- Service parameters are read, never written. Atrea advises against changing
  them over Modbus.

## Sources

The register tables are Atrea documents and are not part of this repository.

- "Indexy protokolu Modbus TCP - RD5 regulace" / "Index table for Modbus TCP -
  RD5 control system", Atrea, 2021: the full register table.
- "Modbus communication - RD5, aMotion", Atrea, version 04, 2025, from the
  documents section of atrea.eu: the registers for normal control.
- The web interface the unit serves (`scripts.js`, `lang/userCtrl.xml` and the
  help texts): which power levels each mode takes, which modes the unit
  accepts, and what the service parameters mean.

## Develop

```bash
uv sync
uv run pytest
uv run ruff format --check . && uv run ruff check . && uv run mypy
```
