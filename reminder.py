"""
reminder.py - Parse reminders from sentences, store them in reminders.json and
fire a callback when they are due (a background thread checks every second).

Understood time phrases:  "in 10 minutes", "in an hour", "in half an hour",
"at 5 pm", "at 17:30", "tomorrow at 9 am", "today at 6:15 pm".
"""

import json
import re
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "fifteen": 15, "twenty": 20,
    "thirty": 30, "forty five": 45, "forty": 40, "fifty": 50, "sixty": 60,
    "half a": 0.5, "half an": 0.5,
}
_NUM_ALT = "|".join(sorted((re.escape(w) for w in _NUMBER_WORDS), key=len, reverse=True))

_RELATIVE = re.compile(
    rf"\bin\s+(?P<num>\d+(?:\.\d+)?|{_NUM_ALT})\s*"
    r"(?P<unit>seconds?|secs?|minutes?|mins?|hours?|hrs?|days?)\b"
)
_ABSOLUTE = re.compile(
    r"\b(?:(?P<day>today|tomorrow)\s+)?at\s+(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>am|pm)?\b"
)


@dataclass
class Reminder:
    id: int
    task: str
    due: str  # ISO format, e.g. 2026-11-02T17:30:00


@dataclass
class ParsedReminder:
    task: str
    due: object  # datetime or None


def _clean(text):
    text = text.lower().strip()
    return re.sub(r"\b([ap])\.\s?m\.?", r"\1m", text)  # "p.m." -> "pm"


def _find_time(text, now):
    """Return (due_datetime, (start, end)) or (None, None)."""
    match = _RELATIVE.search(text)
    if match:
        raw = match.group("num")
        amount = float(raw) if raw[0].isdigit() else float(_NUMBER_WORDS[raw])
        unit = match.group("unit")[0]  # s, m, h, d
        seconds = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit] * amount
        return now + timedelta(seconds=seconds), match.span()

    match = _ABSOLUTE.search(text)
    if match:
        hour = int(match.group("h"))
        minute = int(match.group("m") or 0)
        ap = match.group("ap")
        day = match.group("day")
        if minute > 59 or hour > 23 or (ap and hour > 12) or (ap and hour == 0):
            return None, None
        if ap == "pm" and hour < 12:
            hour += 12
        elif ap == "am" and hour == 12:
            hour = 0

        if day == "tomorrow":
            base = (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)
            return base, match.span()

        candidates = [hour]
        if not ap and hour <= 12:  # "at 5" could mean 5 am or 5 pm
            candidates = [hour % 12, hour % 12 + 12]
        for h in sorted(set(candidates)):
            due = now.replace(hour=h, minute=minute, second=0, microsecond=0)
            if due > now:
                return due, match.span()
        due = now.replace(hour=sorted(set(candidates))[0], minute=minute, second=0, microsecond=0)
        return due + timedelta(days=1), match.span()
    return None, None


def parse_time(text, now=None):
    """Return a datetime found in `text`, or None."""
    now = now or datetime.now()
    due, _ = _find_time(_clean(text), now)
    return due


def parse_reminder(text, now=None):
    """Split a sentence into the task and the due time (either may be missing)."""
    now = now or datetime.now()
    t = _clean(text)
    due, span = _find_time(t, now)
    if span:
        t = t[:span[0]] + " " + t[span[1]:]
    t = re.sub(
        r"^\s*(?:please\s+)?(?:can you\s+|could you\s+)?"
        r"(?:(?:set|add|create)\s+(?:a\s+)?reminder|remind\s+me)\s*(?:to|for|about|that)?\s*",
        "", t)
    t = re.sub(r"\s+", " ", t).strip(" ,.")
    t = re.sub(r"\s+(?:in|at|on|by|please)$", "", t).strip(" ,.")
    return ParsedReminder(task=t, due=due)


def describe_due(due, now=None):
    now = now or datetime.now()
    clock = due.strftime("%I:%M %p").lstrip("0")
    if due.date() == now.date():
        return f"today at {clock}"
    if due.date() == (now + timedelta(days=1)).date():
        return f"tomorrow at {clock}"
    return f"on {due.strftime('%A, %d %B')} at {clock}"


class ReminderManager:
    def __init__(self, path, on_due=None, check_interval=1.0):
        self.path = Path(path)
        self.on_due = on_due
        self.check_interval = check_interval
        self._items = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._load()

    # --- storage
    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._items = [Reminder(**item) for item in data]
        except FileNotFoundError:
            self._items = []
        except (OSError, ValueError, TypeError) as exc:
            print(f"[reminder] Could not read {self.path}: {exc}. Starting empty.")
            self._items = []

    def _save(self):
        try:
            self.path.write_text(
                json.dumps([asdict(i) for i in self._items], indent=2), encoding="utf-8")
        except OSError as exc:
            print(f"[reminder] Could not save reminders: {exc}")

    # --- public API
    def add(self, task, due):
        with self._lock:
            next_id = max((i.id for i in self._items), default=0) + 1
            item = Reminder(id=next_id, task=task, due=due.isoformat(timespec="seconds"))
            self._items.append(item)
            self._save()
            return item

    def pending(self):
        with self._lock:
            return sorted(self._items, key=lambda i: i.due)

    def clear(self):
        with self._lock:
            count = len(self._items)
            self._items = []
            self._save()
            return count

    # --- background checking
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.wait(self.check_interval):
            due_now = []
            with self._lock:
                now = datetime.now()
                still_waiting = []
                for item in self._items:
                    if datetime.fromisoformat(item.due) <= now:
                        due_now.append(item)
                    else:
                        still_waiting.append(item)
                if due_now:
                    self._items = still_waiting
                    self._save()
            for item in due_now:
                if self.on_due:
                    try:
                        self.on_due(item)
                    except Exception as exc:  # noqa: BLE001
                        print(f"[reminder] callback failed: {exc}")
