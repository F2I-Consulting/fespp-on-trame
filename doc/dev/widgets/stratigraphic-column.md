# Widget: Stratigraphic column

The stratigraphic column of the loaded data set — units in stratigraphic
order, each a coloured band, with the chronostratigraphic bracket the file
declares. Packaged widget — `widgets/stratigraphy`
(`trame_fespp_stratigraphy`), plain HTML + scoped CSS.

**Index 0 is the TOP of the column** — the shallowest, youngest unit. A
vertical flex box lays the first child out at the top, so the file order is
already the display order; reversing it (as the first version did) puts the
oldest on top, which is upside down for any geologist.

## What it draws, and why not a list
A flat list of the 385 boundaries is unreadable and was rejected on sight.
The card draws a **chart of nested columns**, the way a chronostratigraphic
chart is drawn: the group is one tall rectangle whose height is the height
of its children, and its formations sit in the column BESIDE it, not under
it. Groups stack youngest to oldest; the group name reads bottom-up in its
rectangle, as in the Eon / Era columns of the ICS chart.

Three detail levels (Groups / + Formations / All) plus a filter, because
"All" is still 199 entities.

**Heights are proportional to the CHILD COUNT, not to age or thickness** —
the equivalent of the ICS chart's "equal rows" scaling. A proportional
chart needs absolute ages, and those are absent from every EPC on hand
(measured: 0 of 768 Volve boundary features carry one).

## Entities, not boundaries
The file lists BOUNDARIES (`X_ Top` and `X_ Base` as two separate units).
`_entities_of` collapses them into one band per thing: 385 boundaries →
199 entities on Volve.

Nesting is **derived from the naming convention** (`GP_` / `Fm_` / `Mb_`),
each entity hanging off the smallest group whose index span covers it. The
first attempt inferred nesting from generic interval containment and
produced a meaningless 110-deep staircase, because this file's Top/Base
spans partly OVERLAP (`HORDALAND GP_ Top` precedes `NORDLAND GP_ Base`).
The result was checked against real geology: Utsira in Nordland, Hugin in
Viking, Smith Bank in Hegre, 0 orphans.

## The band on the well log
`intervals_for_tops` lays the column onto ONE well's depth axis, and
`welllog_dispatch` puts it in each well's payload as `strati`; the D3
renderer draws it as a coloured gutter left of the depth axis
(`LAYOUT.stratiW`), name rotated, bold for groups.

It works because a well's MARKER titles ARE the column's boundary titles —
so no array is read from the HDF5 and no C++ is needed; the depths come
from the markers FESPP already exposes.

The intervals are built from a **stack of open entities**, not one interval
per Top: below the base of a formation you are still inside its group, and
a pick the column does not know must not blank the rock around it. The
first version emitted one interval per Top and left the band riddled with
gaps.

## Scope
Per-view tool card (`strati`), but the DATA is session-wide: the column
belongs to the loaded files, not to a view. Only the highlighted unit is
per-view.

## Why the column is parsed in Python, not read from FESPP
Two independent reasons, both verified:

- **FESPP maps geometry only.** `grep -r Stratigraphic` over its `Plugin/`
  returns nothing. That is structural: in RESQML the stratigraphy lives in
  the INTERPRETATION layer, which has no dataset, so the plugin's
  "object → VTK dataset" architecture has no slot for it.
- **fesapi does not wrap the field that matters.** A unit's
  `ChronostratigraphicTop` / `Bottom` — the only thing in the file that can
  ever be joined to a chart — has no getter in fesapi's
  `StratigraphicUnitFeature.h`; the name appears only in the generated gsoap
  proxies. The XML has it.

So `engine/stratigraphy.py` reads the EPC zip parts directly: stdlib only,
no fesapi, no HDF5, no ParaView, and no C++ to rebuild.

## The resolution chain (verified on Volve)
```
StratigraphicColumnRankInterpretation
  → StratigraphicUnits[Index].Unit          ordered, by Index
    → StratigraphicUnitInterpretation
      → InterpretedFeature
        → StratigraphicUnitFeature          title, colour, chrono bracket
```
The chain must be walked to the END: the interpretation is routinely titled
`|UNNAMED|` (SKUA), and the readable name, the colour and the chrono
bracket all live on the feature.

