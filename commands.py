"""
commands.py - Simple built-in commands and user-defined custom commands.

Custom commands live in config/commands.json. Each one has:
  trigger : the phrase you say           type : website | app | say
  target  : URL, program name or text    response : what the assistant says
"""

import difflib
import json
import os
import re
import subprocess
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus


class BasicCommands:
    def __init__(self, name="Nova"):
        self.name = name

    def greeting(self):
        hour = datetime.now().hour
        if hour < 12:
            part = "Good morning"
        elif hour < 17:
            part = "Good afternoon"
        else:
            part = "Good evening"
        return f"{part}! I am {self.name}, your voice assistant. How can I help you?"

    def current_time(self):
        return "The time is " + datetime.now().strftime("%I:%M %p").lstrip("0") + "."

    def current_date(self):
        return "Today is " + datetime.now().strftime("%A, %d %B %Y") + "."

    @staticmethod
    def _open(url, success):
        try:
            if webbrowser.open(url):
                return success
        except webbrowser.Error:
            pass
        return "Sorry, I could not open your web browser."

    def open_google(self):
        return self._open("https://www.google.com", "Opening Google.")

    def open_youtube(self):
        return self._open("https://www.youtube.com", "Opening YouTube.")

    def search_google(self, query):
        url = "https://www.google.com/search?q=" + quote_plus(query)
        return self._open(url, f"Here are the Google results for {query}.")

    def search_youtube(self, query):
        url = "https://www.youtube.com/results?search_query=" + quote_plus(query)
        return self._open(url, f"Here are the YouTube results for {query}.")

    def help_text(self):
        return (
            "I can tell the time and date, open Google or YouTube, search the web, "
            "send emails after asking you to confirm, set reminders, "
            "answer common questions, and learn custom commands. "
            "Try saying: what time is it, or remind me to drink water in 10 minutes."
        )


def normalise_url(spoken):
    """'github dot com' -> 'https://github.com'"""
    text = re.sub(r"\s+dot\s+", ".", spoken.strip().lower()).replace(" ", "")
    if not text.startswith(("http://", "https://")):
        text = "https://" + text
    if "." not in text:
        raise ValueError("That does not look like a website address.")
    return text


def normalise_app(spoken):
    """'notepad' -> 'notepad.exe' (full paths and names with extensions are kept)."""
    text = spoken.strip().strip('"')
    if not re.search(r"[\\/.]", text):
        text = text.lower().replace(" ", "") + ".exe"
    return text


class CustomCommands:
    def __init__(self, path):
        self.path = Path(path)
        self.commands = []
        self.load()

    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.commands = data.get("custom_commands", [])
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[commands] Could not load {self.path}: {exc}")
            self.commands = []

    def save(self):
        self.path.write_text(
            json.dumps({"custom_commands": self.commands}, indent=2), encoding="utf-8")

    def find(self, text):
        """Return the best matching command for `text`, or None."""
        text = re.sub(r"[^\w\s]", " ", text.lower())
        text = re.sub(r"\s+", " ", text).strip()
        best, best_len = None, 0
        for cmd in self.commands:
            trigger = cmd.get("trigger", "").lower().strip()
            if not trigger:
                continue
            if re.search(rf"\b{re.escape(trigger)}\b", text) and len(trigger) > best_len:
                best, best_len = cmd, len(trigger)
            elif difflib.SequenceMatcher(None, trigger, text).ratio() >= 0.88 and len(trigger) > best_len:
                best, best_len = cmd, len(trigger)
        return best

    def add(self, trigger, kind, target, response=""):
        trigger = re.sub(r"[^\w\s]", " ", trigger.lower())
        trigger = re.sub(r"\s+", " ", trigger).strip()
        if len(trigger) < 2:
            raise ValueError("The trigger phrase is too short.")
        if kind not in {"website", "app", "say"}:
            raise ValueError("Type must be website, app or say.")
        self.commands = [c for c in self.commands if c.get("trigger") != trigger]  # replace old
        self.commands.append(
            {"trigger": trigger, "type": kind, "target": target, "response": response})
        self.save()

    def run(self, cmd):
        """Perform the command and return the sentence to say."""
        kind, target = cmd.get("type"), cmd.get("target", "")
        response = cmd.get("response") or ""
        try:
            if kind == "website":
                if not webbrowser.open(target):
                    return "Sorry, I could not open your web browser."
                return response or "Opening the website."
            if kind == "app":
                if hasattr(os, "startfile"):  # Windows
                    os.startfile(target)  # noqa: S606
                else:
                    subprocess.Popen([target])  # noqa: S603
                return response or "Opening the application."
            if kind == "say":
                return response or target
        except (OSError, ValueError) as exc:
            return f"Sorry, I could not run that command: {exc}"
        return "That custom command has an unknown type."
