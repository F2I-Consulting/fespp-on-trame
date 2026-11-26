"""Widget bundles the page loads on demand, at the first opening of their
view — not at the page (S2, 21/10).

Measured on the session pool (the page served at once): 8.5 MB of
JavaScript ran before the interface showed, and Plotly alone executed
375 ms of it (43 % of the JavaScript time before the mount), for charts no
one had opened; the application's 29 widgets together executed 15 ms.

A lazy module is SERVED as before (its versioned files under
`__<package>_<version>/`) but neither its scripts nor its `vue_use` go
into the page: the trame_fespp_lazy plugin (widgets/lazy) registers each
of its component tags as a Vue async component whose loader injects the
bundle at the first render. The table of modules and tags rides with the
plugin as its options.

A widget instantiated after the server started still calls
`server.enable_module(module)`: trame then appends the scripts to
`trame__scripts`, which the client reads once, at connect — no effect, by
design. What must stay EAGER: every widget instantiated while the layout
is built (the 3D view's tool cards, the tree, the top bar, the doors)."""


def _vue_use_name(definitions, module):
    use = definitions.get("vue_use") or []
    if not use:
        raise ValueError(f"{module.__name__}: no vue_use to load on demand")
    first = use[0]
    return first[0] if isinstance(first, (list, tuple)) else first


def register(server, lazy):
    """`lazy`: [(module, [component tags])]. Serves each module, enables
    the lazy plugin with its table; returns every module this covers (for
    the www check of __main__)."""
    from trame_fespp_lazy import module as lazy_module
    table = {}
    for module, tags in lazy:
        d = module.__dict__
        server.enable_module({"serve": dict(d.get("serve") or {})})
        table[_vue_use_name(d, module)] = {
            "scripts": list(d.get("scripts") or []),
            "styles": list(d.get("styles") or []),
            "components": list(tags),
        }
    server.enable_module({"serve": dict(lazy_module.serve),
                          "scripts": list(lazy_module.scripts),
                          "vue_use": [("trame_fespp_lazy", {"modules": table})]})
    return [lazy_module] + [m for m, _tags in lazy]
