<template>
  <fp-panel class="fas" title="Assistant" :busy="busy" :scroll="false"
            title-tip="A sentence, in French or English, becomes one command of the application — understood here, on the server, never sent elsewhere"
            data-fp-assistant>
    <template #actions>
      <fp-btn label="Clear" data-fp-assistant-clear :disabled="!messages.length || busy"
              :title="clearTitle" @click="$emit('clear')" />
    </template>

    <div ref="list" class="fp-scroll fas-list">
      <template v-if="!messages.length">
        <fp-empty :shows="emptyShows" :gesture="emptyGesture" />
        <div v-if="examples.length" class="fas-examples">
          <fp-btn v-for="(e, i) in examples" :key="i" class="fas-example" tiny
                  :label="capFirst(e)" :title="whileBusy('Send this request: ' + e)" :disabled="held"
                  data-fp-assistant-example @click="send(e, false)" />
        </div>
      </template>

      <div v-for="m in messages" :key="m.id" class="fas-msg"
           :class="m.role === 'user' ? 'fas-user' : 'fas-assistant fas-level-' + levelOf(m)"
           data-fp-assistant-msg :data-role="m.role"
           :data-level="m.role === 'user' ? null : levelOf(m)">
        <div class="fas-text">{{ m.text }}</div>
        <table v-if="m.rows && m.rows.length" class="fp-table fas-rows">
          <tbody>
            <tr v-for="(r, j) in m.rows" :key="j">
              <td class="fas-key">{{ r[0] }}</td>
              <td class="fas-val">{{ cell(r[1]) }}</td>
            </tr>
          </tbody>
        </table>
        <!-- Only the LAST message's buttons are live: an older question was
             answered, or replaced by a new sentence. -->
        <div v-if="m.id === lastId && m.role === 'assistant' && m.choices && m.choices.length"
             class="fas-choices">
          <fp-btn v-for="c in m.choices" :key="c.id" tiny :disabled="held"
                  :label="capFirst(c.label)" :title="whileBusy(choiceTitle(c))"
                  data-fp-assistant-choice :data-choice-id="c.id"
                  @click="pick(c)" />
        </div>
        <!-- The Undo sends the id of ITS reply: the controller undoes only
             while that action is still the last one done. -->
        <div v-if="m.undoable && canUndo" class="fas-choices">
          <fp-btn tiny label="Undo" :busy="busy" :disabled="sent" data-fp-assistant-undo
                  :title="whileBusy('Undo this action: the view goes back to how it was before it')"
                  @click="undoOf(m)" />
        </div>
      </div>
    </div>

    <div class="fas-foot">
      <textarea ref="input" v-model="draft" class="fp-input fas-input" :rows="rows"
                :placeholder="placeholder" :maxlength="maxText" data-fp-assistant-input
                :title="inputTitle" @keydown.enter="onEnter"></textarea>
      <fp-btn variant="primary" label="Send" data-fp-assistant-send :busy="busy"
              :disabled="!draft.trim() || sent" :title="sendTitle" @click="send(draft, true)" />
    </div>
  </fp-panel>
</template>

<script>
/*
 * The Assistant: a conversation in which a sentence, in French or in
 * English, becomes one command of the application.
 *
 * Pure display, like every widget of this repository:
 *   props in   — data {messages: [{id, role, text, level, rows, choices,
 *                undoable}], busy, can_undo, lang, examples}
 *   events out — ask(text), choose(id), undo(id of the reply whose Undo was
 *                clicked), clear()
 * Every decision (what a sentence means, what to ask back, what runs, what
 * can be undone) belongs to the controller
 * (trame_fespp_assistant/controller.py). The panel shows the messages, the
 * buttons of the LAST one, the Undo of the action that can be undone, and
 * the field.
 *
 * Enter sends, Shift+Enter starts a new line; the field empties once its
 * request is sent, and holds MAX_TEXT characters, the controller's own
 * bound. The list follows the newest message. An empty conversation says
 * what the assistant does and offers the host's examples, each one a button
 * that sends it.
 *
 * A gesture sent holds the buttons that send another one (examples,
 * choices, Undo, Send) until the controller's state answers, with its busy
 * bar or its reply, so a double click sends once. The hold lifts by itself
 * after SENT_HOLD_MS when the controller ignored the gesture and sent
 * nothing back.
 *
 * A button label is written in Title case (rule R15, see
 * widgets/_shared/README.md), while an example, a command's name or an
 * object's title may start lower case: its first letter is raised on the
 * button, and the tooltip carries the words as they are.
 */
import FpBtn from "../../../_shared/components/FpBtn.vue";
import FpEmpty from "../../../_shared/components/FpEmpty.vue";
import FpPanel from "../../../_shared/components/FpPanel.vue";
import { fmt } from "../../../_shared/numfmt.js";

const LEVELS = ["info", "ok", "ask", "error"];
const FALLBACK_EXAMPLE = "show the porosity of Geogrid";
// Same bound as controller.MAX_TEXT: a command is one sentence.
const MAX_TEXT = 500;
const SENT_HOLD_MS = 2000;

