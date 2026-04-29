import logging
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

logger = logging.getLogger(__name__)

LATITUDE = 51.23
LONGITUDE = 2.92
TZ = ZoneInfo("Europe/Brussels")

# Oostende beach faces NW (~315°). Perfect offshore wind comes from SE (~135°).
BEACH_FACE = 315

DIRECTIONS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
              "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]

REPORT_HOURS = [4, 7, 10, 13]

_SLOT_ICONS = {4: "🌅", 7: "☀️", 10: "🌤️", 13: "🌞"}
_SLOT_LABELS = {4: "4:00 AM", 7: "7:00 AM", 10: "10:00 AM", 13: "1:00 PM"}

_RATING_ICONS = {
    "Epic": "🔥",
    "Good": "🟢",
    "Fair": "🟡",
    "Poor": "🔴",
    "Flat": "😴",
}

_WIND_ICONS = {
    "Offshore": "✅",
    "Cross-offshore": "🟢",
    "Cross-onshore": "🟡",
    "Onshore": "❌",
}


def degrees_to_compass(degrees: float) -> str:
    return DIRECTIONS[round(degrees / 22.5) % 16]


def _angle_diff(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def _wind_label(wind_dir: float) -> str:
    offshore_source = (BEACH_FACE + 180) % 360  # 135° = SE
    rel = _angle_diff(wind_dir, offshore_source)
    if rel <= 45:
        return "Offshore"
    elif rel <= 90:
        return "Cross-offshore"
    elif rel <= 135:
        return "Cross-onshore"
    else:
        return "Onshore"


def _compute_rating(wave_height: float, wave_period: float | None,
                    wave_dir: float | None, wind_speed: float | None,
                    wind_dir: float | None) -> str:
    if wave_height < 0.3:
        return "Flat"

    score = 0

    if wave_height >= 1.2:
        score += 4
    elif wave_height >= 0.8:
        score += 3
    elif wave_height >= 0.5:
        score += 2
    else:
        score += 1

    if wave_period is not None:
        if wave_period >= 7:
            score += 3
        elif wave_period >= 5:
            score += 2
        elif wave_period >= 3:
            score += 1

    if wave_dir is not None:
        rel = _angle_diff(wave_dir, BEACH_FACE)
        if rel <= 45:
            score += 2
        elif rel <= 90:
            score += 1

    if wind_dir is not None:
        label = _wind_label(wind_dir)
        if label == "Offshore":
            score += 2
        elif label == "Cross-offshore":
            score += 1
        elif label == "Onshore":
            score -= 1

    if wind_speed is not None and wind_speed > 8:
        score -= 1

    if score >= 8:
        return "Epic"
    elif score >= 5:
        return "Good"
    elif score >= 3:
        return "Fair"
    else:
        return "Poor"


def fetch_weekly_surf_slots(start_date: date, days: int = 5) -> list[tuple[date, list[dict]]] | None:
    end_date = start_date + timedelta(days=days - 1)
    start_str = start_date.isoformat()
    end_str = end_date.isoformat()
    try:
        marine_resp = requests.get(
            "https://marine-api.open-meteo.com/v1/marine",
            params={
                "latitude": LATITUDE,
                "longitude": LONGITUDE,
                "hourly": "wave_height,wave_period,wave_direction,wind_wave_height",
                "timezone": "Europe/Brussels",
                "start_date": start_str,
                "end_date": end_str,
            },
            timeout=15,
        )
        marine_resp.raise_for_status()
        marine = marine_resp.json()["hourly"]

        wind_resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": LATITUDE,
                "longitude": LONGITUDE,
                "hourly": "wind_speed_10m,wind_direction_10m,wind_gusts_10m",
                "wind_speed_unit": "ms",
                "timezone": "Europe/Brussels",
                "start_date": start_str,
                "end_date": end_str,
            },
            timeout=15,
        )
        wind_resp.raise_for_status()
        wind = wind_resp.json()["hourly"]

        times = marine.get("time", [])
        result = []
        for day_offset in range(days):
            target_date = start_date + timedelta(days=day_offset)
            date_str = target_date.isoformat()
            slots = []
            for hour in REPORT_HOURS:
                target_time = f"{date_str}T{hour:02d}:00"
                if target_time not in times:
                    continue
                idx = times.index(target_time)
                slots.append({
                    "hour": hour,
                    "wave_height": marine["wave_height"][idx],
                    "wave_period": marine["wave_period"][idx],
                    "wave_direction": marine["wave_direction"][idx],
                    "wind_wave_height": marine["wind_wave_height"][idx],
                    "wind_speed": wind["wind_speed_10m"][idx],
                    "wind_gusts": wind["wind_gusts_10m"][idx],
                    "wind_direction": wind["wind_direction_10m"][idx],
                })
            result.append((target_date, slots))
        return result
    except (requests.RequestException, ValueError, IndexError, KeyError) as e:
        logger.error("Failed to fetch weekly surf slots: %s", e)
        return None