## Measured on the real files
| file | RESQML | columns | units | colour from file | chrono bracket |
|---|---|---|---|---|---|
| Volve (4 EPCs) | 2.0.1 | 1 | 385 | 385 | 385 (see below) |
| Drogon (synthetic) | 2.0.1 | 1 | 5 | 0 | 3 |
| testingPackageCpp | **2.2** | 3 | 1 / 2 / 3 | 0 | 0 |
| ALK | 2.0.1 | 0 | — | — | — |

**The chrono count overstates what is usable.** Volve has a bracket on all
385 units, but on 384 of them the reference is the unit's OWN boundary
name ("NORDLAND GP_ Top" on the unit called "NORDLAND GP_ Top"), which says
nothing a chart could join. The widget therefore shows the bracket only
when it DIFFERS from the unit title.

**Both RESQML generations are handled**, and they differ in three places at
once — a fix to any one alone still yields nothing:
- part naming: `obj_<Type>_<uuid>.xml` (2.0.1) vs
  `namespace_resqml22/<Type>_<uuid>.xml` (2.2, no `obj_`);
- the unit entry: 2.0.1 wraps the reference in `<Unit>` and carries
  `<Index>`; in 2.2 `StratigraphicUnits` IS the reference and has no index,
  so document order is the order;
- the reference's uuid element: `UUID` (2.0.1) vs `Uuid` (2.2), and
  `Index`/`OrderingCriteria` become
  `RankInStratigraphicColumn`/`AscendingOrderingCriteria`.

Drogon carries no colour, which is why the engine generates a deterministic
muted ramp and marks it `color_source: "generated"` — the column has to stay
readable on synthetic files, and the UI has to be able to say the shade is
not the file's.

## Two traps worth keeping
- **`OrderingCriteria = age` does NOT mean the units are chronostratigraphic.**
  Volve's rank says `age` and its units are lithostratigraphic reservoir
  zones (NORDLAND GP, Utsira Fm). fesapi's `isAChronoStratiRank()` only
  tests that flag. Treat it as a sort hint; never surface it as a
  chrono/litho classification.
- **The collector's `Files` property holds ONE path.** `Collector.add_file`
  does `SetPropertyWithName("Files", path)`, so it is the last file only,
  while the C++ repository keeps them all. Anything re-reading the zips
  needs its own list — `boot._loaded_epcs`. A data set routinely ships as
  several files (Volve is four).

## Reads / writes
- Reads `ui_strati_columns`, `ui_strati_selected` **[session]** and
  `ui_strati_titles[view_id]` **[per-view]**.
- Writes nothing directly: `select` sets the shown column, `pick` calls
  `controller.strati_pick` which toggles this view's highlighted unit.

## Not done yet
- **The ICS binding.** The chrono bracket is a pair of BOUNDARY TITLES, and
  on Volve those are a mix of real chart stages (Callovian, Oxfordian,
  Danian), real formations (Hugin Fm) and internal codes (JZP24A). The join
  key is that bracket, never the unit name — a formation name is
  lithostratigraphic and will never appear in a chronostratigraphic chart.
- ~~**ETP.**~~ Done through the reader's query channel (`engine/repo_query`,
  spec in `doc/private/fesapi-query-channel.md`): `ObjectUuids` lists the
  rank interpretations, `ObjectXml` returns `serializeIntoString()` of every
  object the column touches, batched by stage (three round trips for
  Volve, not 771). Same source over EPC and ETP; the zip parser stays as
  the fallback for a plugin build that predates the channel. Two
  behaviours to know: a unit whose object is a reference stub (the common
  case over ETP outside the fetched dataspace) keeps its name but has no
  colour and no chrono bracket; and fesapi demotes a WHOLE rank to a stub
  over one reference it cannot wrap — the card then says so instead of
  "no column in the data". RESQML 2.2 has no chrono bracket in its schema
  at all, which no channel can recover.
- Colouring the 3D grid by unit: Drogon's IjkGrid carries
  `IntervalStratigraphicUnits` (per-K-layer indices) in the `.h5`, which
  needs `getIntervalStratigraphicUnitIndices` on the C++ side.
