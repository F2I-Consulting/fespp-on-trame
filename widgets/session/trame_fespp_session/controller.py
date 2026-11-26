"""The session door's server side: phases, validation, expected files,
download, report — everything that is not the application's own business.

The application hands over a HOST adapter, the only place that knows what
its state is made of::

    class Host:
        def app_name(self) -> str: ...
        def loaded_files(self) -> list: ...          # [{"name", "size_mb", "failed"}]
        def has_data(self) -> bool: ...              # something worth keeping is loaded
        def collect(self) -> dict: ...               # sources / session / objects / layout / views
        def current_objects(self, paths) -> dict: ...   # {path: fingerprint} of what the data has now
        def candidates(self, type_, title) -> list: ... # paths of objects of that type and title
        def restore(self, doc, report) -> None: ...  # apply; report(level, text)

    `collect` may take a `citations` keyword: the autosave then calls it
    with ``citations=False``, so that it never queries the reader.

    and, for a session read from OSDU / ETP (optional)::

        etp_watch = ("etp_connected", ...)          # state vars that move the ETP part
        def etp_state(self) -> dict: ...             # {"connected", "loaded": [dataspaces]}
        def etp_resume(self, dataspaces) -> None: ...   # load them, once connected

    The file keeps the server and the dataspaces, NEVER the token: the door
    prefills the connection form (`etp_prefill_var`) and the reader types it.

    SessionController(server, host, loaded_files_var="ui_loaded_files")

and mounts ``SessionDoor(status=(ctl.status_var,), download=(ctl.download_var,),
autosave=(ctl.autosave_var,), save=(ctl.save, "[$event]"),
open=(ctl.open, "[$event]"), apply=ctl.apply, reset=ctl.reset)``; the host
calls ``ctl.touch()`` on every change it knows of, to feed the autosave.
"""
import datetime

from trame_fespp_session import format as sf


