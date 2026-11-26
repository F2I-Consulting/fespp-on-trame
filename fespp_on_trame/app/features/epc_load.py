"""EPC load

(Moved out of app/boot, overhaul slice 10.)"""
import os
import re
import zipfile
from fespp_on_trame.engine import etp
from fespp_on_trame.engine.vtk_log import capture_vtk_messages


def register(core, *, _publish_globe_availability, _refresh_assembly_xml):
    """Wire the section's controllers and watchers; hands back what
    the rest of the app still calls (nothing)."""
    # the shared services (app/core/context.Core)
    state = core.state
    controller = core.controller
    tree = core.tree
    collector = core.collector
    etp_connector = core.etp_connector
    # --- EPC load ---
    @controller.set("update_data_information")
    def update_data_information():
        # Called by Collector.add_file once the EPC is read.
        with capture_vtk_messages(state):
            etp.update_data_information(etp_connector, collector, tree, core.active_data_source)
            _refresh_assembly_xml()
            _publish_globe_availability()
            # the stratigraphic column is read through the reader (fesapi); it
            # is stale now, and rebuilt only when a view draws it (under ETP
            # its objects stay on the store until then)
            controller.stratigraphy_on_demand()

    def _lattice_grid_held(epc_file_path):
        """The file holds a lattice grid the tree holds already (a velocity
        model saved, then imported again). The reader dies on that one, where
        any other object read twice just adds nothing."""
        try:
            with zipfile.ZipFile(epc_file_path) as z:
                for part in z.namelist():
                    grid = re.search(r"IjkGridRepresentation_([0-9a-fA-F-]{36})\.xml$", part)
                    if (grid and tree.find_node_id_by_uuid(grid.group(1)) is not None
                            and b"Point3dLatticeArray" in z.read(part)):
                        return True
        except (OSError, zipfile.BadZipFile) as exc:
            print(f"[fespp] load_epc_file: its parts not listed ({exc})", flush=True)
        return False

    @controller.set("load_epc_file")
    def load_epc_file(epc_file_path):
        # No list of loaded paths is kept: nothing re-reads the files.
        # Everything RESQML comes from the reader's repository through the
        # query channel, which answers the same over a local EPC and over
        # ETP, where there is no file to list at all.
        name = os.path.basename(epc_file_path)
        report = {"name": name, "failure": "", "note": ""}
        if _lattice_grid_held(epc_file_path):
            print(f"[fespp] journal load: {name} holds a lattice grid already read, not read again", flush=True)
            return report
        try:
            with capture_vtk_messages(state) as read_msgs:
                state.file_loaded = collector.add_file(epc_file_path)
        except Exception as exc:
            print("[fespp] load_epc_file error:", exc, flush=True)
            report["failure"] = f"Failed to read {name}: {exc}"
            state.load_error = report["failure"]
            return report
        # The reader LOGS what went wrong rather than raising it, and at
        # the same level for two different things: the WHOLE file refused
        # (not an EPC, a part fesapi cannot deserialize) and ONE object it
        # could not map, skipped so the rest still loads. Only the first is
        # a failure and goes red; the skips are counted on the amber note
        # the import endpoint composes, with Data health as the next step.
        from fespp_on_trame.engine.io import read_report
        from fespp_on_trame.engine.io.temp_dir import temp_dir
        failure = read_report.file_failure(read_msgs, name, temp_dir)
        if not failure and not state.file_loaded:
            # the collector raised (and wrote the reason itself)
            failure = state.load_error or f"Failed to read {name}."
        if failure:
            report["failure"] = failure
            state.load_error = failure
        else:
            report["note"] = read_report.read_note(
                name, *read_report.skipped_objects(read_msgs))
        return report

    @state.change("load_error")
    def _on_load_error(load_error=None, **_):
        # The engine writes only the text (collector/vtk_log/upload); pulse
        # the visibility so repeated identical errors re-open the snackbar.
        if load_error:
            state.load_error_visible = False
            state.load_error_visible = True
