<template>
  <div class="bench">
    <h1>The shared component set — every state</h1>
    <p class="bench-lead">
      Built from <code>widgets/_shared/components/</code> with the widgets'
      own toolchain and production Vue: prop validation is stripped here
      exactly as in the served page, so a required prop left out shows what a
      reader would really see — a visible accusation and
      <code>data-fp-incomplete</code>, which the browser harness fails on.
      The cells marked <b>defect</b> are wrong ON PURPOSE.
    </p>

    <!-- ------------------------------------------------------- FpBtn -->
    <section class="bench-sec" data-bench="FpBtn">
      <h2>&lt;fp-btn&gt; — R15, R18, R9</h2>
      <div class="bench-row">
        <span class="bench-cell" data-state="default">
          <fp-btn label="Refresh" title="Read the loaded data again" @click="clicks += 1" />
          <em>default</em>
        </span>
        <span class="bench-cell" data-state="primary">
          <fp-btn label="Compute" variant="primary" title="Compute the volumes of the active grid" />
          <em>primary</em>
        </span>
        <span class="bench-cell" data-state="on">
          <fp-btn label="Metrics" variant="on" title="Choose the visible metrics — open" />
          <em>on</em>
        </span>
        <span class="bench-cell" data-state="icon">
          <fp-btn icon title="Show or hide this panel's property tree">T</fp-btn>
          <em>icon, glyph slot</em>
        </span>
        <span class="bench-cell" data-state="tiny">
          <fp-btn tiny label="All" title="Every metric at once" />
          <em>tiny</em>
        </span>
        <span class="bench-cell" data-state="bare">
          <fp-btn variant="bare" label="×" title="Remove PORO from the comparison" />
          <em>bare, the button a chip carries</em>
        </span>
        <span class="bench-cell" data-state="disabled">
          <fp-btn label="Copy CSV" disabled title="Copy the table as CSV — nothing to copy: the table is empty" />
          <em>disabled, and it says why</em>
        </span>
        <span class="bench-cell" data-state="busy">
          <fp-btn label="Refresh" busy title="Reading the file again" />
          <em>busy: disabled, label unchanged</em>
        </span>
        <span class="bench-cell" data-state="no-title">
          <fp-btn label="Go" title="" />
          <em>defect — an empty tooltip</em>
        </span>
        <span class="bench-cell" data-state="title-omitted">
          <fp-btn label="Go" />
          <em>defect — the prop left out: a dev build says "Missing required prop"</em>
        </span>
        <span class="bench-cell" data-state="lower-case">
          <fp-btn label="refresh" title="Read the loaded data again" />
          <em>defect — not Title case</em>
        </span>
      </div>
      <p class="bench-note">clicks: <code data-readout="clicks">{{ clicks }}</code></p>
    </section>

    <!-- ------------------------------------------------------- FpSeg -->
    <section class="bench-sec" data-bench="FpSeg">
      <h2>&lt;fp-seg&gt; — R13</h2>
      <div class="bench-row">
        <span class="bench-cell" data-state="two">
          <fp-seg v-model="seg2" :options="twoWays" title="How the same rows are read" />
          <em>two readings — <code data-readout="seg2">{{ seg2 }}</code></em>
        </span>
        <span class="bench-cell" data-state="four">
          <fp-seg v-model="seg4" :options="fourWays" title="Which case the map shows" />
          <em>four readings — <code data-readout="seg4">{{ seg4 }}</code></em>
        </span>
        <span class="bench-cell" data-state="one">
          <fp-seg v-model="seg1" :options="oneWay" title="Well" />
          <em>defect — a strip of one promises a choice it has not got</em>
        </span>
      </div>
    </section>

    <!-- ---------------------------------------------------- FpSelect -->
    <section class="bench-sec" data-bench="FpSelect">
      <h2>&lt;fp-select&gt; — R18, R1</h2>
      <div class="bench-row">
        <span class="bench-cell" data-state="bare">
          <fp-select v-model="selBare" :options="curves" title="The curve the log draws" placeholder="every curve" />
          <em>bare — <code data-readout="selBare">{{ show(selBare) }}</code></em>
        </span>
        <span class="bench-cell" data-state="labelled">
          <fp-select v-model="selNum" :options="bins" label="Bins" title="How many bins the histogram counts into" />
          <em>a word in front — <code data-readout="selNum">{{ show(selNum) }}</code></em>
        </span>
        <span class="bench-cell" data-state="mandatory">
          <fp-select v-model="selMand" :options="curves" title="The property the cross-plot puts on X" placeholder="choose a property" mandatory />
          <em>mandatory placeholder: it cannot be chosen back</em>
        </span>
        <span class="bench-cell" data-state="disabled">
          <fp-select :model-value="null" :options="none" title="The grid the slicer cuts" disabled disabled-why="no grid is loaded in this view" />
          <em>disabled, and it says why</em>
        </span>
        <span class="bench-cell" data-state="disabled-option">
          <fp-select :model-value="null" :options="withDisabled" title="The grid the slicer cuts" placeholder="choose a grid" />
          <em>one option cannot be chosen, and its tooltip says why</em>
        </span>
        <span class="bench-cell" data-state="disabled-mute">
          <fp-select :model-value="null" :options="none" title="The grid the slicer cuts" disabled />
          <em>defect — disabled without saying why</em>
        </span>
        <span class="bench-cell" data-state="wrong-shape">
          <fp-select :model-value="null" :options="curvesWrongShape" title="The curve the log draws" />
          <em>defect — {value, title}: blank rows, said nothing, until the shape was one</em>
        </span>
      </div>
    </section>

    <!-- ------------------------------------------------------- FpNum -->
    <section class="bench-sec" data-bench="FpNum">
      <h2>&lt;fp-num&gt; — the decimal rule</h2>
      <div class="bench-row">
        <span class="bench-cell" data-state="plain">
          <fp-num v-model="num" title="Water saturation cutoff, fraction" :min="0" :max="1" />
          <em>type 0,25 and leave it — <code data-readout="num">{{ show(num) }}</code></em>
        </span>
        <span class="bench-cell" data-state="clamped">
          <fp-num v-model="numClamp" title="Percentage of cells sampled" :min="1" :max="100" />
          <em>clamped to 100 — <code data-readout="numClamp">{{ show(numClamp) }}</code></em>
        </span>
        <span class="bench-cell" data-state="integer">
          <fp-num v-model="numInt" title="K index of the layer shown" integer :min="0" :max="49" size="sm" />
          <em>integer, small — <code data-readout="numInt">{{ show(numInt) }}</code></em>
        </span>
        <span class="bench-cell" data-state="stepper">
          <fp-num v-model="numStep" title="I index of the first column kept" stepper integer :min="0" :max="9" size="sm" />
          <em>stepper — <code data-readout="numStep">{{ show(numStep) }}</code></em>
        </span>
        <span class="bench-cell" data-state="stepper-at-max">
          <fp-num v-model="numMax" title="J index of the last row kept" stepper integer :min="0" :max="4" size="sm" />
          <em>at its maximum: the up step is inert</em>
        </span>
        <span class="bench-cell" data-state="nullable">
          <fp-num v-model="numNull" title="Gas-oil contact, m TVDSS — empty means none" nullable placeholder="none" />
          <em>nullable — <code data-readout="numNull">{{ show(numNull) }}</code></em>
        </span>
        <span class="bench-cell" data-state="disabled">
          <fp-num :model-value="12" title="Samples per zone — set by the file" disabled />
          <em>disabled</em>
        </span>
        <span class="bench-cell" data-state="no-title">
          <fp-num v-model="num" title="" />
          <em>defect — no tooltip</em>
        </span>
      </div>
    </section>

    <!-- ------------------------------------------------------ FpChip -->
    <section class="bench-sec" data-bench="FpChip">
      <h2>&lt;fp-chip&gt; — R10, R12, R14</h2>
      <div class="bench-row">
        <span class="bench-cell" data-state="variants">
          <span class="bench-line">
            <fp-chip text="3 objects" title="Objects read from the file" />
            <fp-chip variant="accent" text="Geogrid · PORO" title="Geogrid · PORO" />
            <fp-chip variant="warn" text="2 of 9 · 7 dropped" title="2 of 9 cells plotted — 7 dropped: no value" />
            <fp-chip variant="error" text="1 error" title="One dataset could not be read" />
            <fp-chip variant="line" text="PORO" title="PORO — click to put it on X" />
            <fp-chip variant="line" on text="PERM" title="PERM — on X" />
            <fp-chip variant="off" text="SW" title="SW — not in this comparison" />
            <fp-chip sm text="24" title="24 samples in this zone" />
          </span>
          <em>every variant, and the small badge</em>
        </span>
        <span class="bench-cell bench-narrow" data-state="ellipsed">
          <fp-chip variant="accent" :text="longTarget" :title="longTarget" />
          <em>ellipsed, whole text in the tooltip (R12)</em>
        </span>
        <span class="bench-cell" data-state="with-after">
          <fp-chip variant="line" text="PORO" title="PORO — in this comparison">
            <template #after>
              <fp-btn variant="bare" label="★" title="Make PORO the baseline" />
              <fp-btn variant="bare" label="×" title="Remove PORO from the comparison" />
            </template>
          </fp-chip>
          <em>the bare buttons a chip carries</em>
        </span>
        <span class="bench-cell" data-state="no-title">
          <fp-chip text="24" title="" />
          <em>defect — a chip with no full text behind it</em>
        </span>
        <span class="bench-cell" data-state="clickable">
          <fp-chip variant="line" text="PORO" title="PORO — in this comparison" @click="clicks += 1" />
          <em>defect — a click on a chip: no tab stop, no key handler; it is not bound</em>
        </span>
        <span class="bench-cell bench-narrow" data-state="long-warn">
          <fp-chip variant="warn" :text="longWarning" :title="longWarning" />
          <em>defect — a sentence in the warning channel is a band, not an ellipsed badge</em>
        </span>
      </div>
    </section>

    <!-- ------------------------------------------------------ FpNote -->
    <section class="bench-sec" data-bench="FpNote">
      <h2>&lt;fp-note&gt; — R10</h2>
      <div class="bench-col">
        <div class="bench-cell" data-state="warning">
          <fp-note severity="warning" :text="noteText" @close="closed += 1" />
          <em>a warning: something was held back</em>
        </div>
        <div class="bench-cell" data-state="error">
          <fp-note
            severity="error"
            text="The zones could not be recomputed: the porosity curve has no depth."
            next="pick another curve above, or load the well again"
          />
          <em>an error: it names the next step</em>
        </div>
        <div class="bench-cell" data-state="error-mute">
          <fp-note severity="error" text="The export failed." />
          <em>defect — an error with no next step</em>
        </div>
        <div class="bench-cell" data-state="info">
          <fp-note severity="info" text="Nine markers were read." />
          <em>defect — information is not a band</em>
        </div>
      </div>
      <p class="bench-note">
        <fp-btn tiny label="Change the warning's words" title="A new text is a new note: a dismissed note comes back" @click="renote" />
        dismissals: <code data-readout="closed">{{ closed }}</code>
      </p>
    </section>

    <!-- ------------------------------------------------------ FpMenu -->
    <section class="bench-sec" data-bench="FpMenu">
      <h2>&lt;fp-menu&gt; — R16</h2>
      <div class="bench-row">
        <div class="bench-cell" data-state="open">
          <div class="bench-menu-frame">
            <fp-menu inside :at="menuAtTop" title="Geogrid — Effective porosity"
                     :items="menuItems" @pick="menuPicked" @close="menuClosed += 1" />
          </div>
          <em>a title, a separator, a red entry, a disabled entry that says why</em>
        </div>
        <div class="bench-cell" data-state="flip">
          <div class="bench-menu-frame">
            <fp-menu inside :at="menuAtCorner" title="Right-clicked near the corner"
                     :items="menuItems" @pick="menuPicked" @close="menuClosed += 1" />
          </div>
          <em>right-clicked near the bottom right corner: it flips back inside</em>
        </div>
        <div class="bench-cell" data-state="empty">
          <div class="bench-menu-frame">
            <fp-menu inside :at="menuAtTop" title="Wellbore 15/9-F-12" :items="none"
                     empty-why="No action on this node." @close="menuClosed += 1" />
          </div>
          <em>nothing to offer: it still opens, and says why</em>
        </div>
        <div class="bench-cell" data-state="empty-mute">
          <div class="bench-menu-frame">
            <fp-menu inside :at="menuAtTop" title="Wellbore 15/9-F-12" :items="none"
                     @close="menuClosed += 1" />
          </div>
          <em>defect — empty, and it does not say why</em>
        </div>
        <div class="bench-cell" data-state="disabled-mute">
          <div class="bench-menu-frame">
            <fp-menu inside :at="menuAtTop" title="Geogrid — Effective porosity"
                     :items="menuMute" @close="menuClosed += 1" />
          </div>
          <em>defect — a disabled entry with no reason</em>
        </div>
      </div>
      <p class="bench-note">
        picks: <code data-readout="menu-picks">{{ menuPicks }}</code>
        last: <code data-readout="menu-last">{{ menuLast }}</code>
        asked to close: <code data-readout="menu-closes">{{ menuClosed }}</code>
      </p>
    </section>

    <!-- ------------------------------------------------- FpTransport -->
    <section class="bench-sec" data-bench="FpTransport">
      <h2>&lt;fp-transport&gt; — one transport</h2>
      <div class="bench-col">
        <div class="bench-cell bench-wide" data-state="time">
          <fp-transport unit="time step" player :index="tIndex" :count="12" :playing="tPlaying"
                        :speed="tSpeed" @step="tIndex = $event" @play="tPlaying = $event"
                        @speed="tSpeed = $event">
            <b>2026-01-{{ String(tIndex + 1).padStart(2, "0") }}</b>
          </fp-transport>
          <em>a player: play and the speed; the slider under the row</em>
        </div>
        <div class="bench-cell bench-wide" data-state="first">
          <fp-transport unit="realization" :index="0" :count="3">
            <template #lead><b>PORO</b></template>
          </fp-transport>
          <em>at the first position: the two steps back say why they are off</em>
        </div>
        <div class="bench-cell bench-wide" data-state="inline">
          <fp-transport unit="chart of this track" units="charts of this track" player slider="inline"
                        :index="1" :count="2" />
          <em>the slider in the row, before the count</em>
        </div>
        <div class="bench-cell bench-wide" data-state="no-unit">
          <fp-transport :index="0" :count="3" />
          <em>defect — it does not say what it steps through</em>
        </div>
      </div>
      <p class="bench-note">time step: <code data-readout="t-index">{{ tIndex }}</code></p>
    </section>

    <!-- ----------------------------------------------------- FpRange -->
    <section class="bench-sec" data-bench="FpRange">
      <h2>&lt;fp-range&gt; — one double slider</h2>
      <div class="bench-col">
        <div class="bench-cell bench-wide" data-state="plain">
          <fp-range :min="0" :max="100" :low="rLow" :high="rHigh"
                    @drag="(w, v) => (w === 'low' ? (rLow = v) : (rHigh = v))"
                    @commit="(w, v) => (rCommits += 1)" />
          <em>one track, two thumbs, the kept span filled</em>
        </div>
        <div class="bench-cell bench-wide" data-state="ticked">
          <fp-range :min="1" :max="4" :low="2" :high="3" :ticks="facies" />
          <em>one labelled tick per category, lit inside the kept span</em>
        </div>
      </div>
      <p class="bench-note">kept: <code data-readout="r-span">{{ rLow }} … {{ rHigh }}</code>
        commits: <code data-readout="r-commits">{{ rCommits }}</code></p>
    </section>

    <!-- ----------------------------------------------------- FpEmpty -->
    <section class="bench-sec" data-bench="FpEmpty">
      <h2>&lt;fp-empty&gt; — R8</h2>
      <div class="bench-col">
        <div class="bench-cell" data-state="full">
          <fp-empty
            shows="This panel lists the zones of the wells in the log, with their net thickness."
            gesture="Press “Refresh” to sample the grid along the trajectories."
          />
          <em>what it would show, then the gesture</em>
        </div>
        <div class="bench-cell" data-state="with-why">
          <fp-empty
            shows="This card cuts the active grid along I, J and K."
            gesture="Tick a grid in the data tree to make it active."
            why="No grid is loaded in this view yet."
          />
          <em>and why it cannot be done</em>
        </div>
        <div class="bench-cell" data-state="mute">
          <fp-empty shows="Nothing readable yet" gesture="" />
          <em>defect — it does not say what fills it</em>
        </div>
        <div class="bench-cell" data-state="gesture-omitted">
          <fp-empty shows="This panel lists the zones of the wells in the log." />
          <em>defect — the prop left out: a dev build says "Missing required prop"</em>
        </div>
      </div>
    </section>

    <!-- ---------------------------------------------------- FpExport -->
    <section class="bench-sec" data-bench="FpExport">
      <h2>&lt;fp-export&gt; — R11</h2>
      <div class="bench-row">
        <span class="bench-cell" data-state="ready">
          <fp-export
            filename="zones-2026-09-13.csv"
            :build="buildCsvText"
            title="Copy the table as CSV — the rows as filtered here, under a dated provenance header"
          />
          <em>press it: it says which of the two it did</em>
        </span>
        <span class="bench-cell" data-state="xml">
          <fp-export
            label="Copy XML"
            mime="application/xml"
            filename="geogrid-2026-09-13.xml"
            :build="buildXmlText"
            title="Copy the document as XML"
          />
          <em>the word follows the data, the verb never changes</em>
        </span>
        <span class="bench-cell" data-state="disabled">
          <fp-export
            filename="stats.csv"
            :build="buildCsvText"
            title="Copy the table as CSV"
            disabled
            disabled-why="no property is pinned, so the table is empty"
          />
          <em>disabled, and it says why</em>
        </span>
        <span class="bench-cell" data-state="failing">
          <fp-export filename="broken.csv" :build="buildThrows" title="Copy the table as CSV" />
          <em>press it: a failure is said, not swallowed</em>
        </span>
        <span class="bench-cell" data-state="lower-case">
          <fp-export label="copy csv" filename="stats.csv" :build="buildCsvText" title="Copy the table as CSV" />
          <em>defect — R11's one word, not written</em>
        </span>
      </div>
    </section>

    <!-- ------------------------------------------------------ FpIcon -->
    <section class="bench-sec" data-bench="FpIcon">
      <h2>&lt;fp-icon&gt; — the drawing of an object of the model</h2>
      <div class="bench-row">
        <span class="bench-cell" data-state="drawing">
          <fp-icon :icon="icons.gridIjk" :size="24" />
          <em>a drawing of the set, in its family colour</em>
        </span>
        <span class="bench-cell" data-state="by-name">
          <fp-icon icon="fespp-wellbore" :size="24" />
          <em>the same, named the way Python names it</em>
        </span>
        <span class="bench-cell" data-state="declared">
          <fp-icon icon="fespp-surface-tin" :size="24" declared="rgb(181,101,29)" />
          <em>the colour the FILE declares wins over the family</em>
        </span>
        <span class="bench-cell" data-state="polychrome">
          <fp-icon icon="fespp-property-categorical" :size="24" />
          <em>the one icon that IS a palette</em>
        </span>
        <span class="bench-cell" data-state="path">
          <fp-icon :icon="mdiPath" :size="24" />
          <em>a bare SVG path: how an mdi glyph arrives</em>
        </span>
        <span class="bench-cell" data-state="tree-size">
          <fp-icon icon="fespp-marker-frame" :size="15" />
          <em>15 px — the size the tree draws</em>
        </span>
        <span class="bench-cell" data-state="mono">
          <fp-icon icon="fespp-multi-realization-time-series" :size="24" mono />
          <em>mono: une barre n’a pas de familles à trier</em>
        </span>
        <span class="bench-cell" data-state="disabled">
          <fp-icon icon="fespp-blocked-wellbore" :size="24" disabled />
          <em>disabled: desaturated whole, never by colour</em>
        </span>
        <span class="bench-cell" data-state="unknown-name">
          <fp-icon icon="fespp-there-is-no-such-drawing" :size="24" />
          <em>defect — a name the set does not hold: the unknown mark, and it says so</em>
        </span>
        <span class="bench-cell" data-state="mdi-name">
          <fp-icon icon="mdi-file-tree" :size="24" />
          <em>defect — an mdi NAME: only the host's v-icon can draw those</em>
        </span>
      </div>
    </section>

    <!-- ----------------------------------------------------- FpPanel -->
    <section class="bench-sec" data-bench="FpPanel">
      <h2>&lt;fp-panel&gt; — R1, R2, R3, R9, R10, R12, R14</h2>
      <div class="bench-frames">
        <div class="bench-frame" data-state="full">
          <fp-panel
            title="Log ↔ Grid"
            title-tip="What the log says against what the grid holds, zone by zone"
            target="Geogrid · PORO"
            summary="8 of 11 zones · 3 dropped: fewer than 5 samples"
            summary-dropped
          >
            <template #controls>
              <fp-seg v-model="seg2" :options="twoWays" title="How the same rows are read" />
              <fp-select v-model="selBare" :options="curves" title="The curve compared with the grid" placeholder="every curve" />
            </template>
            <template #actions>
              <fp-btn label="Refresh" variant="primary" title="Sample the grid along the trajectories again" />
            </template>
            <template #export>
              <fp-export filename="reconcile.csv" :build="buildCsvText" title="Copy the table as CSV" />
            </template>
            <template #tree>
              <fp-btn icon title="Show or hide this panel's well tree">T</fp-btn>
            </template>
            <template #subbar>
              <fp-chip sm text="11 zones" title="Eleven zones in the current well" />
              <fp-chip sm variant="off" text="3 short" title="Three zones hold fewer than five samples" />
            </template>
            <template #notes>
              <fp-note severity="warning" text="Three zones hold fewer than five samples; they are ranked last." />
            </template>
            <table class="fp-table">
              <thead>
                <tr><th>Zone</th><th class="num">Samples</th><th class="num">Phi log</th><th class="num">Phi grid</th></tr>
              </thead>
              <tbody>
                <tr v-for="z in zones" :key="z[0]">
                  <td>{{ z[0] }}</td>
                  <td class="num">{{ z[1] }}</td>
                  <td class="num">{{ z[2] }}</td>
                  <td class="num">{{ z[3] }}</td>
                </tr>
              </tbody>
            </table>
          </fp-panel>
          <em>the whole frame: title, target, controls, summary, action, export, tree, note, sub-bar, body</em>
        </div>

        <div class="bench-frame" data-state="busy">
          <fp-panel title="Log ↔ Grid" target="Geogrid · PORO" summary="8 of 11 zones" busy>
            <template #actions>
              <fp-btn label="Refresh" variant="primary" busy title="Sampling the grid along the trajectories" />
            </template>
            <table class="fp-table">
              <thead><tr><th>Zone</th><th class="num">Samples</th></tr></thead>
              <tbody>
                <tr v-for="z in zones" :key="z[0]"><td>{{ z[0] }}</td><td class="num">{{ z[1] }}</td></tr>
              </tbody>
            </table>
          </fp-panel>
          <em>busy: the bar under the header, the summary saying so, and the table still there</em>
        </div>

        <div class="bench-frame" data-state="empty">
          <fp-panel title="Data health">
            <template #actions>
              <fp-btn label="Refresh" variant="primary" title="Read the loaded data again" />
            </template>
            <fp-empty
              shows="This panel lists what is wrong with the loaded data."
              gesture="Press “Refresh” to read the file again."
            />
          </fp-panel>
          <em>no target, no export, no tree — and an empty state naming a gesture that is on screen</em>
        </div>

        <div class="bench-frame" data-state="no-title">
          <fp-panel title="">
            <p class="bench-body">A body.</p>
          </fp-panel>
          <em>defect — a panel that does not name itself</em>
        </div>

        <div class="bench-frame" data-state="title-omitted">
          <fp-panel>
            <p class="bench-body">A body.</p>
          </fp-panel>
          <em>defect — the prop left out: a dev build says "Missing required prop"</em>
        </div>

        <div class="bench-frame" data-state="note-in-controls">
          <fp-panel title="Compare" summary="9 of 412 cells">
            <template #controls>
              <fp-note severity="warning" :text="longWarning" />
            </template>
            <template #export>
              <fp-export filename="compare.csv" :build="buildCsvText" title="Copy the table as CSV" />
            </template>
            <p class="bench-body">A body.</p>
          </fp-panel>
          <em>defect — a band in the row of controls pushes the buttons about; the frame says so</em>
        </div>
      </div>
    </section>

    <!-- ----------------------------------------------- FpHistOptions -->
    <section class="bench-sec" data-bench="FpHistOptions">
      <h2>&lt;fp-hist-options&gt; — one form for a histogram's options</h2>
      <div class="bench-col">
        <div class="bench-cell" data-state="full">
          <span class="bench-line">
            <fp-hist-options :opts="hist" @set="histSet">
              <label class="fp-check" title="An option only this host has">
                <input type="checkbox" :checked="!!hist.show_stats"
                       @change="histSet(['show_stats', $event.target.checked])" />
                <span>Stats</span>
              </label>
            </fp-hist-options>
          </span>
          <em>the two choices as strips, every option in sight; a host's own option in the slot</em>
        </div>
        <div class="bench-cell" data-state="compact">
          <span class="bench-line">
            <fp-hist-options compact :opts="hist" @set="histSet" />
          </span>
          <em>compact, for a bar that shares its width: the same words, the two choices as lists</em>
        </div>
        <div class="bench-cell" data-state="empty">
          <span class="bench-line">
            <fp-hist-options />
          </span>
          <em>a host that says nothing yet: the defaults, never a blank field</em>
        </div>
      </div>
      <p class="bench-note">last: <code data-readout="hist-last">{{ histLast }}</code></p>
    </section>
  </div>
