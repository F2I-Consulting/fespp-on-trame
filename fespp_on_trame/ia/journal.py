"""The assistant's dialogue journal: every sentence, what the engine took it
for, what the assistant replied, and what the reader did next (a button
clicked, an undo) — the material the vocabulary is enriched from
(scripts/assistant_log_report.py).

One JSON object per line, one file per UTC day, in the folder
FESPP_ASSISTANT_LOG names (default /deploy/server/logs/assistant; "off"
writes nothing). It stays on the server: nothing leaves it, and it never
holds a token — the assistant never sees one.

    {"ts": "<UTC, ISO 8601>", "session": "3f9a…", "turn": 7,
     "event": "said", "text": "montre la grille", "lang": "fr",
     "intent": "show", "confidence": 0.91, ...}

Writing never fails the assistant: an error is printed once and the journal
goes quiet for the rest of the session.
"""
import datetime
import json
import os
import threading
import uuid

DEFAULT_DIR = "/deploy/server/logs/assistant"


class DialogueJournal:
    """The journal of one session: thread-safe, silent after its first
    write error."""

    def __init__(self, folder, session=None):
        self.folder = folder
        self.session = session or uuid.uuid4().hex[:12]
        self._lock = threading.Lock()
        self._broken = False

    @classmethod
    def from_env(cls, session=None):
        """The journal FESPP_ASSISTANT_LOG asks for, or None when it says
        "off"."""
        where = (os.environ.get("FESPP_ASSISTANT_LOG") or DEFAULT_DIR).strip()
        if where.lower() in ("off", "0", "no", "none"):
            print("[assistant] dialogue journal off (FESPP_ASSISTANT_LOG)", flush=True)
            return None
        journal = cls(where, session)
        print(f"[assistant] dialogue journal: {where} (session {journal.session})", flush=True)
        return journal

    def path(self, when=None):
        day = (when or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y-%m-%d")
        return os.path.join(self.folder, f"assistant-{day}.jsonl")

    def append(self, event):
        """Add one event (a dict), stamped with the UTC time and the session."""
        if self._broken:
            return
        now = datetime.datetime.now(datetime.timezone.utc)
        line = dict({"ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "session": self.session}, **event)
        try:
            text = json.dumps(line, ensure_ascii=False, default=str)
            with self._lock:
                os.makedirs(self.folder, exist_ok=True)
                with open(self.path(now), "a", encoding="utf-8") as f:
                    f.write(text + "\n")
        except Exception as exc:
            self._broken = True
            print(f"[assistant] the dialogue journal cannot be written in {self.folder},"
                  f" it stops for this session:", exc, flush=True)

    __call__ = append


def read(folder):
    """Every event of every journal file of `folder`, oldest first; a line
    that is not JSON is reported and skipped."""
    events = []
    for name in sorted(os.listdir(folder)):
        if not (name.startswith("assistant-") and name.endswith(".jsonl")):
            continue
        with open(os.path.join(folder, name), encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except ValueError as exc:
                    print(f"[assistant] {name}:{n} is not JSON, skipped:", exc, flush=True)
    return events