def _format_week_slot(data: dict) -> str:
    hour = data.get("hour")
    wave_h = data.get("wave_height")
    wave_p = data.get("wave_period")
    wave_dir = data.get("wave_direction")
    wind_speed = data.get("wind_speed")
    wind_gusts = data.get("wind_gusts")
    wind_dir = data.get("wind_direction")

    label = f"{hour:02d}:00"

    wave_str = ""
    if wave_h is not None:
        dir_str = f" {degrees_to_compass(wave_dir)}" if wave_dir is not None else ""
        period_str = f" {wave_p:.0f}s" if wave_p is not None else ""
        energy_str = f" {_wave_energy_kj(wave_h, wave_p):.0f}kJ" if wave_p is not None else ""
        wave_str = f"🌊 {wave_h:.1f}m{dir_str}{period_str}{energy_str}"

    wind_str = ""
    if wind_speed is not None:
        wlabel = _wind_label(wind_dir) if wind_dir is not None else ""
        wicon = _WIND_ICONS.get(wlabel, "")
        dir_str = f" {degrees_to_compass(wind_dir)}" if wind_dir is not None else ""
        gusts_str = f" g{wind_gusts:.0f}" if wind_gusts is not None else ""
        wind_str = f"💨 {wind_speed:.0f}m/s{dir_str}{gusts_str} {wicon}".strip()

    rating_str = ""
    if wave_h is not None:
        rating = _compute_rating(wave_h, wave_p, wave_dir, wind_speed, wind_dir)
        ricon = _RATING_ICONS.get(rating, "")
        rating_str = f"{rating} {ricon}"

    parts = [p for p in [wave_str, wind_str, rating_str] if p]
    return f"*{label}*  " + " | ".join(parts)


def _best_rating(slots: list[dict]) -> str:
    order = ["Epic", "Good", "Fair", "Poor", "Flat"]
    ratings = []
    for s in slots:
        wh = s.get("wave_height")
        if wh is not None:
            r = _compute_rating(wh, s.get("wave_period"), s.get("wave_direction"),
                                s.get("wind_speed"), s.get("wind_direction"))
            ratings.append(r)
    if not ratings:
        return ""
    return min(ratings, key=lambda r: order.index(r) if r in order else 99)


def format_weekly_surf_report(days_data: list[tuple[date, list[dict]]]) -> str:
    header = [
        "🏄 *Surf Forecast — Oostende* 🌊",
    ]
    blocks = []
    for target_date, slots in days_data:
        best = _best_rating(slots)
        best_icon = _RATING_ICONS.get(best, "")
        day_header = f"*{target_date.strftime('%A, %d %b')}*"
        if best:
            day_header += f"  —  Best: {best} {best_icon}"
        slot_lines = [_format_week_slot(s) for s in slots]
        slots_text = "\n".join(slot_lines)
        blocks.append(f"{day_header}\n────────────────────────\n{slots_text}")
    separator = "\n════════════════════════\n"
    return "\n".join(header) + separator + separator.join(blocks)


def fetch_daily_surf_slots(target_date: date) -> list[dict] | None:
    """Fetch surf conditions for all report slots (4AM, 7AM, 10AM, 1PM) for a given date."""
    date_str = target_date.isoformat()
    try:
        marine_resp = requests.get(
            "https://marine-api.open-meteo.com/v1/marine",
            params={
                "latitude": LATITUDE,
                "longitude": LONGITUDE,
                "hourly": "wave_height,wave_period,wave_direction,wind_wave_height",
                "timezone": "Europe/Brussels",
                "start_date": date_str,
                "end_date": date_str,
            },
            timeout=10,
        )
        marine_resp.raise_for_status()
        marine = marine_resp.json()["hourly"]

        wind_resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": LATITUDE,
                "longitude": LONGITUDE,
                "hourly": "wind_speed_10m,wind_direction_10m,wind_gusts_10m",
                "wind_speed_unit": "ms",
                "timezone": "Europe/Brussels",
                "start_date": date_str,
                "end_date": date_str,
            },
            timeout=10,
        )
        wind_resp.raise_for_status()
        wind = wind_resp.json()["hourly"]

        times = marine.get("time", [])
        slots = []
        for hour in REPORT_HOURS:
            target_time = f"{date_str}T{hour:02d}:00"
            idx = times.index(target_time) if target_time in times else hour
            slots.append({
                "hour": hour,
                "wave_height": marine["wave_height"][idx],
                "wave_period": marine["wave_period"][idx],
                "wave_direction": marine["wave_direction"][idx],
                "wind_wave_height": marine["wind_wave_height"][idx],
                "wind_speed": wind["wind_speed_10m"][idx],
                "wind_gusts": wind["wind_gusts_10m"][idx],
                "wind_direction": wind["wind_direction_10m"][idx],
            })
        return slots
    except (requests.RequestException, ValueError, IndexError, KeyError) as e:
        logger.error("Failed to fetch daily surf slots for %s: %s", target_date, e)
        return None


