# Python Voice Assistant

A modular, working voice assistant for Windows 10 built with Python 3.11 for the Oasis Infobyte Python Programming Internship. It listens through the microphone, answers out loud, and has a Tkinter dashboard.

## Features
**Basic:** voice input, speech-to-text, spoken replies, time-based greeting, date and time, open Google/YouTube, Google search, friendly handling of unknown commands.

**Advanced:** email via SMTP **with spoken/typed confirmation**, reminders with notifications, custom voice commands, offline knowledge base, rule-based NLP intent detection (with spelling correction), Tkinter GUI with Start/Stop buttons and conversation log, microphone checks and error handling.

## Project structure
```
main.py            entry point (GUI or --cli)
assistant.py       the brain: routes intents, asks follow-up questions
voice_engine.py    speech recognition + text-to-speech
nlp_engine.py      intent detection, entity extraction, knowledge base
commands.py        built-in and custom commands
email_service.py   SMTP email sender
reminder.py        reminder parsing, storage, background checker
gui.py             Tkinter dashboard
config/commands.json   custom commands (editable)
config/knowledge.json  offline Q&A (editable)
config/contacts.json   email contacts, e.g. {"mom": "mom@example.com"}
tests/test_core.py     offline unit tests
```

## Installation (Windows 10)
1. Install **Python 3.11** from python.org (tick *Add python.exe to PATH*).
2. Open CMD in the project folder and run:
```cmd
python -m venv venv
venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env
notepad .env
```
(Or just double-click `setup.bat`.)

**PyAudio fails to install?** Make sure you use Python 3.11 (64-bit) and an updated pip; wheels are available for it. If it still fails: `pip install pipwin` then `pipwin install pyaudio`.

## Configure `.env`
| Variable | How to get it |
|---|---|
| `EMAIL_ADDRESS` | Your email |
| `EMAIL_APP_PASSWORD` | Gmail: enable 2-Step Verification, then Google Account -> Security -> App passwords. **Not** your normal password |
| `SMTP_SERVER` / `SMTP_PORT` | `smtp.gmail.com` / `587` (465 also works) |

`.env` is listed in `.gitignore`, so your secrets are never uploaded.

## Run
```cmd
venv\Scripts\activate
python main.py          :: GUI
python main.py --cli    :: console mode (typed commands, spoken replies)
```
Click **Start Listening** and speak. You can also type in the box. Allow microphone access in *Windows Settings -> Privacy -> Microphone* (including "desktop apps").

## Example commands
| Say | What happens |
|---|---|
| "Hello" | Greeting for the time of day |
| "What time is it?" / "What's the date?" | Current time / date |
| "Open Google" / "Open YouTube" | Opens the site |
| "Search Google for python tutorials" | Opens Google results |
| "Play lo-fi music on YouTube" | Opens YouTube search |
| "Send an email" | Asks recipient, subject, message, then asks you to confirm |
| "Remind me to drink water in 10 minutes" | Reminder with spoken + popup alert |
| "Remind me to call mom tomorrow at 9 am" | Also works |
| "Show my reminders" / "Delete all reminders" | Manage reminders |
| "Add a new command" | Teaches a custom command (website, app or message) |
| "What is Python?" / "Capital of France?" | Answers from `knowledge.json`; unknown questions fall back to Google |
| "Help" / "Goodbye" | Feature list / exit |

Spoken email addresses work as "john dot smith at gmail dot com", or add contacts to `config/contacts.json` and say the name.

## Customising
* **Custom commands:** edit `config/commands.json` (`type` is `website`, `app` or `say`).
* **More answers:** add entries with `questions` and `answer` to `config/knowledge.json`.

## Tests
```cmd
python -m unittest discover tests -v
```
These run offline; SMTP is mocked in tests.

## Troubleshooting
* **"I cannot access the microphone"** - check Windows microphone privacy settings and the default input device.
* **"could not reach speech recognition service"** - speech-to-text uses Google's free web service and needs internet.
* **Email login failed** - use a Gmail App Password.
* **No voice output** - check Windows volume and that a SAPI5 voice is installed.

## Screenshots and demo
Add screenshots to `docs/screenshots/` and link them here:
`![Dashboard](docs/screenshots/dashboard.png)`. Record the demo with Xbox Game Bar (`Win + G`).

## Publishing to GitHub
```cmd
git init
git add .
git commit -m "Voice assistant"
git branch -M main
git remote add origin https://github.com/YOUR_NAME/voice-assistant.git
git push -u origin main
```
Check that `.env` does not appear in `git status` before pushing.


## Live weather (OpenWeatherMap)
1. Create an account and generate an API key at https://openweathermap.org/api.
2. Copy `.env.example` to `.env` if you do not already have a `.env` file.
3. Set `WEATHER_API_KEY=your_actual_api_key` in `.env`.
4. Keep `WEATHER_UNITS=metric` for Celsius, or use `imperial` for Fahrenheit.
5. Restart Nova and ask: `weather in Mumbai`.

The API key is stored locally in `.env`. Do not share this file or upload it to GitHub.
Nova sends the requested city to OpenWeatherMap to retrieve current weather conditions.
