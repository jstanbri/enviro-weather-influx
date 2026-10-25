"""Build the InfluxDB v2 dashboard template for the Enviro Weather board ("perry").

    python3 dashboard/build_dashboard.py

writes dashboard/perry-weather.json (import via InfluxDB UI: Settings > Templates > Import,
or `influx apply -f dashboard/perry-weather.json`).
Data model: measurement = metric name, field = "value", tag device = nickname.
"""
import json
import pathlib

DEVICE = "perry"
OUT = pathlib.Path(__file__).with_name("perry-weather.json")


def metric(name, rng="v.timeRangeStart, stop: v.timeRangeStop"):
    return f"""from(bucket: "enviro")
  |> range(start: {rng})
  |> filter(fn: (r) => r.device == "{DEVICE}" and r._measurement == "{name}" and r._field == "value")"""


def latest(name, window="-24h"):
    return metric(name, window) + "\n  |> last()"


def series(name):
    """Windowed mean of one metric (follows the dashboard time range)."""
    return metric(name) + "\n  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)\n  |> yield(name: \"mean\")"


COMPASS = '["N", "NE", "E", "SE", "S", "SW", "W", "NW"]'

Q = {
    "temp_now": latest("temperature"),
    "hum_now": latest("humidity"),
    "press_now": latest("pressure"),
    "wind_now": latest("wind_speed"),
    "wind_from": f"""compass = {COMPASS}
{latest("wind_direction")}
  |> map(fn: (r) => ({{_time: r._time, _value: compass[int(v: (r._value + 22.5) / 45.0) % 8]}}))""",
    "rain_24h": metric("rain", "-24h") + "\n  |> sum()",
    "age_min": latest("temperature") + """
  |> map(fn: (r) => ({_time: r._time, _value: float(v: int(v: now()) - int(v: r._time)) / 60000000000.0}))""",
    "readings_1h": """import "array"

n = """ + metric("temperature", "-1h") + """
  |> count()
  |> group()

union(tables: [n, array.from(rows: [{_value: 0}])])
  |> group()
  |> sum()""",
    "temp_hi": metric("temperature", "-24h") + "\n  |> max()",
    "temp_lo": metric("temperature", "-24h") + "\n  |> min()",
    "temp_dew": """import "math"

base = from(bucket: "enviro")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r.device == "%s" and r._field == "value" and (r._measurement == "temperature" or r._measurement == "humidity"))
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
  |> pivot(rowKey: ["_time"], columnKey: ["_measurement"], valueColumn: "_value")
  |> filter(fn: (r) => exists r.temperature and exists r.humidity and r.humidity > 0.0)

temperature = base
  |> map(fn: (r) => ({_time: r._time, _value: r.temperature, _field: "temperature"}))

// Magnus approximation
dew_point = base
  |> map(fn: (r) => {
    g = math.log(x: r.humidity / 100.0) + (17.625 * r.temperature) / (243.04 + r.temperature)
    return {_time: r._time, _value: 243.04 * g / (17.625 - g), _field: "dew point"}
  })

union(tables: [temperature, dew_point])
  |> group(columns: ["_field"])
  |> sort(columns: ["_time"])""" % DEVICE,
    "battery_now": latest("voltage", "-7d"),
    "battery": series("voltage"),
    "humidity": series("humidity"),
    "pressure": series("pressure"),
    "wind": metric("wind_speed") + """
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
  |> set(key: "_field", value: "mean")
  |> yield(name: "mean")

""" + metric("wind_speed") + """
  |> aggregateWindow(every: v.windowPeriod, fn: max, createEmpty: false)
  |> set(key: "_field", value: "gust (max)")
  |> yield(name: "gust")""",
    "rain": metric("rain") + """
  |> aggregateWindow(every: if int(v: v.windowPeriod) < 3600000000000 then 1h else v.windowPeriod, fn: sum, createEmpty: false)
  |> yield(name: "rain")""",
    "lux": series("luminance"),
    "wind_mix": f"""sectors = {COMPASS}
{metric("wind_direction")}
  |> map(fn: (r) => ({{r with sector: sectors[int(v: (r._value + 22.5) / 45.0) % 8]}}))
  |> group(columns: ["sector"])
  |> count()
  |> group()
  |> rename(columns: {{_value: "readings"}})
  |> keep(columns: ["sector", "readings"])
  |> sort(columns: ["readings"], desc: true)""",
    "readings_hr": metric("temperature") + """
  |> aggregateWindow(every: 1h, fn: count, createEmpty: true)
  |> map(fn: (r) => ({r with _value: if exists r._value then r._value else 0}))
  |> yield(name: "readings per hour")""",
}


def colour(hex_, name="c", type_="text", value=None):
    c = {"name": name, "type": type_, "hex": hex_}
    if value is not None:
        c["value"] = value
    return c


def thresholds(base, *steps):
    """base colour, then (value, colour) steps; used as background-less text thresholds."""
    return [colour(base, "base", "text", 0)] + [colour(h, f"t{i}", "text", v) for i, (v, h) in enumerate(steps)]


