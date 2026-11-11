"""
nlp_engine.py - Basic NLP: intent detection + local knowledge base.

How intent detection works (no heavy AI libraries needed)
---------------------------------------------------------
1. Clean the sentence (lowercase, remove punctuation).
2. Fix small spelling mistakes in important command words.
3. Every intent has a few regular-expression patterns, each with a weight.
4. Add up the weights of the patterns that match. The highest score wins.
"""

import difflib
import json
import re
from dataclasses import dataclass
from pathlib import Path

# Words we try to auto-correct when the speech recogniser or the user mis-spells them.
VOCAB = [
    "email", "reminder", "reminders",
    "youtube", "google", "search", "command", "commands", "calendar", "weather", "temperature", "forecast",
]

# intent name -> list of (regex pattern, weight). Order matters only for ties.
INTENT_PATTERNS = {
    "weather": [(r"\b(weather|temperature|forecast)\b", 5)],
    "exit": [(r"\b(exit|quit|goodbye|good bye|bye|shut down|stop assistant|close assistant)\b", 5)],
    "greeting": [(r"^(hello|hi|hey|hii|namaste|good (morning|afternoon|evening))\b", 3)],
    "reminder_clear": [(r"\b(delete|clear|remove|cancel)\b.*\breminders?\b", 7)],
    "reminder_list": [(r"\b(list|show|read|what are|tell me|my)\b.*\breminders?\b", 5)],
    "reminder_set": [(r"\bremind(er)?s?\b", 3), (r"\b(set|add|create)\b.*\breminder\b", 3)],
    "add_command": [(r"\b(add|create|make|teach)\b.*\bcommand\b", 6)],
    "list_commands": [(r"\b(list|show|what are)\b.*\bcommands\b", 6)],
    "email": [(r"\b(email|e-mail|mail)\b", 4), (r"\b(send|write|compose)\b.*\b(email|mail)\b", 2)],
    "open_google": [(r"\b(open|launch|start|go to|take me to)\b.*\bgoogle\b", 4)],
    "open_youtube": [(r"\b(open|launch|start|go to|take me to)\b.*\byoutube\b", 4)],
    "youtube_search": [(r"\b(play|search|find|watch|look up)\b.*\b(on|in)\s+youtube\b", 6),
                       (r"\bsearch\b.*\byoutube\b", 5), (r"\byoutube\b.*\bsearch\b", 5)],
    "search": [(r"\b(search|look up|lookup|google)\b", 3), (r"\bsearch\b.*\bgoogle\b", 4),
               (r"\bfind\b", 2)],
    "time": [(r"\btime\b", 2), (r"\b(current|the|what is the)\b.*\btime\b", 2)],
    "date": [(r"\bdate\b", 3), (r"\b(what day|today is|day is it)\b", 3), (r"\btoday\b", 1)],
    "help": [(r"\b(help|what can you do|your features|capabilities)\b", 4)],
    "knowledge": [
        (r"^(what is|what are|who is|who was|who are|who made|who created|tell me about|"
         r"explain|define|how many|how do|how does|why|when|where)\b", 2),
        (r"\b(your name|who are you|about you|how are you)\b", 3),
    ],
}

MIN_SCORE = 2


@dataclass
class Intent:
    name: str
    score: int
    text: str


class IntentDetector:
    def __init__(self):
        self._compiled = {
            name: [(re.compile(p), w) for p, w in patterns]
            for name, patterns in INTENT_PATTERNS.items()
        }

    @staticmethod
    def normalize(text):
        """Lowercase, expand "what's" -> "what is", remove odd punctuation."""
        text = text.lower().strip()
        text = re.sub(r"\b(what|who|where|how|that|there)'?s\b", r"\1 is", text)
        text = re.sub(r"[^\w\s:@.'-]", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _correct(text):
        """Fix small spelling mistakes in the important words."""
        fixed = []
        for word in text.split():
            if len(word) >= 6 and word not in VOCAB:
                match = difflib.get_close_matches(word, VOCAB, n=1, cutoff=0.85)
                if match:
                    word = match[0]
            fixed.append(word)
        return " ".join(fixed)

    def detect(self, text):
        cleaned = self._correct(self.normalize(text))
        best_name, best_score = "unknown", 0
        for name, patterns in self._compiled.items():
            score = sum(weight for regex, weight in patterns if regex.search(cleaned))
            if score > best_score:
                best_name, best_score = name, score
        if best_score < MIN_SCORE:
            return Intent("unknown", best_score, text)
        return Intent(best_name, best_score, text)


# ---------------------------------------------------------------- entity extraction
_FILLER = {"google", "for", "about", "on", "up", "please", "information", "info", "me",
           "the", "web", "internet", "out"}


def _strip_filler(query):
    words = query.split()
    while words and words[0] in _FILLER:
        words.pop(0)
    while words and words[-1] in {"please", "google"}:
        words.pop()
    return " ".join(words).strip()


def extract_search_query(text):
    """'search google for python tutorials' -> 'python tutorials'"""
    t = re.sub(r"[^\w\s']", " ", text.lower())
    t = re.sub(r"\b(on|in|using) (google|the web|the internet)\b", " ", t)
    match = re.search(r"\b(?:search|look up|lookup|google|find)\s+(.*)", t)
    if not match:
        return ""
    return _strip_filler(re.sub(r"\s+", " ", match.group(1)))


def extract_youtube_query(text):
    """'play despacito on youtube' -> 'despacito'"""
    t = re.sub(r"[^\w\s']", " ", text.lower())
    t = re.sub(r"\b(on|in)\s+youtube\b", " ", t)
    t = re.sub(r"\byoutube\b", " ", t)
    t = re.sub(r"^\s*(please\s+)?(play|search for|search|find|watch|look up)\s+", "", t)
    t = re.sub(r"^\s*for\s+", "", t)
    return re.sub(r"\s+", " ", t).strip()


# ---------------------------------------------------------------- knowledge base
_STOP = {"a", "an", "the", "is", "are", "was", "were", "of", "to", "in", "me", "tell",
         "about", "please", "what", "s", "do", "does", "can", "you", "explain", "define"}
_KEEP_FOR_PERSONAL = {"you"}  # needed for "who are you" / "how are you"


def _tokens(text):
    words = re.findall(r"[a-z0-9]+", text.lower())
    out = set()
    for w in words:
        if w in _STOP and not (w in _KEEP_FOR_PERSONAL and ("who" in words or "how" in words)):
            continue
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.add(w)
    return out


class KnowledgeBase:
    """Answers common questions from config/knowledge.json (no internet needed)."""

    def __init__(self, path, threshold=0.5):
        self.path = Path(path)
        self.threshold = threshold
        self.entries = []
        self.load()

    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.entries = data.get("entries", [])
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[knowledge] Could not load {self.path}: {exc}")
            self.entries = []

    def answer(self, question):
        """Return the best answer, or None when nothing is similar enough."""
        q = _tokens(question)
        if not q:
            return None
        best_score, best_answer = 0.0, None
        for entry in self.entries:
            for example in entry.get("questions", []):
                e = _tokens(example)
                if not e:
                    continue
                score = len(q & e) / len(q | e)  # Jaccard similarity
                if score > best_score:
                    best_score, best_answer = score, entry.get("answer")
        return best_answer if best_score >= self.threshold else None
