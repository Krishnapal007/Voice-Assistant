"""Offline tests. Run from the project folder:  python -m unittest discover tests -v"""
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import email_service
from commands import CustomCommands, normalise_url
from nlp_engine import (IntentDetector, KnowledgeBase, extract_search_query,
                        extract_youtube_query)
from reminder import ReminderManager, parse_reminder, parse_time

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 11, 3, 14, 0, 0)


class IntentTests(unittest.TestCase):
    def setUp(self):
        self.d = IntentDetector()

    def check(self, text, expected):
        self.assertEqual(self.d.detect(text).name, expected, text)

    def test_intents(self):
        for text, expected in [
            ("hello there", "greeting"), ("good morning", "greeting"),
            ("what time is it", "time"), ("what's the time", "time"),
            ("what is the date today", "date"), ("open google", "open_google"),
            ("open YouTube", "open_youtube"), ("search google for python", "search"),
            ("play despacito on youtube", "youtube_search"), ("send an email", "email"),
            ("remind me to drink water in 10 minutes", "reminder_set"),
            ("show my reminders", "reminder_list"), ("delete all reminders", "reminder_clear"),
            ("add a new command", "add_command"), ("what is python", "knowledge"),
            ("who are you", "knowledge"), ("goodbye", "exit"), ("help", "help"),
            ("blah blah xyz", "unknown"),
        ]:
            self.check(text, expected)

    def test_entities(self):
        self.assertEqual(extract_search_query("search google for python tutorials"), "python tutorials")
        self.assertEqual(extract_search_query("search for machine learning on google"), "machine learning")
        self.assertEqual(extract_youtube_query("play despacito on youtube"), "despacito")


class KnowledgeTests(unittest.TestCase):
    def test_answers(self):
        kb = KnowledgeBase(ROOT / "config" / "knowledge.json")
        self.assertIn("Guido", kb.answer("who created python"))
        self.assertIn("Paris", kb.answer("what is the capital of France?"))
        self.assertIn("365", kb.answer("how many days in a year"))
        self.assertIn("Nova", kb.answer("what's your name"))
        self.assertIsNone(kb.answer("what is the meaning of the zebra crossing law"))


class ReminderTests(unittest.TestCase):
    def test_relative(self):
        p = parse_reminder("remind me to drink water in 10 minutes", NOW)
        self.assertEqual(p.task, "drink water")
        self.assertEqual(p.due, datetime(2026, 11, 3, 14, 10))
        self.assertEqual(parse_time("in an hour", NOW), datetime(2026, 11, 3, 15, 0))
        self.assertEqual(parse_time("in half an hour", NOW), datetime(2026, 11, 3, 14, 30))

    def test_absolute(self):
        p = parse_reminder("set a reminder to call mom at 5:30 p.m.", NOW)
        self.assertEqual(p.task, "call mom")
        self.assertEqual(p.due, datetime(2026, 11, 3, 17, 30))
        self.assertEqual(parse_time("tomorrow at 9 am", NOW), datetime(2026, 11, 4, 9, 0))
        self.assertEqual(parse_time("at 1:15", NOW), datetime(2026, 11, 4, 1, 15))
        self.assertEqual(parse_time("at 3", NOW), datetime(2026, 11, 3, 15, 0))

    def test_missing_parts(self):
        self.assertIsNone(parse_reminder("remind me to buy milk", NOW).due)
        self.assertEqual(parse_reminder("remind me in 5 minutes", NOW).task, "")

    def test_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.json"
            fired = []
            m = ReminderManager(path, on_due=fired.append, check_interval=0.1)
            m.add("past task", datetime(2020, 1, 1))
            m.add("future task", datetime(2999, 1, 1))
            m.start()
            import time; time.sleep(0.6); m.stop()
            self.assertEqual([r.task for r in fired], ["past task"])
            self.assertEqual([r.task for r in ReminderManager(path).pending()], ["future task"])


class CommandTests(unittest.TestCase):
    def test_custom(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            path.write_text(Path(ROOT / "config" / "commands.json").read_text())
            c = CustomCommands(path)
            self.assertEqual(c.find("please open notepad")["target"], "notepad.exe")
            self.assertIsNone(c.find("what time is it"))
            c.add("Open Docs", "website", normalise_url("docs dot python dot org"), "Done.")
            self.assertEqual(CustomCommands(path).find("open docs")["target"], "https://docs.python.org")
            self.assertIn("dark mode", c.run(c.find("tell me a joke")))


class EmailTests(unittest.TestCase):
    def test_resolve(self):
        self.assertEqual(email_service.resolve_recipient("john dot smith at gmail dot com", {}), "john.smith@gmail.com")
        self.assertEqual(email_service.resolve_recipient("Mom", {"mom": "mom@example.com"}), "mom@example.com")
        self.assertIsNone(email_service.resolve_recipient("hello world", {}))

    def test_not_configured(self):
        with mock.patch.dict(os.environ, {"EMAIL_ADDRESS": "", "EMAIL_APP_PASSWORD": ""}):
            with self.assertRaises(email_service.EmailError):
                email_service.send_email("a@b.com", "s", "b")

    @mock.patch("email_service.smtplib.SMTP")
    def test_send(self, smtp):
        env = {"EMAIL_ADDRESS": "me@x.com", "EMAIL_APP_PASSWORD": "abcd efgh", "SMTP_PORT": "587"}
        with mock.patch.dict(os.environ, env):
            email_service.send_email("you@y.com", "Hi", "Body")
        inst = smtp.return_value.__enter__.return_value
        inst.login.assert_called_with("me@x.com", "abcdefgh")
        inst.send_message.assert_called_once()


class FakeVoice:
    def __init__(self, answers=()):
        self.spoken, self.answers = [], list(answers)
    def speak(self, text, wait=True): self.spoken.append(text)
    def listen(self, **kw): return self.answers.pop(0) if self.answers else None
    def check_microphone(self): return True, "ok"
    def shutdown(self): pass


class AssistantFlowTests(unittest.TestCase):
    def make(self, answers):
        import assistant as a
        voice = FakeVoice()
        it = iter(answers)
        asst = a.Assistant(voice, on_assistant=lambda t: None, input_provider=lambda: next(it, ""))
        asst.reminders = ReminderManager(Path(tempfile.mkdtemp()) / "r.json")
        return asst, voice

    def test_email_confirm_yes_and_no(self):
        env = {"EMAIL_ADDRESS": "me@x.com", "EMAIL_APP_PASSWORD": "pw"}
        with mock.patch.dict(os.environ, env), mock.patch("email_service.send_email") as send:
            asst, _ = self.make(["bob at example dot com", "hello", "see you soon", "yes"])
            asst.process("send an email")
            send.assert_called_once_with("bob@example.com", "Hello", "See you soon")
            send.reset_mock()
            asst, _ = self.make(["bob at example dot com", "hello", "see you soon", "no"])
            asst.process("send an email")
            send.assert_not_called()

    def test_reminder_and_unknown_and_time(self):
        asst, voice = self.make(["when", ""])
        asst.process("remind me to stretch in 5 minutes")
        self.assertEqual(len(asst.reminders.pending()), 1)
        asst.process("blah blah xyz")
        asst.process("what time is it")
        self.assertTrue(any("did not understand" in s for s in voice.spoken))
        self.assertTrue(any(s.startswith("The time is") for s in voice.spoken))


if __name__ == "__main__":
    unittest.main()
