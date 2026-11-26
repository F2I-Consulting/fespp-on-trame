# Widget: Import dialog (global)

Loads files into the **shared** data layer. One instance, view-independent.

## Scope
Global.

## Input
- User gestures: file upload (drag/drop + file dialog), remote URL list, OSDU/ETP
  connection params (URL, data partition, token, proxy).

## Behaviour
- Tabs:
  - **Files** — upload local EPC/HDF5, or fetch remote URLs.
  - **OSDU** — ETP connect + dataspace browse. *(This tab is a candidate for the
    optional, licensed plugin — see the OSDU extraction discussion: a panel-kind
    registry + plugin loader keeps it out of the open-source build.)*
- On import: download / connect → `load_epc_file(path)` → the `Collector` adds the
  EPC → the assembly tree is (re)built.

## Reads
- Upload progress state, the `osdu_*` form fields, `import_tab`.

## Writes (back-end / global)
- **[session]** `file_loaded`, the loaded files, and the assembly tree
  (`ui_subtree_reservoir/surface/well`). Triggers tree (re)build.
- Does **not** touch any per-view state — newly loaded nodes start unloaded /
  unchecked; each view chooses what to load (checkbox) and show (eye).

## Notes / open
- This is the entry point of the **shared** layer. Everything downstream (which
  nodes are loaded, shown, coloured) is decided per the tree's checkbox/eye
  semantic, not here.
- The OSDU/ETP connector relies on the C++ `ETP12Store`; the licensed split
  gates the Python tab + orchestration.
