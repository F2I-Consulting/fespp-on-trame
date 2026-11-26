# trame-fespp-lazy

The widget bundles the page loads on demand, at the first opening of their
view, instead of at the page.

The server (`fespp_on_trame/app/core/lazy_modules.py`) serves a lazy
module's files as before but keeps its scripts out of the page, and hands
this plugin a table `{vue_use name: {scripts, styles, components}}`. The
plugin registers every component tag of the table as a Vue async component:
at the tag's first render the bundle is injected and its plugin installed
on a shim that collects its components.

Measured on 21/10, before: 8.5 MB of JavaScript run before the interface
showed, Plotly alone 375 ms of it, for charts no one had opened.

No Python widget class: the package only carries the bundle and its
`module`.