def _wave_energy_kj(wave_height: float, wave_period: float) -> float:
    """Wave energy per metre of crest width per wave (kJ/m). E ≈ 0.5 × H² × T²."""
    return 0.5 * wave_height ** 2 * wave_period ** 2


def _format_slot(data: dict) -> str:
    hour = data.get("hour")
    wave_h = data.get("wave_height")
    wave_p = data.get("wave_period")
    wave_dir = data.get("wave_direction")
    wind_wave_h = data.get("wind_wave_height")
    wind_speed = data.get("wind_speed")
    wind_gusts = data.get("wind_gusts")
    wind_dir = data.get("wind_direction")

    label = _SLOT_LABELS.get(hour, f"{hour:02d}:00")
    lines = [f"*{label}*"]

    if wave_h is not None:
        dir_str = f" from {degrees_to_compass(wave_dir)}" if wave_dir is not None else ""
        lines.append(f"🌊 Waves: {wave_h:.1f}m{dir_str}")
        if wave_p is not None:
            lines.append(f"   ⏱️ Period: {wave_p:.0f}s  ⚡ {_wave_energy_kj(wave_h, wave_p):.0f} kJ/m")

    if wind_wave_h is not None:
        lines.append(f"🌀 Wind swell: {wind_wave_h:.1f}m")

    if wind_speed is not None:
        wlabel = _wind_label(wind_dir) if wind_dir is not None else ""
        wicon = _WIND_ICONS.get(wlabel, "")
        dir_str = f" from {degrees_to_compass(wind_dir)}" if wind_dir is not None else ""
        gusts_str = f", gusts {wind_gusts:.0f} m/s" if wind_gusts is not None else ""
        wind_info = f"{wlabel} {wicon}".strip() if wlabel else ""
        wind_info_str = f" ({wind_info})" if wind_info else ""
        lines.append(f"💨 Wind: {wind_speed:.0f} m/s{dir_str}{gusts_str}{wind_info_str}")

    if wave_h is not None:
        rating = _compute_rating(wave_h, wave_p, wave_dir, wind_speed, wind_dir)
        ricon = _RATING_ICONS.get(rating, "")
        lines.append(f"📊 Rating: {rating} {ricon}")

    return "\n".join(lines)


def format_daily_surf_report(slots: list[dict], target_date: date, is_forecast: bool = False) -> str:
    tag = " _(forecast)_" if is_forecast else ""
    date_label = target_date.strftime("%A, %d %B %Y")
    header = [f"🏄 *Surf Report — Oostende* 🌊", f"📅 {date_label}{tag}"]
    slot_blocks = [_format_slot(s) for s in slots]
    separator = "\n─────────────────\n"
    return "\n".join(header) + separator + separator.join(slot_blocks)


# Keep for backwards compatibility (used nowhere currently but keeps API stable)
def fetch_surf_report() -> dict | None:
    try:
        marine_resp = requests.get(
            "https://marine-api.open-meteo.com/v1/marine",
            params={
                "latitude": LATITUDE,
                "longitude": LONGITUDE,
                "current": "wave_height,wave_period,wave_direction,wind_wave_height,wind_wave_period",
                "timezone": "Europe/Brussels",
            },
            timeout=10,
        )
        marine_resp.raise_for_status()
        marine = marine_resp.json()["current"]

        wind_resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": LATITUDE,
                "longitude": LONGITUDE,
                "current": "wind_speed_10m,wind_direction_10m,wind_gusts_10m",
                "wind_speed_unit": "ms",
                "timezone": "Europe/Brussels",
            },
            timeout=10,
        )
        wind_resp.raise_for_status()
        wind = wind_resp.json()["current"]

        return {
            "wave_height": marine.get("wave_height"),
            "wave_period": marine.get("wave_period"),
            "wave_direction": marine.get("wave_direction"),
            "wind_wave_height": marine.get("wind_wave_height"),
            "wind_speed": wind.get("wind_speed_10m"),
            "wind_gusts": wind.get("wind_gusts_10m"),
            "wind_direction": wind.get("wind_direction_10m"),
        }
    except requests.RequestException as e:
        logger.error("Failed to fetch surf report: %s", e)
        return None


