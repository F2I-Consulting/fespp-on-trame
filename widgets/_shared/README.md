# `widgets/_shared` — the vocabulary every widget writes in

Five files of style and helpers, and one folder of components.

| | what it is |
|---|---|
| `tokens.css` | the colours, inks, rules and sizes. No widget writes a colour of its own. |
| `panel.css` | the classes those tokens dress: `fp-bar`, `fp-title`, `fp-right`, `fp-sum`, `fp-btn`, `fp-chip`, `fp-seg`, `fp-sel`, `fp-num`, `fp-note`, `fp-empty`, `fp-busy`, `fp-scrim`/`fp-dialog`, `fp-table`. |
| `numfmt.js` | the one way a number is written (four significant figures, scientific outside `[1e-3, 1e6]`, thin space, a dash for a value that is not there) and read back (`parseNum` takes a typed comma). |
| `csvexport.js` | `buildCsv` and `handOver` — the clipboard, a download when the browser offers none, **and it says which of the two it did**. |
| `escape.js` | `onEscape(close)`: Escape closes what a widget has open (a popover, a picker); one listener per host, removed with it. `<fp-menu>` listens for itself. |
| `components/` | the controls themselves. |

## Why components and not only classes

A class is a look; it holds nothing. `fp-btn` was written by hand 24 times
across 9 widgets, `fp-chip` 38 times across 6, `fp-empty` 15 times across 11 —
so every rule about a control could be broken by whoever wrote that control
next, and several were. A component holds the rule in one place: a tooltip
that cannot be left out, a strip that cannot be built with one tab, a number
field that cannot be `type="number"`.

## What each component enforces

