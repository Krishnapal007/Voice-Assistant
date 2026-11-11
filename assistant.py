"""
assistant.py - The "brain". It receives text, finds the intent, runs the right
feature and answers (speaking + showing the text).

It can ask follow-up questions (for emails, reminders...). Answers come from the
microphone OR from the text box of the GUI, whichever happens first.
"""

import os
import queue
import re
import threading
import time
from pathlib import Path

import email_service
import weather
from commands import BasicCommands, CustomCommands, normalise_app, normalise_url
from nlp_engine import (IntentDetector, KnowledgeBase, extract_search_query,
                        extract_youtube_query)
from reminder import ReminderManager, describe_due, parse_reminder, parse_time
from voice_engine import MicrophoneError, SpeechServiceError, VoiceError

BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR / "config"

YES_WORDS = {"yes", "yeah", "yep", "yup", "sure", "ok", "okay", "send", "confirm",
             "correct", "affirmative", "please"}
NO_WORDS = {"no", "nope", "nah", "cancel", "stop", "don't", "dont", "never"}


class Assistant:
    def __init__(self, voice, on_user=None, on_assistant=None, on_notify=None,
                 on_exit=None, input_provider=None):
        """
        voice          : a VoiceEngine
        on_user        : function(text)   called when the user said/typed something
        on_assistant   : function(text)   called when the assistant answers
        on_notify      : function(title, message) called when a reminder is due
        on_exit        : function()       called after the user says goodbye
        input_provider : function() -> str  (console mode) used for follow-up answers
        """
        self.voice = voice
        self.on_user = on_user
        self.on_assistant = on_assistant
        self.on_notify = on_notify
        self.on_exit = on_exit
        self.input_provider = input_provider

        self.name = os.getenv("ASSISTANT_NAME", "Nova").strip() or "Nova"
        self.nlp = IntentDetector()
        self.knowledge = KnowledgeBase(CONFIG_DIR / "knowledge.json")
        self.basic = BasicCommands(self.name)
        self.custom = CustomCommands(CONFIG_DIR / "commands.json")
        self.reminders = ReminderManager(BASE_DIR / "reminders.json", on_due=self._on_reminder_due)

        self.exit_requested = False
        self._lock = threading.RLock()
        self._typed = queue.Queue()
        self._awaiting = threading.Event()

        self._handlers = {
            "greeting": self._do_greeting, "time": self._do_time, "date": self._do_date,
            "open_google": self._do_open_google,
            "open_youtube": self._do_open_youtube, "search": self._do_search,
            "youtube_search": self._do_youtube_search, "email": self._do_email,
            "reminder_set": self._do_reminder_set, "reminder_list": self._do_reminder_list,
            "reminder_clear": self._do_reminder_clear, "add_command": self._do_add_command,
            "list_commands": self._do_list_commands, "help": self._do_help,
            "knowledge": self._do_knowledge, "weather": self._do_weather, "exit": self._do_exit,
        }

    # ------------------------------------------------------------ life cycle
    def start(self):
        self.reminders.start()

    def stop(self):
        self.reminders.stop()
        self.voice.shutdown()

    def startup(self):
        """Greet the user and report the microphone status."""
        ok, message = self.voice.check_microphone()
        self.respond(self.basic.greeting())
        if not ok:
            self._emit_assistant("Microphone problem: " + message)
            self.voice.speak("I have a microphone problem. You can still type commands.")

    # ------------------------------------------------------------ output helpers
    def _emit_user(self, text):
        if self.on_user:
            self.on_user(text)

    def _emit_assistant(self, text):
        if self.on_assistant:
            self.on_assistant(text)
        else:
            print(f"{self.name}: {text}")

    def respond(self, text):
        self._emit_assistant(text)
        self.voice.speak(text)

    # ------------------------------------------------------------ input handling
    def submit_text(self, text):
        """
        Called by the GUI for typed text. If the assistant is waiting for an
        answer to a question, the text becomes that answer and True is returned.
        """
        text = text.strip()
        if text and self._awaiting.is_set():
            self._emit_user(text)
            self._typed.put(text)
            return True
        return False

    def ask(self, prompt, wait_seconds=25):
        """Ask a question and return the answer (spoken or typed), or None."""
        self.respond(prompt)
        if self.input_provider:
            answer = (self.input_provider() or "").strip()
            return answer or None

        self._awaiting.set()
        try:
            end = time.time() + wait_seconds
            while time.time() < end:
                try:
                    return self._typed.get_nowait()
                except queue.Empty:
                    pass
                try:
                    heard = self.voice.listen(timeout=2, phrase_time_limit=15)
                except VoiceError:
                    time.sleep(0.3)
                    continue
                if heard:
                    self._emit_user(heard)
                    return heard
            return None
        finally:
            self._awaiting.clear()
            while not self._typed.empty():
                self._typed.get_nowait()

    def confirm(self, prompt):
        """Ask a yes/no question. Anything unclear counts as NO (safe default)."""
        for attempt in range(2):
            reply = self.ask(prompt if attempt == 0 else "Please say yes or no.")
            if not reply:
                continue
            words = set(re.findall(r"[a-z']+", reply.lower()))
            if words & NO_WORDS:
                return False
            if words & YES_WORDS:
                return True
        return False

    # ------------------------------------------------------------ main entry point
    def process(self, text):
        text = (text or "").strip()
        if not text:
            return
        with self._lock:
            self._emit_user_once(text)
            try:
                self._route(text)
            except Exception as exc:  # noqa: BLE001 - last safety net
                print(f"[assistant] Unexpected error: {exc!r}")
                self.respond("Sorry, something went wrong while doing that. Please try again.")

    def _emit_user_once(self, text):
        # Typed answers are already shown by submit_text; commands are shown here.
        self._emit_user(text)

    def _route(self, text):
        custom = self.custom.find(text)
        if custom:
            self.respond(self.custom.run(custom))
            return
        intent = self.nlp.detect(text)
        handler = self._handlers.get(intent.name)
        if handler:
            handler(text)
        else:
            self.respond("Sorry, I did not understand that. Say help to hear what I can do.")

    # ------------------------------------------------------------ simple intents
    def _do_greeting(self, text):
        self.respond(self.basic.greeting())

    def _do_time(self, text):
        self.respond(self.basic.current_time())

    def _do_date(self, text):
        self.respond(self.basic.current_date())

    def _do_open_google(self, text):
        self.respond(self.basic.open_google())

    def _do_open_youtube(self, text):
        self.respond(self.basic.open_youtube())

    def _do_help(self, text):
        self.respond(self.basic.help_text())

    def _do_exit(self, text):
        self.respond("Goodbye! Have a great day.")
        self.exit_requested = True
        if self.on_exit:
            self.on_exit()

    def _do_search(self, text):
        query = extract_search_query(text) or self.ask("What should I search for?")
        if not query:
            self.respond("I did not hear a search topic, so I cancelled the search.")
            return
        self.respond(self.basic.search_google(query))

    def _do_youtube_search(self, text):
        query = extract_youtube_query(text) or self.ask("What should I look for on YouTube?")
        if not query:
            self.respond("I did not hear a topic, so I cancelled.")
            return
        self.respond(self.basic.search_youtube(query))

    def _do_knowledge(self, text):
        answer = self.knowledge.answer(text)
        if answer:
            self.respond(answer)
            return
        self.respond("I do not have that in my notes, so I will search Google for you.")
        self.respond(self.basic.search_google(text))

    # ------------------------------------------------------------ email
    def _ask_recipient(self):
        for _ in range(2):
            reply = self.ask("Who should I send it to? Say a contact name, or type the email address.")
            if not reply:
                return None
            address = email_service.resolve_recipient(reply)
            if address:
                return address
            self.respond("I could not understand that email address. Let us try again.")
        return None

    def _do_email(self, text):
        if not email_service.is_configured():
            self.respond("Email is not set up yet. Please add EMAIL_ADDRESS and "
                         "EMAIL_APP_PASSWORD to the .env file.")
            return
        to_address = self._ask_recipient()
        if not to_address:
            self.respond("Email cancelled.")
            return
        subject = self.ask("What is the subject?")
        if not subject:
            self.respond("Email cancelled.")
            return
        body = self.ask("What should the message say?")
        if not body:
            self.respond("Email cancelled.")
            return
        subject, body = subject[0].upper() + subject[1:], body[0].upper() + body[1:]

        summary = (f"I will send an email to {to_address}. The subject is {subject}. "
                   f"The message says: {body}. Shall I send it?")
        if not self.confirm(summary):
            self.respond("Okay, I did not send the email.")
            return
        self.respond("Sending your email.")
        try:
            email_service.send_email(to_address, subject, body)
            self.respond("Your email was sent successfully.")
        except email_service.EmailError as exc:
            self.respond(str(exc))

    # ------------------------------------------------------------ reminders
    def _do_reminder_set(self, text):
        parsed = parse_reminder(text)
        task, due = parsed.task, parsed.due
        if due is None:
            reply = self.ask("When should I remind you? For example: in 10 minutes, or at 6 pm.")
            due = parse_time(reply) if reply else None
            if due is None:
                self.respond("I could not understand the time, so I did not set the reminder.")
                return
        if not task:
            task = self.ask("What should I remind you about?")
            if not task:
                self.respond("I did not hear the reminder text, so I cancelled it.")
                return
        self.reminders.add(task, due)
        self.respond(f"Okay, I will remind you to {task} {describe_due(due)}.")

    def _do_reminder_list(self, text):
        items = self.reminders.pending()
        if not items:
            self.respond("You have no pending reminders.")
            return
        from datetime import datetime
        parts = [f"{i.task}, {describe_due(datetime.fromisoformat(i.due))}" for i in items]
        plural = "reminder" if len(items) == 1 else "reminders"
        self.respond(f"You have {len(items)} {plural}. " + ". ".join(parts) + ".")

    def _do_reminder_clear(self, text):
        count = self.reminders.clear()
        self.respond(f"Deleted {count} reminder{'s' if count != 1 else ''}.")

    def _on_reminder_due(self, reminder):
        message = f"Reminder: {reminder.task}"
        self._emit_assistant(message)
        if self.on_notify:
            try:
                self.on_notify("Reminder", reminder.task)
            except Exception as exc:  # noqa: BLE001
                print(f"[assistant] notify failed: {exc}")
        self.voice.speak(f"Reminder. {reminder.task}")

    # ------------------------------------------------------------ custom commands
    def _do_add_command(self, text):
        trigger = self.ask("What phrase should trigger the new command?")
        if not trigger:
            self.respond("Cancelled.")
            return
        kind_reply = self.ask("Should it open a website, open an app, or reply with a message? "
                              "Say website, app, or message.")
        if not kind_reply:
            self.respond("Cancelled.")
            return
        words = kind_reply.lower()
        kind = "website" if "web" in words else "app" if "app" in words else \
            "say" if "mess" in words or "reply" in words else None
        if not kind:
            self.respond("I did not understand the type, so I cancelled.")
            return
        prompts = {"website": "Which website address? For example, github dot com.",
                   "app": "Which app? For example, notepad or calc. You can also type a full path.",
                   "say": "What should I reply with?"}
        target = self.ask(prompts[kind])
        if not target:
            self.respond("Cancelled.")
            return
        try:
            if kind == "website":
                target = normalise_url(target)
            elif kind == "app":
                target = normalise_app(target)
            self.custom.add(trigger, kind, target, "" if kind == "say" else "Done.")
        except ValueError as exc:
            self.respond(f"I could not save that command. {exc}")
            return
        self.respond(f"Saved. When you say {trigger}, I will do it.")

    def _do_list_commands(self, text):
        triggers = [c["trigger"] for c in self.custom.commands if c.get("trigger")]
        if not triggers:
            self.respond("You have no custom commands yet. Say add a new command to create one.")
        else:
            self.respond("Your custom commands are: " + ", ".join(triggers) + ".")

    # ------------------------------------------------------------ continuous listening
    def listen_loop(self, stop_event, on_status=None):
        """Keep listening until stop_event is set. Used by the GUI's Start button."""
        def status(text):
            if on_status:
                on_status(text)

        ok, message = self.voice.check_microphone()
        if not ok:
            self._emit_assistant("Microphone problem: " + message)
            return
        while not stop_event.is_set() and not self.exit_requested:
            try:
                status("Listening")
                heard = self.voice.listen(timeout=3, phrase_time_limit=12)
            except MicrophoneError as exc:
                self._emit_assistant(str(exc))
                break
            except SpeechServiceError as exc:
                self._emit_assistant(str(exc))
                stop_event.wait(5)
                continue
            if not heard or stop_event.is_set():
                continue
            status("Processing")
            self.process(heard)
        status("Idle")


    def _do_weather(self, text):
        """Fetch live weather for a city using OpenWeatherMap."""
        match = re.search(
            r"\b(?:weather|temperature|forecast)\b(?:\s+(?:in|for|at))?\s+(.+)$",
            text, re.IGNORECASE
        )
        city = match.group(1).strip(" ?.!") if match else None
        if not city:
            city = self.ask("Which city should I check the weather for?")
        if not city:
            self.respond("I did not get a city name, so I cancelled the weather request.")
            return
        try:
            self.respond(weather.get_current_weather(city))
        except weather.WeatherError as exc:
            self.respond(str(exc))
