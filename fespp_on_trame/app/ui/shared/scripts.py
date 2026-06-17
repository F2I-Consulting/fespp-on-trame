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
