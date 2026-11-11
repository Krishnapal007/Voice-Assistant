"""
main.py - Start the Voice Assistant.

    python main.py          -> opens the GUI dashboard
    python main.py --cli    -> console mode (type commands, assistant speaks)
    python main.py --cli --mute   -> console mode without speech output
"""

import argparse
import sys


def run_cli(voice):
    from assistant import Assistant

    assistant = Assistant(voice, on_user=lambda _t: None,
                          input_provider=lambda: input("   > "))
    assistant.start()
    assistant.startup()
    print("Type a command (say 'exit' to quit).")
    try:
        while not assistant.exit_requested:
            try:
                text = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            assistant.process(text)
    finally:
        assistant.stop()


def main():
    parser = argparse.ArgumentParser(description="Python Voice Assistant")
    parser.add_argument("--cli", action="store_true", help="console mode instead of GUI")
    parser.add_argument("--mute", action="store_true", help="turn off spoken replies")
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv
        from pathlib import Path
        load_dotenv(Path(__file__).resolve().parent / ".env")
    except ImportError:
        print("python-dotenv is missing. Run: pip install -r requirements.txt")
        sys.exit(1)

    from voice_engine import VoiceEngine
    voice = VoiceEngine(speech_enabled=not args.mute)

    if args.cli:
        run_cli(voice)
    else:
        from gui import run_gui
        run_gui(voice)


if __name__ == "__main__":
    main()