</template>

<script>
import FpBtn from "../../../widgets/_shared/components/FpBtn.vue";
import FpChip from "../../../widgets/_shared/components/FpChip.vue";
import FpEmpty from "../../../widgets/_shared/components/FpEmpty.vue";
import FpExport from "../../../widgets/_shared/components/FpExport.vue";
import FpHistOptions from "../../../widgets/_shared/components/FpHistOptions.vue";
import FpIcon from "../../../widgets/_shared/components/FpIcon.vue";
import { FESPP_ICONS } from "../../../widgets/_shared/icons/fespp-icons.js";
import FpMenu from "../../../widgets/_shared/components/FpMenu.vue";
import FpNote from "../../../widgets/_shared/components/FpNote.vue";
import FpRange from "../../../widgets/_shared/components/FpRange.vue";
import FpTransport from "../../../widgets/_shared/components/FpTransport.vue";
import FpNum from "../../../widgets/_shared/components/FpNum.vue";
import FpPanel from "../../../widgets/_shared/components/FpPanel.vue";
import FpSeg from "../../../widgets/_shared/components/FpSeg.vue";
import FpSelect from "../../../widgets/_shared/components/FpSelect.vue";
import { buildCsv } from "../../../widgets/_shared/csvexport.js";

export default {
  name: "Gallery",
  components: {
    FpBtn, FpChip, FpEmpty, FpExport, FpHistOptions, FpIcon, FpMenu, FpNote, FpNum,
    FpPanel, FpRange, FpSeg, FpSelect, FpTransport,
  },
  data() {
    return {
      icons: FESPP_ICONS,
      // a filled glyph, the shape an @mdi/js entry has
      mdiPath: "M3 3h8v8H3V3m10 0h8v8h-8V3M3 13h8v8H3v-8m10 0h8v8h-8v-8",
      clicks: 0,
      closed: 0,
      seg1: "well",
      seg2: "table",
      seg4: "p50",
      selBare: null,
      selNum: 20,
      selMand: null,
      num: 0.5,
      numClamp: 50,
      numInt: 3,
      numStep: 5,
      numMax: 4,
      numNull: null,
      none: [],
      withDisabled: [
        { value: "geo", label: "Geogrid" },
        { value: "ijk", label: "IjkGrid", disabled: true,
          title: "IjkGrid is not loaded in this view" },
      ],
      noteText: "Nine markers were dropped: their depths sit outside the trajectory.",
      // fixed objects: a new {x, y} each render would place the menus again
      menuAtTop: { x: 16, y: 12 },
      menuAtCorner: { x: 330, y: 190 },
      menuItems: [
        { key: "dist", label: "Show distribution", title: "A histogram of this property" },
        { key: "stats", label: "Add to stats" },
        { key: "xplot", label: "Cross-plot", disabled: true,
          title: "A cross-plot needs a second property of the same grid" },
        { key: "unload", label: "Unload", danger: true, separatorBefore: true,
          title: "The grid and its properties leave every view" },
      ],
      menuMute: [
        { key: "dist", label: "Show distribution" },
        { key: "xplot", label: "Cross-plot", disabled: true },
      ],
      menuPicks: 0,
      menuLast: "",
      menuClosed: 0,
      tIndex: 4,
      tPlaying: false,
      tSpeed: 1,
      rLow: 20,
      rHigh: 70,
      rCommits: 0,
      facies: [
        { value: 1, label: "Sand", title: "Sand (1)" },
        { value: 2, label: "Shale", title: "Shale (2)" },
        { value: 3, label: "Carbon…", title: "Carbonate (3)" },
        { value: 4, label: "Coal", title: "Coal (4)" },
      ],
      longTarget: "Geogrid · Continuous property · Effective porosity at reservoir conditions",
      longWarning: "9 of 412 cells dropped: no value; 3 more are <= 0 and cannot"
        + " be drawn on a log axis; the rest are plotted.",
      twoWays: [
        { value: "table", label: "Table", title: "The zones as rows" },
        { value: "chart", label: "Chart", title: "The same zones as bars" },
      ],
      fourWays: [
        { value: "p10", label: "P10", title: "The pessimistic case" },
        { value: "p50", label: "P50", title: "The middle case" },
        { value: "p90", label: "P90", title: "The optimistic case" },
        { value: "mean", label: "Mean", title: "The arithmetic mean" },
      ],
      oneWay: [{ value: "well", label: "Well (25)", title: "The only tab" }],
      curves: [
        { value: "PORO", label: "PORO", title: "PORO - porosity" },
        { value: "PERM", label: "PERM", title: "PERM - permeability" },
        { value: "SW", label: "SW", title: "SW - water saturation" },
      ],
      bins: [
        { value: 10, label: "10", title: "Ten bins" },
        { value: 20, label: "20", title: "Twenty bins" },
        { value: 50, label: "50", title: "Fifty bins" },
      ],
      // options in the {value, title} shape, with no label: <fp-select>
      // must mark each such row as a defect rather than draw it blank
      curvesWrongShape: [
        { value: "PORO", title: "PORO" },
        { value: "PERM", title: "PERM" },
      ],
      hist: { mode: "bars", nbins: 50, log_y: false, cumulative: false, norm: "count" },
      histLast: "",
      zones: [
        ["Brent", 412, 0.213, 0.208],
        ["Ness", 96, 0.187, 0.191],
        ["Etive", 4, 0.164, 0.171],
      ],
    };
  },
  methods: {
    show(v) {
      if (v === null || v === undefined) return "null";
      return String(v) + " - " + typeof v;
    },
    menuPicked(it) {
      this.menuPicks += 1;
      this.menuLast = it.key;
    },
    renote() {
      this.closed += 1;
      this.noteText = "Eleven markers were dropped (reading " + this.closed
        + "): their depths sit outside the trajectory.";
    },
    histSet([name, value]) {
      this.hist = { ...this.hist, [name]: value };
      this.histLast = name + "=" + value;
    },
    buildCsvText() {
      return buildCsv(
        ["# zones of the wells in the log, 2026-09-13"],
        ["zone", "samples", "phi log", "phi grid"],
        this.zones,
      );
    },
    buildXmlText() {
      return "<Geogrid uuid=\"8f3c\"><Title>Geogrid</Title></Geogrid>\n";
    },
    buildThrows() {
      throw new Error("the table could not be written");
    },
  },
};
</script>