export default {
  name: "AssistantPanel",
  components: { FpBtn, FpEmpty, FpPanel },
  props: {
    data: { type: Object, default: () => ({}) },
  },
  emits: ["ask", "choose", "undo", "clear"],
  data() {
    // sent: a gesture went out and the controller's state has not answered yet.
    return { draft: "", sent: false, maxText: MAX_TEXT };
  },
  computed: {
    messages() { return (this.data && this.data.messages) || []; },
    examples() { return (this.data && this.data.examples) || []; },
    busy() { return !!(this.data && this.data.busy); },
    held() { return this.busy || this.sent; },
    canUndo() { return !!(this.data && this.data.can_undo); },
    lastId() {
      const m = this.messages;
      return m.length ? m[m.length - 1].id : null;
    },
    rows() {
      const lines = this.draft.split("\n").length;
      return Math.min(3, Math.max(1, lines, Math.ceil(this.draft.length / 70)));
    },
    placeholder() {
      const e = this.examples[0] || FALLBACK_EXAMPLE;
      return "Type a request (English or French) — e.g. “" + e + "”";
    },
    inputTitle() {
      return "Your request, in French or English — Enter sends it, Shift+Enter starts a new line ("
        + MAX_TEXT + " characters at most)";
    },
    sendTitle() {
      if (this.held) return "Wait: the assistant is still working on the last request";
      if (!this.draft.trim()) return "Type a request in the field first";
      return "Send the request (Enter)";
    },
    clearTitle() {
      if (this.busy) return "Wait: the assistant is still working on the last request";
      if (!this.messages.length) return "Nothing to clear: the conversation is empty";
      return "Empty the conversation — what was done in the views stays";
    },
    emptyShows() {
      return "The assistant turns a sentence, in French or English, into a command"
        + " of the application: show, hide or isolate an object, filter or highlight"
        + " cells by value, change the colors, open an analysis panel, describe an"
        + " object or give a statistic — and an action can be undone.";
    },
    emptyGesture() {
      return "Type a request in the field below and press “Send” or Enter"
        + (this.examples.length ? ", or click one of these examples." : ".");
    },
  },
  watch: {
    // Keep the newest message in sight, whoever wrote it.
    lastId() { this.$nextTick(() => this.toBottom()); },
    // The controller answered a gesture, with its busy bar or its reply.
    data() { this.release(); },
  },
  mounted() {
    this.toBottom();
  },
  beforeUnmount() {
    this.release();
  },
  methods: {
    send(text, fromField) {
      const t = String(text || "").trim();
      if (!t || this.held) return;
      this.hold();
      this.$emit("ask", t);
      if (fromField) this.draft = "";
    },
    pick(c) {
      if (this.held) return;
      this.hold();
      this.$emit("choose", c.id);
    },
    undoOf(m) {
      if (this.held) return;
      this.hold();
      this.$emit("undo", m.id);
    },
    hold() {
      this.release();
      this.sent = true;
      this.sentTimer = setTimeout(() => { this.sentTimer = null; this.sent = false; }, SENT_HOLD_MS);
    },
    release() {
      if (this.sentTimer) clearTimeout(this.sentTimer);
      this.sentTimer = null;
      this.sent = false;
    },
    onEnter(e) {
      // Shift+Enter inserts a new line; an Enter while an IME composes belongs to the IME.
      if (e.shiftKey || e.isComposing) return;
      e.preventDefault();
      this.send(this.draft, true);
    },
    toBottom() {
      const el = this.$refs.list;
      if (el) el.scrollTop = el.scrollHeight;
    },
    levelOf(m) {
      return LEVELS.includes(m.level) ? m.level : "info";
    },
    capFirst(s) {
      const t = String(s == null ? "" : s);
      return t.charAt(0).toUpperCase() + t.slice(1);
    },
    cell(v) {
      return typeof v === "number" ? fmt(v) : (v == null ? fmt(null) : String(v));
    },
    // A disabled button says why in its tooltip.
    whileBusy(tip) {
      return this.held ? "Wait: the assistant is still working on the last request — " + tip : tip;
    },
    choiceTitle(c) {
      const id = String(c.id || "");
      if (id === "cancel") return "Do nothing: this request is dropped";
      if (id.startsWith("intent:")) return "Run the request as: " + c.label;
      if (id.startsWith("target:")) return "Use this object: " + c.label + " — " + id.slice(7);
      return c.label;
    },
  },
};
</script>

<style>
@import "../../../_shared/panel.css";
</style>

<style scoped>
.fas-list { display: flex; flex-direction: column; gap: 6px; padding: 8px; }
.fas-examples { display: flex; flex-direction: column; align-items: flex-start; gap: 4px; padding: 0 16px 8px; }
.fas-example { text-align: left; white-space: normal; }
.fas-msg { max-width: 88%; padding: 4px 8px; border-radius: 6px; line-height: 1.4; }
.fas-text { white-space: pre-wrap; overflow-wrap: anywhere; }
.fas-user { align-self: flex-end; background: var(--fp-accent-soft); color: var(--fp-ink); }
.fas-assistant { align-self: flex-start; background: var(--fp-neutral-bg); border-left: 3px solid var(--fp-ink-faint); }
.fas-level-ok { border-left-color: var(--fp-accent); }
.fas-level-ask { border-left-color: var(--fp-warn-ink); }
.fas-level-error { border-left-color: var(--fp-error-ink); background: var(--fp-error-bg); color: var(--fp-error-ink); }
.fas-rows { width: auto; margin-top: 4px; }
.fas-rows td { border-bottom-color: var(--fp-line-soft); }
.fas-key { color: var(--fp-ink-mute); padding-right: 16px; }
.fas-val { text-align: right; font-variant-numeric: tabular-nums; }
.fas-choices { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
.fas-foot { flex: 0 0 auto; display: flex; align-items: flex-end; gap: 6px; padding: 6px 8px; border-top: 1px solid var(--fp-line); background: var(--fp-bg); }
.fas-input { flex: 1 1 auto; resize: none; line-height: 1.35; }
</style>
