"""engine/io/read_report — what the reader said, in the user's words.

The reader logs a refused file and a skipped object at the same level; the
import door must go red only for the first, count the second on the amber
note, and a property ticked without its .h5 must be named with its missing
file. No server temp path ever reaches a sentence.
"""
from fespp_on_trame.engine.io import read_report as rr


TMP = "/tmp/tmpw4j0w3lu"


def _err(text):
    return {"level": "error", "text": text}


def _warn(text):
    return {"level": "warning", "text": text}


class TestFileFailure:
    def test_not_an_archive_is_said_in_the_users_words(self):
        msgs = [_err(f"FESAPI error loading '{TMP}/junk.epc': Cannot unzip"
                     f" {TMP}/junk.epc. Please verify the path of the file and"
                     " if you can open it with a third party archiver.")]
        text = rr.file_failure(msgs, "junk.epc", TMP)
        assert text == ("junk.epc is not an EPC archive — export the model to"
                        " .epc again or pick another file.")
        assert TMP not in text

    def test_an_unknown_reason_keeps_the_readers_words_minus_the_path(self):
        msgs = [_err(f"Error loading EPC '{TMP}/x.epc': gsoap: element"
                     f" not found in {TMP}/x.epc part 3")]
        text = rr.file_failure(msgs, "x.epc", TMP)
        assert text.startswith("Failed to read x.epc: gsoap: element not found")
        assert TMP not in text and "x.epc part 3" in text

    def test_a_temp_path_of_another_shape_is_stripped_too(self):
        msgs = [_err("Unknown fatal error loading EPC '/tmp/tmpabc12/y.epc'")]
        text = rr.file_failure(msgs, "y.epc")
        assert text == ("Failed to read y.epc: the reader gave no reason"
                        " — see Data health.")

    def test_a_skipped_object_is_no_failure(self):
        msgs = [_warn("some warning"),
                _err("Skipping representation uuid=abc: no geometry"),
                _err("[BW DIAG] 1234 no supporting grid"),
                _err("Error: UnstructuredGrid (uuid: 9) has no geometry,"
                     " cannot render.")]
        assert rr.file_failure(msgs, "x.epc", TMP) == ""
        assert rr.skipped_objects(msgs) == (2, 1)
        assert rr.read_note("x.epc", 2, 1) == (
            "Read x.epc with 2 objects skipped by the reader and 1 reader"
            " error — see Data health.")
        assert rr.read_note("x.epc", 1, 0) == (
            "Read x.epc with 1 object skipped by the reader — see Data health.")
        assert rr.read_note("x.epc", 0, 0) == ""

    def test_a_failure_is_not_counted_among_the_skips(self):
        msgs = [_err(f"FESAPI error loading '{TMP}/j.epc': Cannot unzip x")]
        assert rr.skipped_objects(msgs) == (0, 0)


class TestUnreadableProperties:
    UUID = "0e6a0c1b-1111-4222-8333-444455556666"

    def test_missing_h5_names_the_property_and_the_file(self):
        msgs = [_err(f"Error when initialize uuid: {self.UUID}\nThe HDF5 file"
                     f" {TMP}/vector_props.h5 does not exist")]
        out = rr.unreadable_properties(
            msgs, lambda u: "poro" if u == self.UUID else "", TMP)
        assert out == ["poro could not be read: vector_props.h5 is missing —"
                       " import it too, then untick and tick the property"
                       " again."]

    def test_each_uuid_once_and_the_note_counts_the_rest(self):
        other = "0e6a0c1b-1111-4222-8333-444455557777"
        msgs = [_err(f"Error when initialize uuid: {self.UUID}\nThe HDF5 file"
                     f" {TMP}/a.h5 does not exist"),
                _err(f"Error when initialize uuid: {self.UUID}\nThe HDF5 file"
                     f" {TMP}/a.h5 does not exist"),
                _err(f"Error when load Time Series property uuid: {other}\n"
                     f"The HDF5 dataset /RESQML/{other}/values could not"
                     " be opened.")]
        titles = {self.UUID: "poro", other: "pressure"}
        out = rr.unreadable_properties(msgs, lambda u: titles.get(u, ""), TMP)
        assert len(out) == 2
        assert out[1] == ("pressure could not be read: The HDF5 dataset"
                          f" /RESQML/{other}/values could not be opened.")
        assert rr.property_note(out) == out[0] + " (+1 more — see Data health)"
        assert rr.property_note([]) == ""

    def test_an_unknown_uuid_is_named_by_its_uuid(self):
        msgs = [_err(f"Error when initialize uuid: {self.UUID}\nboom")]
        out = rr.unreadable_properties(msgs, lambda u: "", TMP)
        assert out == [f"{self.UUID} could not be read: boom"]


def test_strip_paths_handles_both_separators():
    assert rr.strip_paths("read 'C:\\Users\\me\\Temp\\tmpab12\\x.epc'",
                          "C:\\Users\\me\\Temp\\tmpab12") == "read 'x.epc'"
    assert rr.strip_paths(f"read '{TMP}/x.epc' and {TMP}/x.h5", TMP) == \
        "read 'x.epc' and x.h5"
