"""
voice_engine.py - Speech output (pyttsx3) and speech input (SpeechRecognition).

Beginner notes
--------------
* Text-to-speech runs in ONE background "worker" thread. pyttsx3 can freeze if
  it is used from many different threads, so every request goes through a queue.
* Speech-to-text uses Google's free web speech recognizer (needs internet).
* The libraries are imported inside try/except so the rest of the project can
  still be imported (and tested) when a library is missing.
"""

import queue
import threading

try:
    import speech_recognition as sr
except ImportError:  # pragma: no cover
    sr = None

try:
    import pyttsx3
except ImportError:  # pragma: no cover
    pyttsx3 = None


class VoiceError(Exception):
    """Base class for all voice related problems."""


class MicrophoneError(VoiceError):
    """The microphone is missing, blocked or PyAudio is not installed."""


class SpeechServiceError(VoiceError):
    """The online speech recognition service could not be reached."""


MIC_HELP = (
    "I cannot access the microphone. Please check: (1) a microphone is plugged in, "
    "(2) Windows Settings > Privacy > Microphone > allow microphone access and "
    "'Let desktop apps access your microphone' are ON, (3) PyAudio is installed "
    "(pip install PyAudio)."
)


class VoiceEngine:
    def __init__(self, rate=175, volume=1.0, speech_enabled=True):
        self.rate = rate
        self.volume = volume
        self.speech_enabled = speech_enabled
        self.tts_available = False

        self.recognizer = None
        if sr is not None:
            self.recognizer = sr.Recognizer()
            self.recognizer.dynamic_energy_threshold = True
            self.recognizer.pause_threshold = 0.8

        self._calibrated = False
        self._listen_lock = threading.Lock()
        self._speech_queue = queue.Queue()
        self._tts_ready = threading.Event()

        self._worker = threading.Thread(target=self._speech_worker, daemon=True)
        self._worker.start()
        self._tts_ready.wait(timeout=10)

    # ------------------------------------------------------------------ speech output
    def _speech_worker(self):
        """Runs forever in the background and speaks whatever is in the queue."""
        engine = None
        if self.speech_enabled and pyttsx3 is not None:
            try:
                try:  # Windows: each thread must initialise COM once
                    import pythoncom
                    pythoncom.CoInitialize()
                except ImportError:
                    pass
                engine = pyttsx3.init()
                engine.setProperty("rate", self.rate)
                engine.setProperty("volume", self.volume)
            except Exception as exc:  # noqa: BLE001
                print(f"[voice] Text-to-speech could not start: {exc}")
                engine = None
        self.tts_available = engine is not None
        self._tts_ready.set()

        while True:
            item = self._speech_queue.get()
            if item is None:
                break
            text, done = item
            if engine is not None:
                try:
                    engine.say(text)
                    engine.runAndWait()
                except Exception as exc:  # noqa: BLE001
                    print(f"[voice] Could not speak: {exc}")
            done.set()

    def speak(self, text, wait=True):
        """Say `text` out loud. If wait=True, return after speaking has finished."""
        if not text:
            return
        done = threading.Event()
        self._speech_queue.put((text, done))
        if wait:
            done.wait(timeout=90)

    # ------------------------------------------------------------------ speech input
    def check_microphone(self):
        """Return (ok, message). Used at start-up and before listening."""
        if sr is None:
            return False, "SpeechRecognition is not installed. Run: pip install SpeechRecognition"
        try:
            import pyaudio  # noqa: F401
        except ImportError:
            return False, "PyAudio is not installed. Run: pip install PyAudio"
        try:
            names = sr.Microphone.list_microphone_names()
        except Exception as exc:  # noqa: BLE001
            return False, f"Could not list audio devices: {exc}"
        if not names:
            return False, "No microphone was found. Please plug one in."
        try:
            with sr.Microphone():
                pass
        except OSError:
            return False, MIC_HELP
        except Exception as exc:  # noqa: BLE001
            return False, f"Microphone problem: {exc}"
        return True, "Microphone is ready."

    def listen(self, timeout=5, phrase_time_limit=10):
        """
        Listen once. Returns the recognised text, or None if nothing was said or
        the speech was not understood. Raises MicrophoneError / SpeechServiceError
        for real problems.
        """
        if self.recognizer is None:
            raise MicrophoneError("SpeechRecognition is not installed.")

        with self._listen_lock:  # only one thread may use the microphone at a time
            try:
                with sr.Microphone() as source:
                    if not self._calibrated:
                        self.recognizer.adjust_for_ambient_noise(source, duration=1)
                        self._calibrated = True
                    audio = self.recognizer.listen(
                        source, timeout=timeout, phrase_time_limit=phrase_time_limit
                    )
            except sr.WaitTimeoutError:
                return None
            except (OSError, AttributeError) as exc:
                # AttributeError = PyAudio missing, OSError = no/blocked microphone
                raise MicrophoneError(MIC_HELP) from exc

        try:
            return self.recognizer.recognize_google(audio).strip()
        except sr.UnknownValueError:
            return None
        except sr.RequestError as exc:
            raise SpeechServiceError(
                "I could not reach the speech recognition service. Please check your internet connection."
            ) from exc

    def shutdown(self):
        self._speech_queue.put(None)