| Component | The rule it makes unbreakable |
|---|---|
| `FpPanel` | **R1** the bar is always rendered, and its order is title → target → controls → right group. **R14** the summary is the first element of that group; **R15** the action, **R11** the export and **R3** the tree button follow it, in that order, because they are slots INSIDE the frame. **R2** one title. **R12** the target, written once, as an accent chip. **R9** `busy` draws the 2 px bar and adds "recomputing…" to the summary without emptying the body. **R10** it READS its `controls` slot and accuses a note found in the row of controls. |
| `FpBtn` | **R18** one button vocabulary. **R15** the `label` validator refuses a word that does not start in Title case. **Nothing silent** — `title` is required, and a disabled button says why in it. **R9** `busy` means disabled with the label UNCHANGED. |
| `FpSelect` | **R18** one field. `title` required; `disabledWhy` required as soon as it is disabled; a per-option `disabled` carries its reason in the option's own tooltip. Option shape `{value, label, title?, done?}` (`done`: the option's result is already there, a green ✓ before its words). Always its chevron (`panel.css`); with nothing to choose (one option a reader can take, already the value, no greyed one) it is the option's words, `.fp-sel-one`, no list. |
| `FpSeg` | **R13** two to four exclusive readings of the same data — a strip of one (a control promising a choice it has not got) and a strip of five (that is a list) are both refused. Same option shape as `FpSelect`. |
| `FpNum` | The decimal rule: **never `<input type="number">`**, which Chromium writes and reads in the browser's locale. Text field with a decimal keypad, `numfmt.fmtExact` writes the value back with every digit it has (a typed 1250.5 is never shown as 1251), `parseNum` reads a typed comma, and the clamp / the rounding / the refusal all snap the field back visibly on `change`. |
| `FpColorPicker` | The palette, open: saturation x brightness, hue, opacity, `#rrggbb`; reports on release. |
| `FpColorSwatch` | A colour in a list or a row: a swatch opening that palette over the page, never clipped. |
| `FpNumPick` | A number typed or picked among values offered: the list opens at the first click. |
| `FpProgress` | **THE wait of the application, no other is drawn**: what is waited for (`label`), the kit's bar, what can be done about it (slot). It runs while the length is unknown and fills when it is known (`value`, 0 to 100; `done` when it ended well). The page's pill writes the same classes (`fespp_on_trame/__main__.py`). |
| `FpChip` | **R10** the information channel. **R12** `title` required and carrying the FULL text of what the chip ellipses. **R14** `warn` is the summary's form when something was dropped — and it is held to 60 characters, past which a warning is a sentence and belongs in a band. It emits no click, and a click listener a host puts on it is REFUSED rather than bound — a `<span>` with a click handler is a control the keyboard skips; something to press goes in the `after` slot as an `<fp-btn variant="bare">`, and the chip says in its tooltip that it dropped the listener. |
| `FpNote` | **R10** a band, full width, under the bar. Two severities, `warning` and `error`; a validator refuses "info" (information is the summary or a chip). An error names the next step. Every band carries a ×. Dismissal is keyed on the note's own TEXT, so a host never clears a note and therefore never clears it on the next refresh; a new text is a new note. |
| `FpEmpty` | **R8** `shows` and `gesture` are both required, in that order, and `why` comes third. The gesture quotes the exact words of a control, and the browser sweep reads those words back and looks for them on screen in the same panel. |
| `FpMenu` | **R16** the one right-click menu (the data trees, the 3D view, Statistics). `title` (what it acts on) and `items` are required; an empty menu still opens, with `emptyWhy` as its one disabled line; a disabled entry keeps its reason in its tooltip (`aria-disabled`, never `disabled`, which would hide the tooltip). An entry's `icon` ("fespp-<name>" drawn by `FpIcon`, "mdi-<name>" by `v-icon`) stands in a column of its own, the words aligned with or without one. It asks to close on Escape and on a click or a right-click beside it, flips back from the right and bottom edges of its frame (the viewport, or with `inside` the 3D view it is drawn in), and scrolls past 60 % of that frame. A pick is the host's to act on: it clears `at` as it acts. |
| `FpTransport` | One transport (the Time / Realization card): first, previous, play or stop (a `player`), next, last, the speed (a `player`: the same five speeds everywhere), the host's slot (a label, an index picker), the position "n / count"; the slider under the row or in it (`slider`). A step that is off says why; the slider moves on RELEASE, one read per gesture. `unit` (what one position is) is required. It counts positions: a host with sparse indices maps them back. |
| `FpRange` | **The slider, no other is drawn**: one value (`single`: an opacity, a position, the exaggeration of a view) or a span (Thresholds, Slicers): one track, two thumbs, the kept span filled, the thumb on its side of the middle kept on top so two thumbs pushed together can be pulled apart; `drag` on every position (a live preview), `commit` on release; `ticks` put one labelled tick per category under the track. Clamping stays the host's. |
| `FpHistOptions` | **One form** for a histogram's options, wherever one is drawn: the shape, the bins, Log Y, Cumulative, what a class's height means. The words and tooltips are written here, so two panels cannot read differently; the eslint gate refuses a `.cumulative` bound by hand in a widget. `opts` in, `set` `[name, value]` out; `compact` for a bar that shares its width (the two choices as lists, not strips); an option only one host has goes in the slot. |
| `FpExport` | **R11** one word ("Copy CSV", "Copy XML" — the verb never changes), one place (the panel's `export` slot), one behaviour (`csvexport.handOver`, and it says which of the two it did, in place of the label). A table with nothing to hand over keeps its button, disabled, with `disabledWhy`. A failure is said, not swallowed. |

## How they are wired

Imported **by relative path**, registered **locally** in each widget's
`components: {}`:

```js
import FpBtn from "../../../_shared/components/FpBtn.vue";
```

There is no runtime-shared package on purpose: registering base components
globally would put a load order between widget bundles (the `www` bake and the
eager-import rule) and break the smoke harness, which mounts bundles one at a
time. A few KB duplicated per bundle is the accepted price.

Two packages are runtime ones all the same, and neither registers a base
component: `widgets/icon` (`<fp-icon>` for the layout the application
builds itself) and `widgets/lazy` (`trame_fespp_lazy`, in the page from the
start, which registers the tags of the bundles loaded on demand as Vue async
components — `app/core/lazy_modules` says which; a bundle loaded that way
is installed on a shim that collects its components, so the load order
between bundles stays what it was).

**No component carries a `<style>` block.** They emit `fp-*` classes only, so
the look keeps one source: the widget's own

```css
<style>
@import "../../../_shared/panel.css";
</style>
```

in a NON-scoped block — a scoped one rewrites `:root` and loses the custom
properties. That sheet is inlined into every bundle, so **an edit to
`panel.css` means rebuilding every widget that imports it**, not only the one
being worked on; otherwise the same sheet ships at two versions in the same
page and the winner for the next edit is widget load order.

## Adding a component

1. It must hold a RULE that a class cannot. A component that is only a shape
   is a class.
2. `inheritAttrs: false` and `v-bind="$attrs"` on the root, so a host can
   still put a class or a test hook on it.
3. Whatever the rule requires is a **required prop with a validator** — and,
   because the production build of Vue strips validators, also an
   `incomplete()` computed that raises `data-fp-incomplete` and renders a
   **visible accusation** (in the tooltip, or in place of the missing words).
   Three catches, in this order: the declaration (a development build warns),
   the attribute, the harness assertion.
4. Add every state to the bench, `tests/browser/fixtures/Gallery.vue`,
   **including the states that are defects on purpose** — a component nobody
   has rendered is not delivered — and the matching lines to
   `tests/browser/probes/components.mjs`:
   `node fixtures/build.mjs && node probes/components.mjs` from
   `tests/browser`.
5. Add the invariant to `tests/browser/specs/04c-components.spec.mjs`, which
   sweeps the running application, and a rule to
   `widgets/.eslintrc.widgets.json` that refuses the hand-written SHAPE the
   component replaces — the tag, the class written by hand, and the binding
   that reaches the same thing with a colon.
6. `sh widgets/lint.sh`, then `npm run build` in every widget you touched.
