<template>
  <Teleport to="body">
    <div v-if="asking" class="fp-scrim" data-fp-leave-guard @click.self="stay()">
      <div ref="dialog" class="fp-dialog" role="dialog" aria-modal="true" tabindex="-1"
           @keydown.esc="stay()">
        <div class="fp-dialog-head">
          <span class="fp-title">Warning</span>
          <fp-btn variant="bare" label="×" title="Stay on this page" @click="stay()" />
        </div>
        <div class="fp-dialog-body">
          Leaving this page ends the session: the loaded files and every view are lost.
          To come back to them later, save the session first (Session, in the top bar).
        </div>
        <div class="fp-dialog-foot">
          <fp-btn label="Stay" title="Stay on this page" @click="stay()" />
          <fp-btn variant="primary" label="Leave" title="Go back to the previous page: the session ends"
                  @click="leave()" />
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script>
/*
 * The browser's Back, caught while something is loaded (`armed`): the page
 * puts one entry of its own on the history, the same address, so Back lands
 * on the page itself instead of leaving it, and asks. Stay puts the entry
 * back; Leave goes back for real. Nothing is sent to the server: the question
 * is answered even while it is busy.
 *
 *   props in — armed (something is loaded: there is a session to lose)
 */
import FpBtn from "../../../_shared/components/FpBtn.vue";

// the mark of the page's own history entry
const MARK = "fespp-leave-guard";
// time left to the browser to leave the page after Leave; still here, there
// was no page to go back to, and the guard is set again
const NO_PAGE_BEHIND = 800;

export default {
  name: "LeaveGuard",
  components: { FpBtn },
  props: {
    armed: { type: Boolean, default: false },
  },
  data() {
    return { asking: false, guarded: false, leaving: false };
  },
  watch: {
    armed: {
      immediate: true,
      handler(on) { if (on) this.guard(); },
    },
  },
  mounted() { window.addEventListener("popstate", this.onBack); },
  beforeUnmount() { window.removeEventListener("popstate", this.onBack); },
  methods: {
    marked(state) { return !!(state && state[MARK]); },
    guard() {
      if (this.guarded || this.leaving) return;
      // a reload keeps the entry the page was on: already the page's own
      if (!this.marked(window.history.state)) {
        window.history.pushState({ ...(window.history.state || {}), [MARK]: true }, "");
      }
      this.guarded = true;
    },
    onBack(ev) {
      if (!this.guarded || this.leaving || this.marked(ev.state)) return;
      this.guarded = false;
      this.asking = true;
      this.$nextTick(() => {
        const box = this.$refs.dialog;
        const first = box && box.querySelector(".fp-dialog-foot button");
        (first || box)?.focus();
      });
    },
    stay() {
      this.asking = false;
      this.guard();
    },
    leave() {
      this.asking = false;
      this.leaving = true;
      window.history.back();
      setTimeout(() => {
        this.leaving = false;
        if (this.armed) this.guard();
      }, NO_PAGE_BEHIND);
    },
  },
};
</script>

<style>
@import "../../../_shared/panel.css";
</style>
