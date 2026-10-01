# trame-fespp-icon

The one exception to the rule written in `widgets/_shared/README.md` — "there
is no runtime-shared package on purpose".

That rule is about BASE COMPONENTS: registering buttons, chips and panels
globally would put a load order between widget bundles, and the smoke harness
mounts them one at a time. This module registers ONE component, `<fp-icon>`,
and it exists for a place no widget covers: the application's **own layout**.
The top bar is built in Python with Vuetify buttons, and a Vuetify button takes
its icon as a PROP — a name, never markup — so a button that must draw an
object of the model (a stratigraphic column, a log track, a well against a
grid) has nowhere to put a drawing.

What keeps it honest:

* it ships no stylesheet and matches no class, so it cannot fight another
  bundle's sheet;
* a widget that needs the icon still imports `_shared/components/FpIcon.vue`
  at build time, as every widget does — this module is for the LAYOUT only,
  never a way for one widget to borrow another's components;
* the browser suite mounts the bundles the way it always did, and scenario
  04c fails on a hyphenated tag left in the DOM, which is exactly what an
  unregistered `<fp-icon>` would leave.

The drawings themselves live in `widgets/_shared/icons/fespp-icons.js`.