GREEN, AMBER, RED, BLUE, TEAL = "#7CE490", "#FFB94A", "#F95F53", "#4591ED", "#31C0F6"
SCALE = [colour("#31C0F6", "a", "scale"), colour("#A500A5", "b", "scale"), colour("#FF7E27", "c", "scale")]


def stat(name, key, x, y, w, h, suffix="", decimals=1, colors=None):
    return {
        "kind": "Single_Stat", "name": name, "queries": [{"query": Q[key]}],
        "colors": colors or [colour(TEAL, "base", "text", 0)],
        "decimalPlaces": decimals, "suffix": suffix, "prefix": "",
        "xPos": x, "yPos": y, "width": w, "height": h,
    }


def xy(name, key, x, y, w, h, label, suffix="", geom="line", colors=None, legend=False):
    return {
        "kind": "XY", "name": name, "queries": [{"query": Q[key]}],
        "axes": [{"name": "x", "label": "", "base": "", "scale": "linear"},
                 {"name": "y", "label": label, "suffix": suffix, "base": "10", "scale": "linear"}],
        "colors": colors or SCALE, "geom": geom, "xCol": "_time", "yCol": "_value",
        "position": "overlaid", "legendOpacity": 1.0, "legendOrientationThreshold": 100000000,
        "hoverDimension": "auto", "shade": geom == "line" and not legend,
        "xPos": x, "yPos": y, "width": w, "height": h,
    }


charts = [
    # row 1: right-now numbers
    stat("Temperature", "temp_now", 0, 0, 2, 3, " °C", 1),
    stat("Humidity", "hum_now", 2, 0, 2, 3, " %", 0),
    stat("Pressure", "press_now", 4, 0, 2, 3, " hPa", 0),
    stat("Wind", "wind_now", 6, 0, 2, 3, " m/s", 1),
    stat("Wind from", "wind_from", 8, 0, 2, 3, "", 0),
    stat("Rain, 24 h", "rain_24h", 10, 0, 2, 3, " mm", 1),
    # row 2: highs/lows + board health
    stat("24 h high", "temp_hi", 0, 3, 3, 2, " °C", 1, [colour("#FF7E27", "hi", "text", 0)]),
    stat("24 h low", "temp_lo", 3, 3, 3, 2, " °C", 1, [colour(BLUE, "lo", "text", 0)]),
    stat("Last reading (min ago)", "age_min", 6, 3, 3, 2, " min", 0,
         thresholds(GREEN, (35, AMBER), (60, RED))),
    stat("Readings, last hour (7+ ok, 12 max)", "readings_1h", 9, 3, 3, 2, "", 0,
         thresholds(RED, (4, AMBER), (7, GREEN))),
    # row 3: battery (volts at VSYS; USB reads ~4.7-5, fresh 3xAAA alkaline ~4.5)
    stat("Battery", "battery_now", 0, 5, 3, 4, " V", 2, thresholds(RED, (3.4, AMBER), (4.0, GREEN))),
    xy("Battery voltage", "battery", 3, 5, 9, 4, "V", " V"),
    # row 4
    xy("Temperature & dew point", "temp_dew", 0, 9, 8, 4, "°C", " °C"),
    xy("Humidity", "humidity", 8, 9, 4, 4, "%", " %"),
    # row 4
    xy("Pressure", "pressure", 0, 13, 6, 4, "hPa", " hPa"),
    xy("Wind speed", "wind", 6, 13, 6, 4, "m/s", " m/s"),
    # row 5
    xy("Rain", "rain", 0, 17, 6, 4, "mm", " mm", geom="bar"),
    xy("Light", "lux", 6, 17, 6, 4, "lux", " lux"),
    # row 6
    {"kind": "Table", "name": "Wind direction mix", "queries": [{"query": Q["wind_mix"]}],
     "colors": [colour(TEAL, "base", "text", 0)], "decimalPlaces": 0,
     "tableOptions": {"verticalTimeAxis": True, "sortBy": "", "wrapping": "", "fixFirstColumn": False},
     "timeFormat": "YYYY-MM-DD HH:mm:ss",
     "xPos": 0, "yPos": 21, "width": 4, "height": 4},
    xy("Readings per hour (gaps = outages)", "readings_hr", 4, 21, 8, 4, "readings", "", geom="bar",
       colors=[colour(TEAL, "a", "scale"), colour(TEAL, "b", "scale")]),
]

template = {
    "apiVersion": "influxdata.com/v2alpha1",
    "kind": "Dashboard",
    "metadata": {"name": "perry-weather"},
    "spec": {"name": "Perry weather", "description": "Enviro Weather board: now, trends, derived values, board health",
             "charts": charts},
}

if __name__ == "__main__":
    OUT.write_text(json.dumps([template], indent=2) + "\n")
    print(f"wrote {OUT} ({len(charts)} cells)")
