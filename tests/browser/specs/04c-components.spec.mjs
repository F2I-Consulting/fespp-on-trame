/*
 * Scenario (l): the invariants the shared components exist to hold.
 *
 * It sweeps every panel of the top bar and every tool card of the 3D view,
 * then reads the WHOLE document once and holds it to the charter's rules —
 * the ones that live in a component's markup rather than in a widget's:
 *
 *   1  no hyphenated tag left in the DOM (a component used but not
 *      registered leaves its tag verbatim; the production build of Vue says
 *      nothing about it)
 *   2  an .fp-empty says what it would show and the gesture that fills it
 *   3  a control quoted in that gesture is on screen in the same panel, or
 *      in the top bar when the sentence sends the reader there
 *   4  a note carries a severity and a ×, and an error names the next step
 *   5  a .fp-btn carries a tooltip, disabled ones included, and its label is
 *      in Title case
 *   6  where a right group exists, the summary opens it and the tree button
 *      closes it
 *   7  a segmented control never holds fewer than two readings
 *   8  no input[type=number] anywhere in the application
 *   9  at most one confirmation dialog, and it belongs to the layout —
 *      never to a panel or a card
 *  10  no note inside a row of controls, where a band that grows pushes
 *      the buttons along the bar, out from under the reader's pointer
 *  11  nothing left marked busy once the sweep has settled
 *  12  the options of a histogram say the same words wherever one is drawn
 *
 * THE LEDGERS. A rule that some markup is known to break carries the list of
 * those breaks, rather than asserting nothing (a green test that checks
 * nothing is worse than no test): the run fails if anything else appears.
 * The lists are the running-application side of the exemptions in
 * widgets/.eslintrc.widgets.json, which hold the same rules in the source.
 * The verdict is "nothing OFF the ledger": which panels a pass has open
 * depends on the scenarios run before it, so a line not met is printed
 * rather than failed, and a line that is never met again is a line to strike
 * off. A ledger only ever shrinks.
 */
import {
  test, expect, M, DATASET, clickTopBar, ensureProperty, focusRenderView, state, viewId,
} from '../lib/app.mjs';
import { MODE_KEYS } from '../lib/markers.mjs';

/* A tool button of the VISIBLE toolbar, found BY ITS TOOLTIP. The panels
 * swept below include "New 3D view", so the page ends up holding a second
 * view: a button counted by position may sit in a strip that is not the one
 * on screen, or in a view that offers a different set of tools. A tooltip
 * names the tool wherever it sits. */
function toolBtn(page, title) {
  return page.locator(M.toolbar + ':visible').first()
    .locator('.tb-btn[title=' + JSON.stringify(title) + ']');
}

