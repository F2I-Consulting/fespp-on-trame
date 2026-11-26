/*
 * Escape closes what a widget has open — a popover, a picker, a menu.
 *
 *   mounted()       { this._unEscape = onEscape(() => { this.open = false; }); }
 *   beforeUnmount() { this._unEscape(); }
 *
 * One listener on the window per host, removed with the host. Closing what
 * is already closed is a no-op, so an Escape meant for something else costs
 * nothing. <fp-menu> listens for itself.
 */
export function onEscape(close) {
  const handler = (e) => {
    if (e.key === "Escape") close(e);
  };
  window.addEventListener("keydown", handler);
  return () => window.removeEventListener("keydown", handler);
}
