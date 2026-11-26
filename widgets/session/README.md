# trame-fespp-session

The **session door**: save the state of the whole application to a
`.fespp.json` file on the reader's computer, and open such a file to restore
it. It draws its own trigger for the app bar (an icon button like its
neighbours) and its dialog (`fp-dialog`, teleported to `body`).

## What the file holds

The STATE only — what is shown and how. The data (the EPC and its h5 files,
or an OSDU/ETP connection) is not in it and is loaded again when the session
is opened. The dialog guides that: it lists the files the session expects,
each with its state (missing / loaded / different), and mounts the host's own
drop zone in its `files` slot so they are dropped without leaving the dialog.
The file format itself is the host's (`trame_fespp_session/format.py`): the
widget carries the text and never parses it.

## Contract

```
props   hasData   bool     something is loaded: Save is offered only then
        status    {} | {phase, file, saved, note, app, views, files, etp, report, error}
                  phase   idle | waiting | ready | restoring | done | error
                  files   [{name, size_mb, state: missing|loaded|different, why}]
                  etp     null | {url, partition, dataspaces: [uri..], connected, loaded: [uri..]}
                  etp_ready  bool   connected and every saved dataspace loaded
                  report  [{level: ok|warn|error, text}]
        download  {} | {name, text, n}   each new n saves `text` as the file `name`
        autosave  {} | {text, sig, saved, views, files, n}   the state, pushed after each change
                  saved   ISO date (UTC); views  a count; files  [file names]
events  save(note)            the note may be ""
        open({name, text})    a .fespp.json / .json file picked or dropped, read as text
        apply()               restore now ("Restore" and "Restore anyway")
        reset()               forget the opened session file
slot    files                 in the "waiting" phase, under the expected files
        etp                   in "waiting" / "ready" while !etp_ready, under the dataspaces
```

**OSDU / ETP.** A session read from an OSDU RDDMS / ETP server keeps the
server URL, the data partition and the dataspaces loaded — **never the
access token**, which must not lie around in a file. The dialog shows the URL
and partition, one row per saved dataspace with its state (Loaded / To load),
and, while `etp_ready` is false, a line asking for the token above the `etp`
slot, where the host mounts its OSDU form prefilled (`upload-osdu`'s
`prefill` prop): once connected, the dataspaces load by themselves.
**Restore** is enabled only when no file is missing and the ETP part (if any)
is ready; **Restore anyway** goes without what is absent, which the report
lists. A session can hold both files and an ETP part: both slots then show.

The dialog opens by itself when the phase becomes `waiting` or `done`, and
stays closable (Esc, the scrim, ×). A file whose name does not end in `.json`
is refused in the dialog, with no event.

## Autosave

Each new `autosave.n` with a non-empty `text` is kept in this browser's
`localStorage` under the key **`fespp-on-trame:session-autosave`**, as
`{text, saved, views, files}`. The `n` seen at mount is not new, so a state
replayed on reconnection is not stored again (the same rule as `download`).
Storage may be blocked or full: every access is guarded, and a refusal is one
quiet line under Save.

Whenever the browser holds one, the dialog shows a **Last autosave** block
(local date, views, files) with three actions:

- **Resume** emits `open({name: "autosave-<yyyy-mm-dd-hhmm>.fespp.json", text})`,
  and the usual waiting / restore flow follows. It is hidden while a session
  file is open (waiting, ready, restoring), and it is the primary button when
  the session is empty (no data, phase idle or error).
- **Download** saves the stored text as a file on the client side, so it works
  without the server.
- **Discard** removes it from the browser, which cannot be undone.

**On mount**, when there is no data and the browser holds an autosave, the
dialog opens by itself once, with the Resume offer at the top. Its scrim
(z-index 2410) sits above the Import door, which also opens by itself on an
empty session.

**Lost connection.** The widget subscribes to
`window.trame.client.onConnectionClose`, the same wslink subscription trame's
own client uses to replace the page with its loading or reconnect template.
That swap unmounts the widget, so the notice is plain DOM on `<body>`
(`[data-fp-session-lost]`, non-modal, bottom left). It says the connection is
lost and offers **Download the last state**. It is shown only when the browser
holds an autosave.

## Build

```
cd vue-components && npm install && npm run build
# -> trame_fespp_session/module/serve/{*.umd.js, style.css}
```
