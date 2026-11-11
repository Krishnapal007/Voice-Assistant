"""
gui.py - Tkinter dashboard.

Important rule: Tkinter widgets may only be touched from the main thread.
Background threads (listening, speaking, reminders) put messages into
`self.events`; the main thread reads them every 100 ms in `_poll_events`.
"""

import queue
import threading
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, scrolledtext

from assistant import Assistant

try:
    import winsound  # Windows only
except ImportError:
    winsound = None

C = {
    "bg": "#0f172a", "panel": "#1e293b", "text": "#e2e8f0", "muted": "#94a3b8",
    "accent": "#38bdf8", "user": "#60a5fa", "bot": "#4ade80", "error": "#f87171",
    "green": "#16a34a", "red": "#dc2626", "amber": "#f59e0b", "grey": "#475569",
}
FONT = ("Segoe UI", 11)

QUICK_ACTIONS = [
    ("What time is it?", "what time is it"),
    ("Today's date", "what is the date today"),
    ("Open Google", "open google"),
    ("Open YouTube", "open youtube"),
    ("Weather", "weather"),
    ("My reminders", "show my reminders"),
    ("Help", "help"),
]


class AssistantGUI:
    def __init__(self, root, voice):
        self.root = root
        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.listen_thread = None

        self.assistant = Assistant(
            voice,
            on_user=lambda t: self.events.put(("user", t)),
            on_assistant=lambda t: self.events.put(("assistant", t)),
            on_notify=lambda title, msg: self.events.put(("notify", (title, msg))),
            on_exit=lambda: self.events.put(("exit", None)),
        )

        self._build_window()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.assistant.start()
        threading.Thread(target=self.assistant.startup, daemon=True).start()
        self._poll_events()
        self._refresh_reminders()

    # ------------------------------------------------------------ layout
    def _build_window(self):
        root = self.root
        root.title(f"{self.assistant.name} - Voice Assistant")
        root.geometry("1000x660")
        root.minsize(860, 560)
        root.configure(bg=C["bg"])

        header = tk.Frame(root, bg=C["panel"], padx=16, pady=10)
        header.pack(fill="x")
        tk.Label(header, text=f"\U0001F399  {self.assistant.name} Voice Assistant", bg=C["panel"],
                 fg=C["accent"], font=("Segoe UI", 16, "bold")).pack(side="left")
        self.status_dot = tk.Label(header, text="\u25CF", bg=C["panel"], fg=C["grey"], font=("Segoe UI", 14))
        self.status_dot.pack(side="right")
        self.status_label = tk.Label(header, text="Idle", bg=C["panel"], fg=C["text"], font=FONT)
        self.status_label.pack(side="right", padx=(0, 6))

        body = tk.Frame(root, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=12, pady=10)

        # Conversation log
        left = tk.Frame(body, bg=C["bg"])
        left.pack(side="left", fill="both", expand=True)
        tk.Label(left, text="Conversation", bg=C["bg"], fg=C["muted"], font=("Segoe UI", 10, "bold")
                 ).pack(anchor="w")
        self.chat = scrolledtext.ScrolledText(
            left, wrap="word", state="disabled", bg=C["panel"], fg=C["text"], font=FONT,
            relief="flat", padx=10, pady=10, insertbackground=C["text"])
        self.chat.pack(fill="both", expand=True, pady=(4, 8))
        self.chat.tag_config("time", foreground=C["muted"], font=("Segoe UI", 9))
        self.chat.tag_config("user", foreground=C["user"], font=("Segoe UI", 11, "bold"))
        self.chat.tag_config("bot", foreground=C["bot"], font=("Segoe UI", 11, "bold"))
        self.chat.tag_config("error", foreground=C["error"], font=("Segoe UI", 11, "bold"))
        self.chat.tag_config("body", foreground=C["text"])

        # Text entry
        entry_row = tk.Frame(left, bg=C["bg"])
        entry_row.pack(fill="x")
        self.entry = tk.Entry(entry_row, bg=C["panel"], fg=C["text"], insertbackground=C["text"],
                              relief="flat", font=FONT)
        self.entry.pack(side="left", fill="x", expand=True, ipady=8, padx=(0, 8))
        self.entry.bind("<Return>", lambda _e: self._send_typed())
        self.entry.focus_set()
        self._button(entry_row, "Send", C["accent"], self._send_typed, fg="#0f172a").pack(side="left")

        # Control buttons
        controls = tk.Frame(left, bg=C["bg"])
        controls.pack(fill="x", pady=(10, 0))
        self.start_btn = self._button(controls, "\U0001F3A4  Start Listening", C["green"], self.start_listening)
        self.start_btn.pack(side="left", padx=(0, 8))
        self.stop_btn = self._button(controls, "\u23F9  Stop Listening", C["red"], self.stop_listening)
        self.stop_btn.pack(side="left", padx=(0, 8))
        self.stop_btn.config(state="disabled")
        self._button(controls, "Clear Log", C["grey"], self._clear_log).pack(side="left")

        # Sidebar
        right = tk.Frame(body, bg=C["bg"], width=260)
        right.pack(side="right", fill="y", padx=(12, 0))
        right.pack_propagate(False)
        tk.Label(right, text="Quick Actions", bg=C["bg"], fg=C["muted"], font=("Segoe UI", 10, "bold")
                 ).pack(anchor="w")
        for label, command in QUICK_ACTIONS:
            self._button(right, label, C["panel"], lambda c=command: self._run_command(c)
                         ).pack(fill="x", pady=2)
        tk.Label(right, text="Pending Reminders", bg=C["bg"], fg=C["muted"], font=("Segoe UI", 10, "bold")
                 ).pack(anchor="w", pady=(14, 0))
        self.reminder_list = tk.Listbox(right, bg=C["panel"], fg=C["text"], relief="flat", font=("Segoe UI", 10),
                                        selectbackground=C["accent"], activestyle="none", height=8)
        self.reminder_list.pack(fill="both", expand=True, pady=4)

    @staticmethod
    def _button(parent, text, bg, command, fg="white"):
        return tk.Button(parent, text=text, command=command, bg=bg, fg=fg, activebackground=C["accent"],
                         activeforeground="#0f172a", relief="flat", font=("Segoe UI", 10, "bold"),
                         padx=14, pady=7, cursor="hand2", bd=0)

    # ------------------------------------------------------------ chat log
    def _append(self, who, text, tag):
        self.chat.config(state="normal")
        self.chat.insert("end", datetime.now().strftime("[%H:%M:%S] "), "time")
        self.chat.insert("end", f"{who}: ", tag)
        self.chat.insert("end", text + "\n\n", "body")
        self.chat.config(state="disabled")
        self.chat.see("end")

    def _clear_log(self):
        self.chat.config(state="normal")
        self.chat.delete("1.0", "end")
        self.chat.config(state="disabled")

    def _set_status(self, text):
        colors = {"Listening": C["green"], "Processing": C["amber"], "Idle": C["grey"]}
        self.status_label.config(text=text)
        self.status_dot.config(fg=colors.get(text, C["accent"]))

    # ------------------------------------------------------------ events from other threads
    def _poll_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "user":
                    self._append("You", payload, "user")
                elif kind == "assistant":
                    is_error = payload.lower().startswith(("microphone problem", "i cannot access", "i could not reach"))
                    self._append(self.assistant.name, payload, "error" if is_error else "bot")
                elif kind == "status":
                    self._set_status(payload)
                elif kind == "notify":
                    self._show_reminder(*payload)
                elif kind == "listen_ended":
                    self.start_btn.config(state="normal")
                    self.stop_btn.config(state="disabled")
                    self._set_status("Idle")
                elif kind == "exit":
                    self.root.after(800, self._on_close)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def _show_reminder(self, title, message):
        if winsound:
            try:
                winsound.MessageBeep()
            except RuntimeError:
                pass
        self.root.bell()
        messagebox.showinfo(title, message, parent=self.root)
        self._refresh_reminders(once=True)

    def _refresh_reminders(self, once=False):
        self.reminder_list.delete(0, "end")
        for item in self.assistant.reminders.pending():
            due = datetime.fromisoformat(item.due).strftime("%d %b %H:%M")
            self.reminder_list.insert("end", f"{due}  {item.task}")
        if not once:
            self.root.after(3000, self._refresh_reminders)

    # ------------------------------------------------------------ actions
    def _run_command(self, text):
        if self.assistant.submit_text(text):
            return
        threading.Thread(target=self.assistant.process, args=(text,), daemon=True).start()

    def _send_typed(self):
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, "end")
        self._run_command(text)

    def start_listening(self):
        if self.listen_thread and self.listen_thread.is_alive():
            return
        self.stop_event.clear()
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.listen_thread = threading.Thread(target=self._listen_worker, daemon=True)
        self.listen_thread.start()

    def _listen_worker(self):
        try:
            self.assistant.listen_loop(self.stop_event, lambda s: self.events.put(("status", s)))
        finally:
            self.events.put(("listen_ended", None))

    def stop_listening(self):
        self.stop_event.set()
        self.stop_btn.config(state="disabled")
        self._set_status("Stopping...")

    def _on_close(self):
        self.stop_event.set()
        self.assistant.stop()
        self.root.destroy()


def run_gui(voice):
    root = tk.Tk()
    AssistantGUI(root, voice)
    root.mainloop()