/* Everything the sweep reads off the page, in one pass. */
function readInvariants(page) {
  return page.evaluate((m) => {
    const text = (e) => (e.innerText || e.textContent || '').replace(/\s+/g, ' ').trim();
    // the panel or card an element belongs to, by the name the reader sees
    const host = (e) => {
      const box = e.closest(m.card + ', ' + m.dockPart);
      if (!box) return '(loose)';
      const named = box.querySelector(m.cardTitle) || box.querySelector(m.title);
      if (named) return text(named);
      // a panel that does not name itself (R2) is named here by the root
      // class of the widget drawing it - fxp, fxv, fst - so the ledger below
      // says WHICH one
      for (let n = e; n && n !== box.parentElement; n = n.parentElement) {
        const own = [...n.classList].find((c) => /^(f[a-z]{2}|wlc)$/.test(c));
        if (own) return '(' + own + ')';
      }
      return '(unnamed)';
    };
    const all = (sel) => [...document.querySelectorAll(sel)];

    return {
      tags: [...new Set(all('*').map((e) => e.tagName.toLowerCase())
        .filter((t) => t.includes('-')))],

      incomplete: all('[data-fp-incomplete]').map((e) => host(e) + ' · ' + e.className),

      empties: all(m.empty).map((e) => ({
        host: host(e),
        classes: e.className,
        shows: (e.getAttribute('data-fp-shows') || '').trim(),
        gesture: (e.getAttribute('data-fp-gesture') || '').trim(),
        words: text(e),
        // what the sentence quotes, and whether those words are on screen in
        // the same panel — or in the top bar, when the sentence sends the
        // reader there: R8's half that no prop can enforce
        quoted: (text(e).match(/[“‘]([^”’]{1,60})[”’]/g) || [])
          .map((q) => q.slice(1, -1))
          .filter((q) => {
            const boxes = [e.closest(m.card + ', ' + m.dockPart)];
            if (/top bar/i.test(text(e))) boxes.push(document.querySelector('header'));
            return !boxes.some((b) => b && text(b).includes(q));
          }),
      })),

      notes: all('.fp-note').map((e) => ({
        host: host(e),
        severity: e.getAttribute('data-fp-severity') || '',
        cross: !!e.querySelector('button'),
        next: (e.getAttribute('data-fp-next') || '').trim(),
        words: text(e).slice(0, 60),
      })),

      buttons: all('.fp-btn').map((e) => ({
        host: host(e),
        label: text(e),
        title: (e.getAttribute('title') || '').trim(),
      })),

      rights: all(m.right).filter((e) => e.children.length).map((e) => ({
        host: host(e),
        first: e.firstElementChild.className,
        last: text(e.lastElementChild) || e.lastElementChild.className,
        treeLast: !e.querySelector(m.treeToggle)
          || e.querySelector(m.treeToggle) === e.lastElementChild,
        sumFirst: !e.querySelector('.fp-sum')
          || e.querySelector('.fp-sum') === e.firstElementChild,
      })),

      segments: all('.fp-seg').map((e) => ({
        host: host(e), count: e.querySelectorAll('.fp-segbtn').length,
      })),

      numberFields: all('input[type=number]').map((e) => host(e) + ' · ' + e.className),

      // R10: a band belongs under the bar, not in the row of controls
      notesInBar: all(m.bar + ' .fp-note').map(
        (e) => host(e) + ' · ' + (e.getAttribute('data-fp-severity') || 'no severity')),

      // a control still marked busy once everything has settled is a panel
      // that never came back
      busy: all('[data-fp-busy]').map((e) => host(e) + ' · ' + (text(e) || e.className)),

      histOptions: all('.fp-hist-options').map((e) => ({
        host: host(e),
        words: [...e.querySelectorAll('label')].map(text),
      })),

      scrims: all(m.scrim).length,
      // a dialog a widget re-created behind its own v-if would live inside
      // that widget; the layout's is a child of the page
      dialogsOwnedByAWidget: all(m.dialog)
        .filter((e) => e.closest(m.dockPart + ', ' + m.card))
        .map((e) => host(e)),
    };
  }, M);
}

/*
 * The ledgers: what is known to break a rule. A line names a widget on an
 * exemption list of widgets/.eslintrc.widgets.json, or a panel written in
 * Python, which the eslint gate cannot reach at all.
 */
const LEDGER = {
  // every empty state says what it would show and the gesture that fills
  // it: the widgets through <fp-empty>, the well log's placeholder (Python,
  // over a D3 canvas that cannot mount empty) through the same two
  // attributes
  empties: [],
  // every .fp-btn says what it does and is written in Title case
  buttons: [],
  // a precondition is not a warning: it is the why of an empty state, never
  // an amber band
  notes: [],
  // none in the DOM of this sweep: the number fields of the slicers, the well
  // log and a histogram's bins are drawn only once a grid, a well or a histogram
  // is in play, which this pass does not reach. The eslint gate holds those;
  // this line holds the rest.
  numberFields: [],
};

