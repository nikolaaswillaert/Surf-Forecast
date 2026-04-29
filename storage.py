import json
from datetime import date
from pathlib import Path

BIRTHDAYS_FILE = Path(__file__).parent / "birthdays.json"


def load_birthdays() -> list[dict]:
    if not BIRTHDAYS_FILE.exists():
        return []
    with open(BIRTHDAYS_FILE) as f:
        return json.load(f)


def save_birthdays(birthdays: list[dict]) -> None:
    with open(BIRTHDAYS_FILE, "w") as f:
        json.dump(birthdays, f, indent=2)


def add_birthday(name: str, day: int, month: int) -> bool:
    """Add a birthday. Returns False if the name already exists."""
    birthdays = load_birthdays()
    if any(b["name"].lower() == name.lower() for b in birthdays):
        return False
    birthdays.append({"name": name, "day": day, "month": month})
    save_birthdays(birthdays)
    return True


def delete_birthday(name: str) -> bool:
    """Delete a birthday by name. Returns False if not found."""
    birthdays = load_birthdays()
    filtered = [b for b in birthdays if b["name"].lower() != name.lower()]
    if len(filtered) == len(birthdays):
        return False
    save_birthdays(filtered)
    return True


def get_todays_birthdays() -> list[dict]:
    today = date.today()
    return [
        b for b in load_birthdays()
        if b["day"] == today.day and b["month"] == today.month
    ]
