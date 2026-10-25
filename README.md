# Enviro Weather -> InfluxDB

Pimoroni Enviro Weather board (Pico W, MicroPython) uploading readings to an InfluxDB v2 server, plus an Influx dashboard template.

> Directed by James Stanbridge — written and prepared with Claude Code (Anthropic).

## Layout
- `board/` — backup of the board's filesystem (Pimoroni `enviro` + `phew` firmware, with the local patches listed in `CLAUDE.md`). `config.py`, `log.txt` and runtime state are git-ignored.
- `dashboard/build_dashboard.py` — generates `dashboard/perry-weather.json`, an InfluxDB dashboard template (UI: Settings > Templates > Import, or `influx apply -f dashboard/perry-weather.json`).
- `CLAUDE.md` — working notes: hardware, config, tooling, outage history.

## Setup
Copy `board/enviro/config_template.py` values into a `config.py` on the board (provisioning creates it) with `destination = 'influxdb'` and your Influx URL, org, bucket and a write token. Never commit `config.py` or `.env`.

## Credits
`board/enviro/` and `board/phew/` are from [pimoroni/enviro](https://github.com/pimoroni/enviro) and [pimoroni/phew](https://github.com/pimoroni/phew), both MIT licensed. Local modifications are marked `# PATCH`.