test('the components hold their invariants across every panel and card',
  async ({ app }) => {
    const { page, note } = app;
    await ensureProperty(app, DATASET.properties[0]);

    // every panel of the top bar, left open: dockview keeps a panel that is
    // not in front in the DOM, so one read at the end sees them all. What
    // this pass opens, this pass closes: the session is shared with every
    // scenario after it, and a multi-instance kind (a 3D view, an XML tab)
    // opens a SECOND panel when a later scenario presses the same button;
    // a few extra panels are enough to hide the render view's toolbar.
    const tabsBefore = await page.locator(M.dockTab).evaluateAll(
      (els) => els.map((e) => (e.innerText || '').trim()));
    // a greyed panel button says why and opens nothing (28/10): skipped
    const panels = await page.locator(M.topBarButton + '[title]').evaluateAll(
      (els) => els.filter((e) => !e.disabled)
        .map((e) => e.getAttribute('title'))
        .filter((t) => t && !/^(reload|import|session|about)/i.test(t)));
    for (const title of panels) {
      // some buttons ASK before they open anything: the helper answers
      await clickTopBar(page, title);
      await page.waitForTimeout(700);
    }
    note('panels swept: ' + panels.length);

    // then every tool card of the 3D view
    await focusRenderView(page);
    const vid = await viewId(page);
    const tools = (await state(page, 'view_tools_' + vid)) || [];
    const opened = [];
    for (const tool of tools) {
      if (MODE_KEYS.includes(tool.key)) continue;
      // a tool the host sends OFF (its precondition fails, and its tooltip
      // says why rather than the button vanishing) opens no card
      if (tool.disabled) continue;
      const already = ((await state(page, 'ui_open_tools_by_view'))[vid] || [])
        .includes(tool.key);
      if (already) continue;
      if (!(await toolBtn(page, tool.title).count())) continue;
      await toolBtn(page, tool.title).click();
      opened.push(tool.title);
      await page.waitForTimeout(250);
    }
    note('cards opened: ' + opened.length);

    const seen = await readInvariants(page);
    note(seen.empties.length + ' empty state(s), ' + seen.notes.length + ' note(s), '
      + seen.buttons.length + ' shared button(s), ' + seen.segments.length
      + ' segment(s), ' + seen.rights.length + ' right group(s)');

    // put the session back BEFORE the first verdict: a failing assertion
    // must not leave a stack of panels open for the scenarios after it.
    for (const title of opened.reverse()) {
      await toolBtn(page, title).click();
      await page.waitForTimeout(150);
    }
    const leftOver = await page.evaluate(([before, m]) => {
      const label = (tab) => ((tab.querySelector('.dv-default-tab-content')
        || tab).innerText || '').trim();
      const known = [...before];
      const extra = [];
      for (const tab of document.querySelectorAll(m.dockTab)) {
        const seat = known.indexOf(label(tab));
        if (seat >= 0) { known.splice(seat, 1); continue; }
        const close = tab.querySelector(m.dockTabClose);
        extra.push(label(tab) + (close ? '' : ' (no close button)'));
        if (close) close.click();
      }
      return extra;
    }, [tabsBefore, M]);
    await page.waitForTimeout(700);
    await focusRenderView(page);
    const tabsAfter = await page.locator(M.dockTab).evaluateAll(
      (els) => els.map((e) => (e.innerText || '').trim()));
    note('panels this pass opened and closed again: '
      + (leftOver.join(', ') || 'none'));
    expect(tabsAfter.length,
      'the sweep left dockview panels behind: ' + tabsAfter.join(', '))
      .toBe(tabsBefore.length);

    // what each rule holds against, all read before the first verdict: one
    // run then tells the whole story instead of the first line of it
    const mute = [...new Set(seen.empties.filter((e) => !e.shows || !e.gesture)
      .map((e) => e.host + ' · ' + e.classes))].sort();
    const missing = seen.empties.filter((e) => e.quoted.length)
      .map((e) => e.host + ' names ' + e.quoted.join(', ') + ', which is not there');
    const noteFaults = [...new Set(seen.notes.filter((n) => !n.severity || !n.cross
      || (n.severity === 'error' && !n.next))
      .map((n) => n.host + ' · ' + (n.severity || 'no severity')))].sort();
    const badButtons = [...new Set(seen.buttons
      .filter((b) => !b.title || (b.label && /^[a-z]/.test(b.label)))
      .map((b) => b.host + ' · "' + (b.label || '(glyph)') + '"'
        + (b.title ? '' : ' — no tooltip')))].sort();
    const rightFaults = seen.rights.filter((r) => !r.treeLast || !r.sumFirst)
      .map((r) => r.host + ' · first ' + r.first + ', last ' + r.last);
    const thin = seen.segments.filter((s) => s.count < 2).map((s) => s.host);
    const locale = [...new Set(seen.numberFields)].sort();

    note('empty states not yet converted: ' + (mute.join(' | ') || 'none'));
    note('buttons off the charter: ' + (badButtons.join(' | ') || 'none'));
    note('number fields still in the browser locale: ' + (locale.join(' | ') || 'none'));
    note('notes: ' + (seen.notes.map((n) => n.host + ' ' + (n.severity || '(no severity)'))
      .join(' | ') || 'none'));
    note('right groups: ' + (seen.rights.map((r) => r.host + ' [' + r.first + ' … '
      + r.last + ']').join(' | ') || 'none'));

    // 1 - every component the page uses is registered where it is used
    expect(seen.tags, 'tags Vue left unresolved').toEqual([]);

    // a component rendered with a required prop missing says so in the DOM,
    // and nothing of the kind may reach a reader
    expect(seen.incomplete, 'components rendered with a required prop missing')
      .toEqual([]);

    // 2 - an empty state says what it would show and how to fill it
    const newempties = mute.filter((x) => !LEDGER.empties.includes(x));
    const goneempties = LEDGER.empties.filter((x) => !mute.includes(x));
    note('ledger of mute empty states — not met in this pass: '
      + (goneempties.join(' | ') || 'none'));
    expect(newempties, 'empty states with no shows/gesture, off the ledger')
      .toEqual([]);

    // 3 - a control named in an empty state is on screen where it is named
    expect(missing, 'empty states naming a control that is not on screen')
      .toEqual([]);

    // 4 - a note carries its severity and its ×, an error its next step
    const newnotes = noteFaults.filter((x) => !LEDGER.notes.includes(x));
    const gonenotes = LEDGER.notes.filter((x) => !noteFaults.includes(x));
    note('ledger of bands that do not say what they are — not met in this pass: '
      + (gonenotes.join(' | ') || 'none'));
    expect(newnotes, 'notes that do not say what they are, off the ledger')
      .toEqual([]);

    // 5 - a button says what it does, and its label is in Title case
    const newbuttons = badButtons.filter((x) => !LEDGER.buttons.includes(x));
    const gonebuttons = LEDGER.buttons.filter((x) => !badButtons.includes(x));
    note('ledger of buttons off the charter — not met in this pass: '
      + (gonebuttons.join(' | ') || 'none'));
    expect(newbuttons, 'buttons off the charter and off the ledger').toEqual([]);

    // 6 - the summary opens the right group, the tree button closes it
    expect(rightFaults, 'right groups out of order').toEqual([]);

    // 7 - a strip of one promises a choice it has not got
    expect(thin, 'segmented controls with fewer than two readings').toEqual([]);

    // 8 - no input[type=number]: it parses in the browser's locale, not by
    // the application's decimal rule (see FpNum)
    const newnumberFields = locale.filter((x) => !LEDGER.numberFields.includes(x));
    const gonenumberFields = LEDGER.numberFields.filter((x) => !locale.includes(x));
    note('ledger of fields in the browser locale — not met in this pass: '
      + (gonenumberFields.join(' | ') || 'none'));
    expect(newnumberFields, 'input[type=number] off the ledger').toEqual([]);

    // 9 - one confirmation box for the whole application, and it is the
    // layout's. The box itself is v-if'd away while nothing is being
    // confirmed, so what is held here is the fact that is true AT REST:
    // never a second scrim, and never a dialog owned by a panel or a card
    // (a widget that re-created one behind its own v-if would be caught
    // here even while it is closed). What happens when the box is OPEN (the
    // count, the wording, cancel putting the ticks back) is checked by
    // 04b-charter and by 06-compare, whose folder tick crosses
    // engine/tick_confirm.MAX_TICK_LOAD on purpose.
    expect(seen.scrims, 'confirmation scrims in the page').toBeLessThanOrEqual(1);
    expect(seen.dialogsOwnedByAWidget,
      'confirmation dialogs owned by a panel or a card instead of the layout')
      .toEqual([]);

    // 10 - a note is a band under the bar. In the row of controls a band
    // that grows pushes the buttons about, and a frame cannot refuse what
    // a host hands to its `controls` slot; this reaches the panels written
    // in Python too, which no eslint rule can.
    expect(seen.notesInBar, 'notes written into a row of controls').toEqual([]);

    // 11 - the busy marker, read: a control still marked busy once the
    // sweep has settled is an action that never came back
    expect(seen.busy, 'controls left marked busy after the sweep settled')
      .toEqual([]);

    // 12 - one form for a histogram's options: a host may add to it (the
    // Distribution panel's Stats), never reword it
    const histFaults = seen.histOptions
      .filter((h) => !['Bins', 'Log Y', 'Cumulative'].every((w) => h.words.includes(w)))
      .map((h) => h.host + ' · ' + h.words.join(', '));
    note('histogram options: ' + (seen.histOptions.map((h) => h.host).join(' | ') || 'none in this pass'));
    expect(histFaults, 'histogram options that do not read as the one form').toEqual([]);
  });
