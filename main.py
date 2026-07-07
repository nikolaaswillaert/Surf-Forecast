import logging
import os

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv()

from scheduler import start_scheduler
from storage import add_birthday, delete_birthday, load_birthdays
from datetime import date, datetime, timedelta

from surf_report import TZ, fetch_daily_surf_slots, fetch_weekly_surf_slots, fetch_high_tides_range, fetch_stormglass_today, fetch_visualcrossing, format_daily_surf_report, format_weekly_surf_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)


def format_date(day: int, month: int) -> str:
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(day if day < 20 else day % 10, "th")
    month_name = ["January", "February", "March", "April", "May", "June",
                  "July", "August", "September", "October", "November", "December"][month - 1]
    return f"{day}{suffix} {month_name}"


HELP_TEXT = (
    "*Birthday Reminder Bot*\n\n"
    "Commands:\n"
    "  bday add <name> <DD-MM> — Add a birthday\n"
    "  bday list — Show all birthdays\n"
    "  bday remove <name> — Remove a birthday\n"
    "  bday help — Show this message\n\n"
    "*Surf Report*\n"
    "  surf — Today's surf conditions at Oostende\n"
    "  surf week — 5-day surf forecast"
)


def send_message(chat_id: str, text: str) -> None:
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


def handle_command(chat_id: str, text: str) -> None:
    parts = text.strip().split()
    if len(parts) < 2 or parts[0].lower() != "bday":
        return

    cmd = parts[1].lower()

    if cmd == "help":
        send_message(chat_id, HELP_TEXT)

    elif cmd == "add":
        if len(parts) < 4:
            send_message(chat_id, "Usage: bday add <name> <DD-MM>\nExample: bday add John 15-03")
            return
        name = parts[2]
        date_str = parts[3]
        try:
            day_str, month_str = date_str.split("-")
            day, month = int(day_str), int(month_str)
            if not (1 <= day <= 31 and 1 <= month <= 12):
                raise ValueError
        except ValueError:
            send_message(chat_id, "Invalid date. Use DD-MM format, e.g. 15-03")
            return
        if add_birthday(name, day, month):
            send_message(chat_id, f"Birthday added for {name} on {format_date(day, month)}.")
        else:
            send_message(chat_id, f"A birthday for {name} already exists. Remove it first.")

    elif cmd == "list":
        birthdays = load_birthdays()
        if not birthdays:
            send_message(chat_id, "No birthdays saved yet.")
            return
        sorted_bdays = sorted(birthdays, key=lambda b: (b["month"], b["day"]))
        lines = [f"  {b['name']}: {format_date(b['day'], b['month'])}" for b in sorted_bdays]
        send_message(chat_id, "Birthdays:\n" + "\n".join(lines))

    elif cmd == "remove":
        if len(parts) < 3:
            send_message(chat_id, "Usage: bday remove <name>")
            return
        name = parts[2]
        if delete_birthday(name):
            send_message(chat_id, f"Birthday for {name} removed.")
        else:
            send_message(chat_id, f"No birthday found for {name}.")


def handle_surf_command(chat_id: str, parts: list[str]) -> None:
    days_data = fetch_weekly_surf_slots(date.today(), days=5)
    if days_data is None:
        send_message(chat_id, "Could not fetch weekly forecast. Try again later.")
    else:
        high_tides = fetch_high_tides_range(date.today(), days=5)
        sg_key = os.environ.get("STORMGLASS_API_KEY", "")
        sg_today = fetch_stormglass_today(sg_key) if sg_key else None
        vc_key = os.environ.get("VISUALCROSSING_API_KEY", "")
        vc_data = fetch_visualcrossing(vc_key) if vc_key else None
        send_message(chat_id, format_weekly_surf_report(days_data, high_tides, sg_today=sg_today, vc_data=vc_data))


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "ignored"}), 200

    if data.get("event") != "message.any":
        return jsonify({"status": "ignored"}), 200

    payload = data.get("payload", {})
    to_field = payload.get("to", "")
    from_field = payload.get("from", "")
    # Group messages: 'to' is the group JID; DMs: 'from' is the sender
    chat_id = to_field if to_field.endswith("@g.us") else from_field
    text = payload.get("body", "").strip()
    logger.info("Webhook: event=%s chat_id=%s text=%r", data.get("event"), chat_id, text)

    owner_id = os.environ.get("REMINDER_CHAT_ID", "")
    surf_group_id = os.environ.get("SURF_GROUP_CHAT_ID", "")

    is_owner = chat_id == owner_id
    is_surf_group = bool(surf_group_id) and chat_id == surf_group_id

    if not is_owner and not is_surf_group:
        logger.info("Ignored: from=%s", chat_id)
        return jsonify({"status": "ignored"}), 200

    if not text:
        return jsonify({"status": "ignored"}), 200

    parts = text.strip().split()
    keyword = parts[0].lower()

    if is_surf_group:
        if keyword == "surf":
            handle_surf_command(chat_id, parts)
    elif is_owner:
        if keyword == "bday":
            handle_command(chat_id, text)
        elif keyword == "surf":
            handle_surf_command(chat_id, parts)

    return jsonify({"status": "ok"}), 200


def start_waha_session() -> None:
    waha_base = os.environ["WAHA_BASE_URL"]
    session = os.environ["WAHA_SESSION"]
    api_key = os.environ.get("WAHA_API_KEY", "")
    headers = {"X-Api-Key": api_key}
    try:
        status_resp = requests.get(
            f"{waha_base}/api/sessions/{session}",
            headers=headers,
            timeout=10,
        )
        if status_resp.status_code == 200:
            status = status_resp.json().get("status", "")
            if status in ("WORKING", "STARTING"):
                logger.info("WAHA session '%s' already %s.", session, status)
                return
        resp = requests.post(
            f"{waha_base}/api/sessions/{session}/start",
            headers=headers,
            timeout=10,
        )
        if resp.status_code == 201:
            logger.info("WAHA session '%s' started.", session)
        else:
            logger.warning("WAHA session start returned %s", resp.status_code)
    except requests.RequestException as e:
        logger.error("Could not start WAHA session: %s", e)


if __name__ == "__main__":
    host = os.environ.get("WEBHOOK_HOST", "0.0.0.0")
    port = int(os.environ.get("WEBHOOK_PORT", 5000))
    reminder_time = os.environ.get("REMINDER_TIME", "09:00")

    start_waha_session()
    scheduler = start_scheduler(reminder_time)
    try:
        app.run(host=host, port=port)
    finally:
        scheduler.shutdown()
