"""XmlPanel — the ``xml`` view kind: browse the RESQML objects themselves.

Contract
--------
Input:     ``server`` and ``view_id``.
Behaviour: mounts ``XmlViewer`` (widgets/xmlviewer) on this panel's own tab
           set. A tab is a navigation STACK: following a
           DataObjectReference pushes onto it, the breadcrumb pops back, and
           several tabs keep several places open at once — descending a
           reference chain is one click, coming back is what needs help.
Reads:     ``xml_xml__<vid>``, ``xml_tabs__<vid>``, ``xml_tab__<vid>``,
           ``xml_note__<vid>``, ``xml_hits__<vid>`` (the panel's own find),
           ``xml_relations__<vid>`` (the Graph reading), ``xml_raws__<vid>``
           (the objects read beside the graph).
Writes:    nothing directly — every gesture goes through a controller
           (``xml_search``, ``xml_pick``, ``xml_follow``, ``xml_back``,
           ``xml_select_tab``, ``xml_close_tab``, ``xml_new_tab``), which
           owns the tab state. The view is independent: its find row lists
           the repository's objects, so it opens on any of them without
           another view's help.

The objects it browses need NOT be in the tree: most are not (the whole
stratigraphy chain, property kinds, CRS). They only have to be in the
reader's repository, which the query channel serves the same way over a
local EPC and over ETP.
"""
from trame.widgets import html


class XmlPanel:
    def __init__(self, server, view_id):
        from trame_fespp_xmlviewer.widgets.xmlviewer import XmlViewer

        self.server = server
        self.view_id = vid = str(view_id)
        self.html_view = None  # non-render kind
        ctrl = server.controller
        state = server.state
        for name, default in ((f"xml_tabs__{vid}", []), (f"xml_tab__{vid}", 0),
                              (f"xml_xml__{vid}", ""), (f"xml_note__{vid}", ""),
                              (f"xml_relations__{vid}", {}),
                              (f"xml_hits__{vid}", {}),
                              (f"xml_raws__{vid}", [])):
            if getattr(state, name, None) is None:
                state[name] = default

        with html.Div(style="width:100%; height:100%; background:#fff;"
                            " overflow:hidden;"):
            XmlViewer(
                framed=True,
                xml=(f"xml_xml__{vid}", ""),
                # the active tab's stack drives the breadcrumb
                trail=(f"(xml_tabs__{vid} && xml_tabs__{vid}[xml_tab__{vid}]"
                       f" && xml_tabs__{vid}[xml_tab__{vid}].stack) || []",),
                tabs=(f"xml_tabs__{vid} || []",),
                active_tab=(f"xml_tab__{vid} || 0",),
                note=(f"xml_note__{vid}", ""),
                hits=(f"xml_hits__{vid}", {}),
                empty_label="Add an object above — its title, its type or its"
                            " uuid — or right-click a row of the data tree or an"
                            " object in a 3D view and choose “Info”.",
                search=(ctrl.xml_search, f"[$event, '{vid}']"),
                pick=(ctrl.xml_pick, f"[$event, '{vid}']"),
                follow=(ctrl.xml_follow, f"[$event, '{vid}']"),
                back=(ctrl.xml_back, f"[$event, '{vid}']"),
                select_tab=(ctrl.xml_select_tab, f"[$event, '{vid}']"),
                close_tab=(ctrl.xml_close_tab, f"[$event, '{vid}']"),
                new_tab=(ctrl.xml_new_tab, f"['{vid}']"),
                # the Graph reading: the object's neighbourhood, half of
                # which is in no object's XML — see boot.xml_relations
                relations=(f"xml_relations__{vid} || {{}}",),
                relations_supported=("!!ui_xml_relations_ok",),
                need_relations=(ctrl.xml_relations, f"[$event, '{vid}']"),
                # objects read beside the graph (right-click a box): shown,
                # pinned, closed — see boot.xml_raw
                raws=(f"xml_raws__{vid} || []",),
                raw=(ctrl.xml_raw, f"[$event, '{vid}']"),
            )
