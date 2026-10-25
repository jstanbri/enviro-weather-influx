# Enviro Weather – project context

Pimoroni **Enviro Weather** board (Pico W soldered on, RP2040, MicroPython).
The firmware reports `model: weather` (wind speed/direction, rain, temperature, humidity, pressure, luminance).
Nickname `perry`; uploads to the existing InfluxDB v2 server at `http://192.168.1.232:8086` (org `home`, bucket `enviro`).
The board log reports `Enviro 0.0.10, MicroPython v1.22.2, enviro v1.22.2 (2024-03-06)`. Host: Windows 11, commands run from WSL2
(mirrored networking) via `mpremote.exe`.
`board/` is a full local backup of the board filesystem (see Board filesystem).

## Goal
1. ~~Get stock Enviro firmware uploading readings to InfluxDB v2.~~ Done: 5-minute readings, uploaded immediately.
2. Explore the data in Python (learn which features matter).
3. Later: Rust service / Azure (Cosmos DB or Azure SQL) once the data is understood.

## Hardware (from pimoroni/enviro source)
> Written for the Indoor board; this is a Weather board, so the sensor details below (BME688, BH1745, gas/AQI)
> are unverified for it. Check `enviro/boards/weather.py` before relying on them.
- I2C via `PimoroniI2C(I2C_SDA_PIN, I2C_SCL_PIN, 100000)`. Use the constants in `enviro.constants`, don't hard-code the pins.
- **BME688** @ 0x77, read with `breakout_bme68x.BreakoutBME68X`: `read()` returns `(temp °C, pressure Pa, humidity %, gas Ω, …)`
- **BH1745** colour/light sensor @ 0x38 (56), read with `breakout_bh1745.BreakoutBH1745`.
  You must write `i2c.writeto_mem(0x38, 0x44, b'\x02')` after init or it returns bad values (undocumented).
- **PCF85063A** RTC @ 0x51 handles the wake alarm and the warn LED (via its clock-out pin).
- `HOLD_VSYS_EN_PIN` must be driven high early, otherwise the board powers off on battery.
- `vbus_present = Pin("WL_GPIO2", Pin.IN).value()` tells you whether it's on USB power.
- On USB the board self-heats; the firmware subtracts `config.usb_power_temperature_offset`.
- Derived values: `aqi = log(gas_resistance) + 0.04 * humidity`. Lux and colour temperature are computed from raw RGBC (see `enviro/boards/indoor.py`).

## Board filesystem
- `main.py`, `enviro/`, `phew/`: Pimoroni code. Edits are fine now that `board/` holds a backup, but keep them minimal and listed below.
- `config.py` is created by provisioning and holds Wi-Fi and Influx settings. **Never commit it.**
  Current settings: `destination='influxdb'`, `reading_frequency=5` (min), `upload_frequency=6` (upload every 30 min to save battery;
  `1` is only for testing on USB, since it is ~6x the Wi-Fi sessions).
- `log.txt` (contains the Wi-Fi password, git-ignored), `readings/YYYY-MM-DD.csv`, `uploads/*.json` (pending upload cache), `last_lux.txt` (see patch).
- Local edits to Pimoroni code (reapply after a reflash):
  - `enviro/boards/weather.py` `get_sensor_readings`: `ltr559.get_reading()` intermittently returns `None` and crashed the cycle
    (`TypeError` at line 198, no upload). Now retries 10x, then falls back to the last good lux in `last_lux.txt` (0 if none).
  - `enviro/__init__.py`: battery voltage measurement re-enabled (stock had it commented out) and `readings["voltage"]` restored, so Influx gets a `voltage` metric
    (VSYS in volts: USB reads ~4.7-5, fresh 3xAAA alkaline ~4.5; dashboard goes amber below 4.0, red below 3.4 - thresholds are a guess, tune once seen).
- Sync with `mpremote.exe connect COM3 fs cp -r : ./board/`; push a file with `fs cp board/<f> :<f>`.

## InfluxDB (existing server on the LAN, `192.168.1.232:8086`, v2.9.1)
- org `home`, bucket `enviro`. The token in `.env` (`INFLUX_WRITE_TOKEN`, git-ignored) can read and write. `INFLUX_ADMIN_*` in `.env` are leftovers from a removed local container.
- The Enviro uploader POSTs to `/api/v2/write?precision=s&org=…&bucket=…` with header
  `Authorization: Token <token>`. Each line looks like `<metric>,device=<nickname> value=<v> <epoch_s>`.
  Only HTTP 204 counts as success. Metrics: temperature, humidity, pressure, luminance, rain, rain_per_second, wind_speed, wind_direction.
- Check data arrived: Flux query via `POST /api/v2/query?org=home` (`Content-Type: application/vnd.flux`, `Accept: application/csv`), e.g. count `device=="perry"`.
- The earlier local Docker InfluxDB (and its compose file/volume) was removed. If the PC ever hosts it again: the board needs the PC's **LAN IP**, an inbound
  Windows rule for TCP 8086 on the profile the Wi-Fi uses (it is **Public**, not Private), and, because WSL2 runs in mirrored mode, a Hyper-V firewall rule too:
  `New-NetFirewallHyperVRule -Name InfluxDB8086 -DisplayName "InfluxDB 8086" -Direction Inbound -VMCreatorId '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}' -Protocol TCP -LocalPorts 8086 -Action Allow`.
  No router change needed (same LAN); reserve the host's DHCP address.

## Outdoor operation and outages
- The board sleeps between readings and has **no remote access**: Wi-Fi is off between wakes and there is no IP service. The only ways to see what it
  is doing are the data in Influx and, once it is brought in, `log.txt` over USB. Router client list (MAC (see the board log), reserved IP `192.168.1.108`) shows whether it is alive.
- 2026-10-25: the board died outdoors after the 15:00 reading (batteries failed). The log shows a clean last cycle, then a restart at `2000-01-01`
  (RTC lost power). Readings 15:05-18:04 are permanently missing. Fresh batteries + `upload_frequency=6` afterwards.
- Firmware logged "on usb power" while outside, so the `usb_power_temperature_offset` (4.5 C) may have been mis-applied; expect a ~4.5 C step in
  temperature when moving between USB and battery.
- Battery voltage is now reported (see patches above); watch the dashboard Battery cell for decline before it fails outdoors.
- Dashboard: `dashboard/build_dashboard.py` generates `dashboard/perry-weather.json` (import via Influx UI > Templates). Health cells expect batched
  uploads (last reading under 35 min is green; 7+ readings in the last hour is green).

## Tooling
- Use `mpremote` (`pip install mpremote`), not Thonny, when working from Claude Code.
  **Close Thonny first.** Only one program can hold the COM port.
  - `mpremote connect COMx fs ls`
  - `mpremote connect COMx fs cp :log.txt .` (pull a file from the board)
  - `mpremote connect COMx run script.py` (run without copying to the board)
  - `mpremote connect COMx mount .` (Enviro's `phew.remote_mount` supports this)
  - Ctrl-C interrupts `main.py`; `mpremote reset` soft-resets.
  - **Any `mpremote` connection interrupts the board's idle loop**, which on USB power is what waits for the RTC alarm and restarts it. After pulling files the board
    stays idle until you press the physical reset button. Verify uploads from the Influx side and pull `log.txt` sparingly.
- Pico W Wi-Fi is 2.4 GHz only.

## Conventions
- MicroPython on the device, Python 3 for exploration/scripts on the PC, Rust for anything long-lived.
- Keep secrets out of the repo (`config.py`, `.env`).
