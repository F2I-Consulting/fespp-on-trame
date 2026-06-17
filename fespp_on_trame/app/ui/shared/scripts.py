"""Client-side JavaScript injected once into the app layout.

Pure-JS to avoid trame/server round-trips per drag step. Handles:
  - footer hiding (catches dynamically-added footer nodes too),
  - VTK log auto-scroll (MutationObserver keeps the scroll at the
    bottom as new lines arrive),
  - drawer resize handle (drag the right edge to resize the drawer,
    width clamped to [200, 900]).

`trame_client.Script` injects a real executable <script> element
(unlike `html.Script`, which is rendered as text)."""
from trame.widgets import client as trame_client


_CLIENT_JS = """
(function () {
    function hideEl(el) {
        if (el && el.nodeType === 1) {
            var tag = el.tagName && el.tagName.toLowerCase();
            var cls = el.classList;
            if (tag === 'footer' || (cls && cls.contains('v-footer'))) {
                el.style.setProperty('display', 'none', 'important');
                el.style.setProperty('height', '0', 'important');
                el.style.setProperty('overflow', 'hidden', 'important');
            }
        }
    }

    function setupLogScroll() {
        var c = document.getElementById('vtk-log-container');
        if (!c) { setTimeout(setupLogScroll, 600); return; }
        new MutationObserver(function () {
            c.scrollTop = c.scrollHeight;
        }).observe(c, { childList: true, subtree: true });
    }

    function init() {
        // Hide any already-present footer elements
        document.querySelectorAll('footer, .v-footer').forEach(hideEl);

        // Watch the whole DOM for dynamically added footer elements
        new MutationObserver(function (mutations) {
            mutations.forEach(function (m) {
                m.addedNodes.forEach(function (node) {
                    hideEl(node);
                    if (node.querySelectorAll) {
                        node.querySelectorAll('footer, .v-footer').forEach(hideEl);
                    }
                });
            });
        }).observe(document.documentElement, { childList: true, subtree: true });

        setupLogScroll();
        setupDrawerResize();
        setupStatsMinimize();
    }

    // ---- Drawer resize handle (pure JS — zero trame/server round-trips) ----
    // Event delegation on document: the handle element can be
    // re-mounted by Vue when surrounding layout changes (toolbar
    // v-if, drawer re-render, …) which would orphan a directly-
    // attached listener. Delegating to document survives that.
    function setupDrawerResize() {
        var dragging = false;

        document.addEventListener('mousedown', function (e) {
            if (!e.target || !e.target.closest) return;
            if (!e.target.closest('.fespp-drawer-resize-handle')) return;
            dragging = true;
            document.body.style.cursor = 'ew-resize';
            document.body.style.userSelect = 'none';
            e.preventDefault();
        });

        document.addEventListener('mousemove', function (e) {
            if (!dragging) return;
            var w = Math.max(200, Math.min(900, e.clientX));
            // Drive Vuetify's layout through the proper channel:
            // push drawer_width via trame's state API. This makes
            // Vuetify recompute its registered layout-item sizes,
            // so VMain follows the drawer's new width without any
            // CSS hack. Falls back to direct DOM mutation if the
            // global trame.state API is somehow unavailable (early
            // bootstrap, version mismatch, …).
            if (
                window.trame
                && window.trame.state
                && typeof window.trame.state.set === 'function'
            ) {
                window.trame.state.set('drawer_width', w);
            } else {
                var drawer = document.querySelector('.v-navigation-drawer');
                if (drawer) {
                    drawer.style.setProperty('width', w + 'px', 'important');
                }
            }
        });

        document.addEventListener('mouseup', function () {
            if (!dragging) return;
            dragging = false;
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
        });
    }

    // ---- Stats panel window-state (minimize / maximize, floating overlay) ----
    // Mirrors two trame state flags to body classes:
    //   ui_stats_panel_minimized → body.fespp-stats-minimized
    //   ui_stats_panel_maximized → body.fespp-stats-maximized
    // CSS in styles.py reads those classes to collapse / expand
    // the floating Stats shell. The two are mutex (the Vue click
    // handlers in multi_view ensure only one is true at a time)
    // but we don't enforce that here — class toggling is a pure
    // state mirror.
    function setupStatsMinimize() {
        var KEYS = [
            ['ui_stats_panel_minimized', 'fespp-stats-minimized'],
            ['ui_stats_panel_maximized', 'fespp-stats-maximized'],
        ];
        function apply() {
            if (!window.trame || !window.trame.state) return;
            for (var i = 0; i < KEYS.length; i++) {
                var v = !!window.trame.state.get(KEYS[i][0]);
                document.body.classList.toggle(KEYS[i][1], v);
            }
        }
        function snapshot() {
            var out = {};
            for (var i = 0; i < KEYS.length; i++) {
                out[KEYS[i][0]] = window.trame.state.get(KEYS[i][0]);
            }
            return out;
        }
        function differs(a, b) {
            for (var i = 0; i < KEYS.length; i++) {
                if (a[KEYS[i][0]] !== b[KEYS[i][0]]) return true;
            }
            return false;
        }
        function watchState() {
            if (!window.trame || !window.trame.state) {
                setTimeout(watchState, 200);
                return;
            }
            apply();
            var last = snapshot();
            setInterval(function () {
                var cur = snapshot();
                if (!differs(last, cur)) return;
                last = cur;
                apply();
            }, 150);
        }
        watchState();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
"""


def inject_client_scripts() -> None:
    """Inject the client-side JS blob into the layout."""
    trame_client.Script(_CLIENT_JS)
