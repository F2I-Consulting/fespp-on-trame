"""What the reader said about a read, in the user's words.

FESPP logs through vtkLogger and never raises: a file that is not an EPC,
a representation it cannot map, a property whose HDF5 file is absent all
land in `state.vtk_log_messages` (see engine/vtk_log) as error lines, the
way Data health lists them. This module reads those lines back for the two
actions that must report at once, the import of a file and the load of a
ticked property, and sorts them:

  - a FILE-level failure (the whole file was refused): red, with the file's
    name and the reason in the user's words;
  - the OBJECTS the reader skipped while it read the rest of the file: a
    count, amber, with Data health as the next step (the tree is filled,
    the read did not fail);
  - a PROPERTY that could not be read when it was ticked: red, naming the
    property, the missing file and what to do.

Every sentence is stripped of the server's temp directory, which the user
never sees, and the reader's known phrases are mapped to sentences the user
can act on. Pure functions over the captured entries: no ParaView here.
"""
import os
import re

# The reader's file-level failures: what FESPP's addFile / vtkEPCCollector
# log when the WHOLE file is refused (a bad archive, a schema fesapi cannot
# deserialize). Everything else logged during a read is about ONE object.
_FILE_FAILURE_PREFIXES = (
    "FESAPI error loading",
    "Unknown error loading",
    "Error loading EPC",
    "Unknown fatal error loading EPC",
)

# One object the reader could not map, skipped so the rest of the file
# still loads (ResqmlDataRepositoryToVtkPartitionedDataSetCollection);
# "[BW DIAG]" marks a blocked wellbore whose cells cannot be read.
_SKIP_PREFIXES = ("Skipping ", "[BW DIAG]")

# One property whose values could not be reached when it was ticked.
_PROPERTY_FAILURE_RE = re.compile(
    r"^Error when (?:initialize|load Time Series property) uuid:\s*"
    r"([0-9a-fA-F-]{36})")

# A temp directory made by tempfile.mkdtemp, on POSIX or Windows: never
# shown to the user.
_TMP_DIR_RE = re.compile(r"(?:/tmp|/var/tmp|[A-Za-z]:[\\/][^\s'\"]*?Temp)"
                         r"[\\/]tmp[A-Za-z0-9_]+[\\/]")


def strip_paths(text, temp_dir=""):
    """`text` with the server's temp directory taken out, so a file is
    named by its name alone: "'/tmp/tmpw4j0/junk.epc'" reads "'junk.epc'"."""
    out = str(text or "")
    if temp_dir:
        for sep in ("/", "\\"):
            out = out.replace(str(temp_dir).rstrip("/\\") + sep, "")
    return _TMP_DIR_RE.sub("", out)


def _errors(messages):
    """The text of each non-empty error-level entry, in the order logged."""
    for m in messages or []:
        if (m or {}).get("level") != "error":
            continue
        text = str(m.get("text") or "").strip()
        if text:
            yield text


def _first_line(text):
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines[0] if lines else ""


def _detail_lines(text):
    """Every non-blank line past the first, joined on one line."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return " ".join(lines[1:])


def file_failure(messages, name, temp_dir=""):
    """The sentence for a file the reader REFUSED, "" when it read it (with
    or without skipped objects). `name` is the file's basename."""
    for text in _errors(messages):
        head = _first_line(text)
        if not head.startswith(_FILE_FAILURE_PREFIXES):
            continue
        reason = strip_paths(text, temp_dir)
        # The reader's own wording, past the "... loading '<file>': " header.
        m = re.match(r"^[^:]*loading (?:EPC )?'[^']*'\s*:?\s*", reason)
        detail = reason[m.end():].strip() if m else reason
        if "Cannot unzip" in detail or "not a zip" in detail.lower():
            return (f"{name} is not an EPC archive — export the model to"
                    " .epc again or pick another file.")
        if "does not exist" in detail or "No such file" in detail:
            return f"{name} is not on the server any more — import it again."
        detail = " ".join(detail.split())[:300]
        return (f"Failed to read {name}: {detail}" if detail
                else f"Failed to read {name}: the reader gave no reason"
                     " — see Data health.")
    return ""


def skipped_objects(messages):
    """Count `(skipped, other)` for the amber note: the objects the reader
    skipped and the other object-level errors of a read. File-level
    failures are left out (see file_failure)."""
    skipped, other = 0, 0
    for text in _errors(messages):
        head = _first_line(text)
        if head.startswith(_FILE_FAILURE_PREFIXES):
            continue
        if head.startswith(_SKIP_PREFIXES):
            skipped += 1
        else:
            other += 1
    return skipped, other


def read_note(name, skipped, other):
    """The amber sentence for a file that WAS read, saying what the reader
    left out; "" when it left nothing out."""
    parts = []
    if skipped:
        parts.append(f"{skipped} object{'s' if skipped != 1 else ''}"
                     " skipped by the reader")
    if other:
        parts.append(f"{other} reader error{'s' if other != 1 else ''}")
    if not parts:
        return ""
    return f"Read {name} with {' and '.join(parts)} — see Data health."


def unreadable_properties(messages, title_for_uuid, temp_dir=""):
    """One sentence per property the reader could not read when it was
    ticked, in the order logged, each uuid once. `title_for_uuid` names the
    tree node of a uuid ("" when unknown)."""
    out, seen = [], set()
    for text in _errors(messages):
        m = _PROPERTY_FAILURE_RE.match(_first_line(text))
        if not m:
            continue
        uuid = m.group(1).lower()
        if uuid in seen:
            continue
        seen.add(uuid)
        title = title_for_uuid(uuid) or uuid
        detail = strip_paths(_detail_lines(text), temp_dir)
        h5 = re.search(r"The HDF5 file ([^\s]+) does not exist", detail)
        if h5:
            fname = os.path.basename(h5.group(1).rstrip(".:"))
            out.append(f"{title} could not be read: {fname} is missing —"
                       " import it too, then untick and tick the property"
                       " again.")
            continue
        detail = " ".join(detail.split())[:300]
        out.append(f"{title} could not be read: {detail}" if detail
                   else f"{title} could not be read — see Data health.")
    return out


def property_note(sentences):
    """The red sentence for the ticked properties that could not be read:
    the first one, and how many more Data health lists."""
    if not sentences:
        return ""
    if len(sentences) == 1:
        return sentences[0]
    return f"{sentences[0]} (+{len(sentences) - 1} more — see Data health)"