class SessionController:
    """The session door's server side for one trame server and one host
    adapter; its state variables are named after `prefix`."""

    def __init__(self, server, host, loaded_files_var="ui_loaded_files",
                 prefix="ui_session"):
        self.server = server
        self.state = server.state
        self.host = host
        self.status_var = f"{prefix}_status"
        self.download_var = f"{prefix}_download"
        # the OSDU / ETP connection form, prefilled from the file (url,
        # partition): the token is the reader's to type
        self.etp_prefill_var = f"{prefix}_etp_prefill"
        self._etp_asked = set()
        # a session that waited for its OSDU / ETP data restores by itself
        # once the reader's token brought them back: nothing else to decide
        self._auto_apply = False
        # the AUTOSAVE: the state document after every change (one write per
        # burst of changes, see `touch`), pushed to the browser, which keeps
        # it in its local storage — it outlives a server session that
        # crashes, with its temporary files
        self.autosave_var = f"{prefix}_autosave"
        self.autosave_delay = 2.0
        self._autosave_pending = False
        self._doc = None
        self._name = ""
        self.state.setdefault(self.status_var, {})
        self.state.setdefault(self.download_var, {})
        self.state.setdefault(self.autosave_var, {})
        self.state.setdefault(self.etp_prefill_var, {})

        # the expected files tick themselves as the reader drops them
        @self.state.change(loaded_files_var)
        def _on_files(**_):
            if self._doc is not None and self._phase() in ("waiting", "ready"):
                self._publish_waiting()

        # and the ETP part as the connection and the dataspaces arrive
        watch = tuple(getattr(host, "etp_watch", ()) or ())
        if watch:
            @self.state.change(*watch)
            def _on_etp(**_):
                if self._doc is not None and self._phase() in ("waiting", "ready"):
                    self._publish_waiting()

    # ---------------------------------------------------------------- save
    def save(self, note=""):
        doc = {"schema": sf.SCHEMA,
               "meta": {"app": self.host.app_name(),
                        "saved": datetime.datetime.now(datetime.timezone.utc)
                        .strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "note": str(note or "")}}
        doc.update(self.host.collect() or {})
        stamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M")
        prev = self.state[self.download_var] or {}
        self.state[self.download_var] = {
            "name": f"session-{stamp}{sf.SUFFIX}", "text": sf.dumps(doc),
            "n": int(prev.get("n") or 0) + 1}

    # ---------------------------------------------------------------- open
    def open(self, payload):
        payload = payload if isinstance(payload, dict) else {}
        name = str(payload.get("name") or "")
        try:
            doc = sf.loads(payload.get("text") or "")
        except sf.SessionFileError as exc:
            self._doc = None
            self._name = name
            self.state[self.status_var] = {"phase": "error", "file": name, "error": str(exc)}
            return
        self.open_document(doc, name)

    def open_document(self, doc, name=""):
        """A validated document (`format.document`) opened in the door: the
        files it expects awaited, the ETP form prefilled, the dataspaces
        loaded once the reader typed the token. A file applies on the
        reader's click; a PARTIAL document (the API's: a URL, a host) has
        no reader to click and applies as soon as its sources are there —
        a file it names by a server path is read now, by the host."""
        self._doc, self._name = doc, name
        files = (doc.get("sources") or {}).get("files") or []
        if hasattr(self.host, "load_file"):
            for f in files:
                if f.get("path"):
                    self.host.load_file(f["path"])
        etp = (doc.get("sources") or {}).get("etp") or {}
        self._etp_asked = set()
        self.state[self.etp_prefill_var] = (
            {"url": etp.get("url") or "", "partition": etp.get("partition") or ""}
            if etp.get("url") else {})
        self._auto_apply = bool(doc.get("partial"))
        self._publish_waiting()
        st = self.state[self.status_var] or {}
        if not doc.get("partial"):
            self._auto_apply = bool(st.get("phase") == "waiting" and st.get("etp")
                                    and not st.get("etp_ready"))

    def reset(self):
        self._doc = None
        self._name = ""
        self._auto_apply = False
        self._etp_asked = set()
        self.state[self.etp_prefill_var] = {}
        self.state[self.status_var] = {}

    # ---------------------------------------------------------------- apply
    def apply(self):
        if self._doc is None:
            return
        base = self._facts()
        self.state[self.status_var] = {**base, "phase": "restoring"}
        self.state.flush()
        report = []

        def say(level, text):
            report.append({"level": level, "text": str(text)})

        doc = self._doc
        # what changed in the data since the save, before anything is applied
        saved = doc.get("objects") or {}
        try:
            now = self.host.current_objects(list(saved))
            for f in sf.compare_objects(saved, now, self.host.candidates):
                say(f["level"], f["text"])
        except Exception as exc:
            say("warn", f"The data could not be compared with the save: {exc}")
        try:
            self.host.restore(doc, say)
        except Exception as exc:
            say("error", f"The restore stopped: {exc}")
        if not any(r["level"] == "error" for r in report):
            say("ok", "Session restored.")
        # a document applied by itself (a URL, a host) is no reason to open
        # the dialog: its report waits there, `silent` keeps the door shut
        self.state[self.status_var] = {**base, "phase": "done", "report": report,
                                       "silent": bool(doc.get("partial"))}

    # ---------------------------------------------------------------- helpers
    def _phase(self):
        return (self.state[self.status_var] or {}).get("phase", "")

    def _facts(self):
        doc = self._doc or {}
        meta = doc.get("meta") or {}
        saved = meta.get("saved") or ""
        return {"file": self._name, "saved": saved.replace("T", " ").rstrip("Z")[:16],
                "note": meta.get("note") or "", "app": meta.get("app") or "",
                "views": len(doc.get("views") or []),
                "etp": (doc.get("sources") or {}).get("etp") or None}

    def _publish_waiting(self):
        sources = self._doc.get("sources") or {}
        files = sf.file_states(sources.get("files") or [], self.host.loaded_files())
        ready = all(f["state"] != "missing" for f in files)
        # the OSDU / ETP part: connected (the reader typed the token), then
        # the saved dataspaces loaded — asked for once each, by the host
        now = (self.host.etp_state() if hasattr(self.host, "etp_state") else {}) or {}
        etp, etp_ready, missing = sf.etp_state(sources.get("etp"), now.get("connected"),
                                               now.get("loaded"))
        ask = [d for d in missing if d not in self._etp_asked]
        if now.get("connected") and ask and hasattr(self.host, "etp_resume"):
            self._etp_asked.update(ask)
            self.host.etp_resume(ask)
        self.state[self.status_var] = {
            **self._facts(), "files": files, "etp": etp, "etp_ready": etp_ready,
            "phase": "ready" if ready and etp_ready else "waiting"}
        # a file applies by itself once the token it waited for came; a
        # partial document as soon as everything it needs is there
        if ready and etp_ready and self._auto_apply and (etp or (self._doc or {}).get("partial")):
            self._auto_apply = False
            self.apply()

    # ---------------------------------------------------------------- autosave
    def touch(self):
        """Something changed: schedule the autosave `autosave_delay` seconds
        from now, unless one is already scheduled — a burst of changes gives
        one write, timed from its first change. The host calls this on every
        change it knows of (a render, a load)."""
        if self._autosave_pending:
            return
        self._autosave_pending = True
        try:
            import asyncio
            from trame.app import asynchronous

            async def _later():
                await asyncio.sleep(self.autosave_delay)
                self._autosave_pending = False
                with self.state:
                    self.autosave_now()

            asynchronous.create_task(_later())
        except Exception as exc:
            # no event loop (a headless call): write it now
            print("[session] autosave deferred write failed, writing now:", exc, flush=True)
            self._autosave_pending = False
            self.autosave_now()

    def autosave_now(self):
        """The state document into `autosave_var` — never the state of an
        EMPTY session (a fresh page would erase the one worth coming back
        to) nor during a restore (half a session)."""
        if not self.host.has_data() or self._phase() in ("waiting", "ready", "restoring"):
            return
        doc = {"schema": sf.SCHEMA,
               "meta": {"app": self.host.app_name(),
                        "saved": datetime.datetime.now(datetime.timezone.utc)
                        .strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "note": "autosave"}}
        try:
            # a host that can collect WITHOUT querying its reader does so
            # here: the autosave follows every render, and a FESPP reader
            # query at that moment can crash the next render
            import inspect
            light = "citations" in inspect.signature(self.host.collect).parameters
            doc.update((self.host.collect(citations=False) if light else self.host.collect()) or {})
        except Exception as exc:
            print("[session] autosave collect failed:", exc, flush=True)
            return
        prev = self.state[self.autosave_var] or {}
        # what the session IS, without the moment it was written: a render
        # that changed nothing must not push the same state again
        import hashlib
        sig = hashlib.sha1(sf.dumps({k: v for k, v in doc.items() if k != "meta"})
                           .encode("utf-8")).hexdigest()
        if sig == prev.get("sig"):
            return
        self.state[self.autosave_var] = {
            "text": sf.dumps(doc), "sig": sig, "saved": doc["meta"]["saved"],
            "views": len(doc.get("views") or []),
            "files": [f.get("name") for f in (doc.get("sources") or {}).get("files") or []],
            "n": int(prev.get("n") or 0) + 1}
