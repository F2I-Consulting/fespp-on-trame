/*
 * trame_fespp_lazy — the widget bundles the page loads on demand, at the first
 * opening of their view, instead of at the page (S2, 21/10).
 *
 * The server hands this plugin a table, as its options:
 *
 *   { modules: { "<vue_use name>": { scripts: [...], styles: [...],
 *                                    components: ["<tag>", ...] } } }
 *
 * For every tag the plugin registers a Vue ASYNC component. Its loader, run at
 * the tag's first render, injects the module's styles and scripts (in order,
 * relative to the page as trame does), then installs the bundle's plugin on a
 * SHIM that collects the components it registers — never on the real app,
 * whose names stay the async ones. A module is loaded once, whichever of its
 * tags came first; a failure is thrown to Vue, which says which tag and why.
 *
 * Measured before: Plotly alone executed 375 ms of JavaScript before the
 * interface showed, for charts no one had opened.
 */
import { defineAsyncComponent } from "vue";

const loading = new Map(); // vue_use name -> Promise of { tag: component }

function addScript(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = src;
    s.async = false;
    s.onload = resolve;
    s.onerror = () => reject(new Error("could not load " + src));
    document.head.appendChild(s);
  });
}

function addStyle(href) {
  return new Promise((resolve) => {
    const l = document.createElement("link");
    l.rel = "stylesheet";
    l.href = href;
    l.onload = resolve;
    l.onerror = resolve; // a missing sheet is not a reason to keep the panel blank
    document.head.appendChild(l);
  });
}

/* "ComparePanel" -> "compare-panel", "trame-plotly" unchanged */
function kebab(name) {
  return String(name)
    .replace(/([a-z0-9])([A-Z])/g, "$1-$2")
    .replace(/([A-Z])([A-Z][a-z])/g, "$1-$2")
    .toLowerCase();
}

function load(name, spec) {
  if (!loading.has(name)) {
    loading.set(name, (async () => {
      await Promise.all((spec.styles || []).map(addStyle));
      for (const src of spec.scripts || []) await addScript(src);
      const plugin = window[name];
      if (!plugin || typeof plugin.install !== "function") {
        throw new Error(name + " loaded but defines no Vue plugin");
      }
      const got = {};
      const shim = {
        component(n, c) { if (c !== undefined) got[kebab(n)] = c; return shim; },
        use() { return shim; },
        directive() { return shim; },
        mixin() { return shim; },
        provide() { return shim; },
        config: { globalProperties: {}, compilerOptions: {} },
      };
      plugin.install(shim);
      return got;
    })());
  }
  return loading.get(name);
}

export function install(app, options = {}) {
  const modules = (options && options.modules) || {};
  for (const [name, spec] of Object.entries(modules)) {
    for (const tag of spec.components || []) {
      app.component(tag, defineAsyncComponent({
        loader: () => load(name, spec).then((got) => {
          const c = got[tag];
          if (!c) throw new Error(tag + " is not a component of " + name);
          return c;
        }),
        delay: 0,
      }));
    }
  }
  // the page can warm one up (a panel about to open, a probe)
  window.fesppLazy = { modules, load: (name) => load(name, modules[name] || {}) };
}
