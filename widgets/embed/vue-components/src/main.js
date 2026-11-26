/*
 * trame_fespp_embed — the page that embeds FesTrame in an iframe talks to it
 * by postMessage, with the session documents of the API (S4, 21/10).
 *
 * Heard (window.message, from an origin the options allow):
 *   { festrame: "apply", document: {...} }   -> the server's session_apply_doc
 *   { festrame: "state" }                    -> the server's session_state
 * Said, to the parent, to the origin that spoke (or any when every origin
 * is allowed):
 *   { festrame: "ready" }                    once the trame client is up
 *   { festrame: "status", status }           the Session door's status, on change
 *   { festrame: "state", state }             the session as one document, on change
 *
 * `window.trame` is trame-client's handle on the page: trigger() reaches a
 * controller, state.watch() follows a state variable.
 */
export function install(app, options = {}) {
  const origins = Array.isArray(options.origins) && options.origins.length ? options.origins : ["*"];
  const any = origins.includes("*");
  let speaker = any ? "*" : "";

  function allowed(origin) {
    return any || origins.includes(origin);
  }

  function post(message) {
    if (window.parent === window || !speaker) return;
    window.parent.postMessage(message, speaker);
  }

  window.addEventListener("message", (event) => {
    const m = event.data;
    if (!m || typeof m !== "object" || m.festrame === undefined) return;
    if (!allowed(event.origin)) return;
    if (!any) speaker = event.origin;
    const trame = window.trame;
    if (!trame) return;
    if (m.festrame === "apply") trame.trigger("session_apply_doc", [m.document || {}]);
    else if (m.festrame === "state") trame.trigger("session_state", []);
  });

  // the client is up a little after the plugin installs: wait for it
  const start = () => {
    const trame = window.trame;
    if (!trame || !trame.state || typeof trame.state.watch !== "function") {
      setTimeout(start, 100);
      return;
    }
    trame.state.watch(["ui_session_status"], (status) => { if (status && status.phase) post({ festrame: "status", status }); });
    trame.state.watch(["ui_session_state"], (state) => { if (state && state.schema) post({ festrame: "state", state }); });
    post({ festrame: "ready" });
  };
  start();
}