<style>
@import "../../../widgets/_shared/panel.css";
</style>

<style scoped>
.bench { font-family: var(--fp-font); font-size: var(--fp-size); color: var(--fp-ink); padding: 16px 20px 60px; background: #fafafa; }
h1 { font-size: 18px; color: var(--fp-accent); }
h2 { font-size: 13px; color: var(--fp-accent); margin: 0 0 8px; }
.bench-lead { max-width: 70ch; color: var(--fp-ink-soft); line-height: 1.5; }
.bench-sec { background: #fff; border: 1px solid var(--fp-line); border-radius: 6px; padding: 12px 14px; margin: 14px 0; }
.bench-row { display: flex; flex-wrap: wrap; gap: 18px 22px; align-items: flex-start; }
.bench-col { display: flex; flex-direction: column; gap: 10px; }
.bench-line { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.bench-cell { display: flex; flex-direction: column; gap: 4px; align-items: flex-start; }
.bench-cell em { color: var(--fp-ink-faint); font-size: var(--fp-size-small); font-style: italic; }
.bench-narrow { width: 190px; }
.bench-note { color: var(--fp-ink-mute); margin: 10px 0 0; display: flex; align-items: center; gap: 8px; }
.bench-frames { display: flex; flex-direction: column; gap: 18px; }
.bench-frame > :first-child { border: 1px solid var(--fp-line); border-radius: 4px; height: 230px; }
.bench-frame em { color: var(--fp-ink-faint); font-size: var(--fp-size-small); font-style: italic; }
.bench-body { padding: 8px; }
.bench-wide { width: 420px; align-items: stretch; }
.bench-menu-frame { position: relative; width: 360px; height: 260px; border: 1px dashed var(--fp-line); border-radius: 4px; background: #fdfdfd; }
code { background: #f2f2f2; padding: 0 4px; border-radius: 3px; }
</style>
