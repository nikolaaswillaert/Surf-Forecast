import logging
import os
from datetime import date

import requests
from apscheduler.schedulers.background import BackgroundScheduler

from storage import get_todays_birthdays
from surf_report import TZ, fetch_weekly_surf_slots, fetch_high_tides_range, fetch_stormglass_today, fetch_visualcrossing, format_weekly_surf_report

logger = logging.getLogger(__name__)


def _send_message(chat_id: str, text: str) -> None:
    waha_base = os.environ["WAHA_BASE_URL"]
    session = os.environ["WAHA_SESSION"]
    api_key = os.environ.get("WAHA_API_KEY", "")
    
    try:
        resp = requests.post(
            f"{waha_base}/api/sendText",
            json={"chatId": chat_id, "text": text, "session": session},
            headers={"X-Api-Key": api_key},
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error("Failed to send message to %s: %s", chat_id, e)


def send_birthday_reminders() -> None:
    birthdays = get_todays_birthdays()
    if not birthdays:
        return

    chat_id = os.environ["REMINDER_CHAT_ID"]
    for b in birthdays:
        text = f"Today is {b['name']}'s birthday! Don't forget to wish them well!"
        _send_message(chat_id, text)
        logger.info("Sent birthday reminder for %s", b["name"])


def send_morning_surf_report() -> None:
    chat_id = os.environ.get("SURF_GROUP_CHAT_ID", "")
    if not chat_id:
        logger.warning("SURF_GROUP_CHAT_ID not set, skipping morning surf report")
        return

    days_data = fetch_weekly_surf_slots(date.today(), days=5)
    if days_data is None:
        logger.error("Could not fetch surf data for morning report")
        return

    high_tides = fetch_high_tides_range(date.today(), days=5)

    sg_key = os.environ.get("STORMGLASS_API_KEY", "")
    sg_today = fetch_stormglass_today(sg_key) if sg_key else None

    vc_key = os.environ.get("VISUALCROSSING_API_KEY", "")
    vc_data = fetch_visualcrossing(vc_key) if vc_key else None

    report = format_weekly_surf_report(days_data, high_tides, sg_today=sg_today, vc_data=vc_data)
    _send_message(chat_id, report)
    logger.info("Sent morning weekly surf report to %s", chat_id)


def start_scheduler(reminder_time: str = "09:00") -> BackgroundScheduler:
    hour, minute = map(int, reminder_time.split(":"))
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        send_birthday_reminders,
        trigger="cron",
        hour=hour,
        minute=minute,
        id="daily_birthday_check",
    )
    scheduler.add_job(
        send_morning_surf_report,
        trigger="cron",
        hour=6,
        minute=0,
        id="morning_surf_report",
    )
    scheduler.start()
    logger.info("Scheduler started — birthday check at %s, surf report at 06:00", reminder_time)
    return scheduler