def fetch_surf_forecast(target_date: date, hour: int = 10) -> dict | None:
    """Fetch surf conditions for a specific date at a given hour (default 10:00)."""
    date_str = target_date.isoformat()
    try:
        marine_resp = requests.get(
            "https://marine-api.open-meteo.com/v1/marine",
            params={
                "latitude": LATITUDE,
                "longitude": LONGITUDE,
                "hourly": "wave_height,wave_period,wave_direction,wind_wave_height",
                "timezone": "Europe/Brussels",
                "start_date": date_str,
                "end_date": date_str,
            },
            timeout=10,
        )
        marine_resp.raise_for_status()
        marine = marine_resp.json()["hourly"]

        wind_resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": LATITUDE,
                "longitude": LONGITUDE,
                "hourly": "wind_speed_10m,wind_direction_10m,wind_gusts_10m",
                "wind_speed_unit": "ms",
                "timezone": "Europe/Brussels",
                "start_date": date_str,
                "end_date": date_str,
            },
            timeout=10,
        )
        wind_resp.raise_for_status()
        wind = wind_resp.json()["hourly"]

        target_time = f"{date_str}T{hour:02d}:00"
        times = marine.get("time", [])
        idx = times.index(target_time) if target_time in times else hour

        return {
            "wave_height": marine["wave_height"][idx],
            "wave_period": marine["wave_period"][idx],
            "wave_direction": marine["wave_direction"][idx],
            "wind_wave_height": marine["wind_wave_height"][idx],
            "wind_speed": wind["wind_speed_10m"][idx],
            "wind_gusts": wind["wind_gusts_10m"][idx],
            "wind_direction": wind["wind_direction_10m"][idx],
        }
    except (requests.RequestException, ValueError, IndexError, KeyError) as e:
        logger.error("Failed to fetch surf forecast for %s: %s", target_date, e)
        return None


def format_surf_report(data: dict, date_label: str | None = None) -> str:
    wave_h = data.get("wave_height")
    wave_p = data.get("wave_period")
    wave_dir = data.get("wave_direction")
    wind_wave_h = data.get("wind_wave_height")
    wind_speed = data.get("wind_speed")
    wind_gusts = data.get("wind_gusts")
    wind_dir = data.get("wind_direction")

    if date_label is None:
        date_label = datetime.now(TZ).strftime("%A, %d %B %Y")
    lines = ["🏄 *Surf Report — Oostende* 🌊", f"📅 {date_label}", ""]

    if wave_h is not None:
        dir_str = f" from {degrees_to_compass(wave_dir)}" if wave_dir is not None else ""
        lines.append(f"🌊 Waves: {wave_h:.1f}m{dir_str}")
        if wave_p is not None:
            lines.append(f"   ⏱️ Period: {wave_p:.0f}s  ⚡ {_wave_energy_kj(wave_h, wave_p):.0f} kJ/m")

    if wind_wave_h is not None:
        lines.append(f"🌀 Wind swell: {wind_wave_h:.1f}m")

    if wind_speed is not None:
        wlabel = _wind_label(wind_dir) if wind_dir is not None else ""
        wicon = _WIND_ICONS.get(wlabel, "")
        dir_str = f" from {degrees_to_compass(wind_dir)}" if wind_dir is not None else ""
        gusts_str = f", gusts {wind_gusts:.0f} m/s" if wind_gusts is not None else ""
        wind_info_str = f" ({wlabel} {wicon})".strip() if wlabel else ""
        lines.append(f"💨 Wind: {wind_speed:.0f} m/s{dir_str}{gusts_str}{wind_info_str}")

    if wave_h is not None:
        rating = _compute_rating(wave_h, wave_p, wave_dir, wind_speed, wind_dir)
        ricon = _RATING_ICONS.get(rating, "")
        lines.append(f"\n📊 Rating: {rating} {ricon}")

    return "\n".join(lines)
