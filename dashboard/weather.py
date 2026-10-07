"""Weather for CAP's panel, from Open-Meteo (free, no API key or account).

    python weather.py "Boston, MA"
    python weather.py --json "Boston, MA"   # one line of JSON (used by CAP)

Only the place name (to look up its coordinates) and those coordinates are sent
to open-meteo.com. Nothing is saved.
"""
import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"
TEMP_UNIT, WIND_UNIT = "fahrenheit", "mph"  # or "celsius", "kmh"
HOURS, DAYS = 8, 5

# WMO weather codes -> (description, icon)
CODES = {
    0: ("Clear", "clear"), 1: ("Mostly clear", "partly"), 2: ("Partly cloudy", "partly"), 3: ("Overcast", "cloudy"),
    45: ("Fog", "fog"), 48: ("Freezing fog", "fog"),
    51: ("Light drizzle", "rain"), 53: ("Drizzle", "rain"), 55: ("Heavy drizzle", "rain"),
    56: ("Freezing drizzle", "rain"), 57: ("Freezing drizzle", "rain"),
    61: ("Light rain", "rain"), 63: ("Rain", "rain"), 65: ("Heavy rain", "rain"),
    66: ("Freezing rain", "rain"), 67: ("Freezing rain", "rain"),
    71: ("Light snow", "snow"), 73: ("Snow", "snow"), 75: ("Heavy snow", "snow"), 77: ("Snow grains", "snow"),
    80: ("Rain showers", "rain"), 81: ("Rain showers", "rain"), 82: ("Heavy showers", "rain"),
    85: ("Snow showers", "snow"), 86: ("Heavy snow showers", "snow"),
    95: ("Thunderstorm", "storm"), 96: ("Thunderstorm, hail", "storm"), 99: ("Thunderstorm, hail", "storm"),
}


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def get(url: str, params: dict) -> dict:
    req = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}", headers={"User-Agent": "CAP-weather"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)
    except urllib.error.URLError as e:
        sys.exit(f"Couldn't reach Open-Meteo ({getattr(e, 'reason', e)}). Check your internet connection.")


def find_place(place: str) -> dict:
    """'Boston, MA' -> search 'Boston', prefer a result whose state/country matches 'MA'."""
    name, *rest = [part.strip() for part in place.split(",")]
    hints = [h.lower() for h in rest if h]
    results = get(GEOCODE, {"name": name, "count": 10, "language": "en", "format": "json"}).get("results") or []
    if not results:
        sys.exit(f"Couldn't find a place called \"{place}\". Try just the city name.")

    def matches(r):
        fields = [str(r.get(k, "")).lower() for k in ("admin1", "country", "country_code")]
        return all(any(h == f or (len(h) > 2 and h in f) for f in fields) or h == STATE_CODES.get(r.get("admin1", "")) for h in hints)

    return next((r for r in results if matches(r)), results[0])


STATE_CODES = {  # so "Boston, MA" finds Massachusetts
    "Alabama": "al", "Alaska": "ak", "Arizona": "az", "Arkansas": "ar", "California": "ca", "Colorado": "co",
    "Connecticut": "ct", "Delaware": "de", "Florida": "fl", "Georgia": "ga", "Hawaii": "hi", "Idaho": "id",
    "Illinois": "il", "Indiana": "in", "Iowa": "ia", "Kansas": "ks", "Kentucky": "ky", "Louisiana": "la",
    "Maine": "me", "Maryland": "md", "Massachusetts": "ma", "Michigan": "mi", "Minnesota": "mn",
    "Mississippi": "ms", "Missouri": "mo", "Montana": "mt", "Nebraska": "ne", "Nevada": "nv",
    "New Hampshire": "nh", "New Jersey": "nj", "New Mexico": "nm", "New York": "ny", "North Carolina": "nc",
    "North Dakota": "nd", "Ohio": "oh", "Oklahoma": "ok", "Oregon": "or", "Pennsylvania": "pa",
    "Rhode Island": "ri", "South Carolina": "sc", "South Dakota": "sd", "Tennessee": "tn", "Texas": "tx",
    "Utah": "ut", "Vermont": "vt", "Virginia": "va", "Washington": "wa", "West Virginia": "wv",
    "Wisconsin": "wi", "Wyoming": "wy", "District of Columbia": "dc",
}


def describe(code: int) -> tuple:
    return CODES.get(code, ("Unknown", "cloudy"))


def weather(place: str) -> dict:
    log(f"Locating {place}")
    p = find_place(place)
    log(f"Fetching forecast for {p['name']}")
    f = get(FORECAST, {
        "latitude": p["latitude"], "longitude": p["longitude"], "timezone": "auto",
        "temperature_unit": TEMP_UNIT, "wind_speed_unit": WIND_UNIT, "forecast_days": DAYS + 1,
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,is_day",
        "hourly": "temperature_2m,weather_code,precipitation_probability,is_day",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
    })
    cur, hourly, daily = f["current"], f["hourly"], f["daily"]

    # Hourly times are local "YYYY-MM-DDTHH:00"; start at the current hour.
    this_hour = cur["time"][:13]
    start = next((i for i, t in enumerate(hourly["time"]) if t[:13] >= this_hour), 0)
    hours = [{
        "time": hourly["time"][i], "temp": round(hourly["temperature_2m"][i]),
        "rain": hourly["precipitation_probability"][i], "is_day": bool(hourly["is_day"][i]),
        "icon": describe(hourly["weather_code"][i])[1],
    } for i in range(start, min(start + HOURS, len(hourly["time"])))]

    days = [{
        "date": daily["time"][i], "high": round(daily["temperature_2m_max"][i]), "low": round(daily["temperature_2m_min"][i]),
        "rain": daily["precipitation_probability_max"][i],
        "summary": describe(daily["weather_code"][i])[0], "icon": describe(daily["weather_code"][i])[1],
    } for i in range(min(DAYS, len(daily["time"])))]

    summary, icon = describe(cur["weather_code"])
    return {
        "place": {"name": p["name"], "region": p.get("admin1"), "country": p.get("country")},
        "units": {"temp": "°F" if TEMP_UNIT == "fahrenheit" else "°C", "wind": WIND_UNIT},
        "current": {
            "temp": round(cur["temperature_2m"]), "feels_like": round(cur["apparent_temperature"]),
            "humidity": cur["relative_humidity_2m"], "wind": round(cur["wind_speed_10m"]),
            "is_day": bool(cur["is_day"]), "summary": summary, "icon": icon,
        },
        "today": {**days[0], "sunrise": daily["sunrise"][0], "sunset": daily["sunset"][0]} if days else None,
        "hours": hours,
        "days": days,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("place", help='a city, optionally with state or country, e.g. "Boston, MA"')
    ap.add_argument("--json", action="store_true", help="print one line of JSON")
    args = ap.parse_args()
    w = weather(args.place)
    if args.json:
        print(json.dumps(w))
        return
    c, u = w["current"], w["units"]
    where = ", ".join(x for x in (w["place"]["name"], w["place"]["region"]) if x)
    print(f"{where}: {c['temp']}{u['temp']} {c['summary']} (feels like {c['feels_like']}{u['temp']}), "
          f"humidity {c['humidity']}%, wind {c['wind']} {u['wind']}")
    for d in w["days"]:
        print(f"  {d['date']}  {d['high']:>3}/{d['low']:<3} {d['summary']}  rain {d['rain']}%")


if __name__ == "__main__":
    main()
