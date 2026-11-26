"""app.views.widgets — self-contained per-view panel widgets.

Every widget module here owns its UI construction, seeds its own state vars
and documents an explicit contract (Input · Behaviour · Reads · Writes) in its
docstring. Callbacks that depend on the engine path are INJECTED — a widget
never reaches into another module's globals. Wiring stays in the thin
``tools_config`` / ``boot`` layers.
"""
