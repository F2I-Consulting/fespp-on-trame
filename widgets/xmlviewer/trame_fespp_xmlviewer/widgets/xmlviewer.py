from trame_client.widgets.core import AbstractElement

from trame_fespp_xmlviewer import module


class XmlViewer(AbstractElement):
    """One RESQML object, two ways: a readable tree and the raw text.

    Mounted BOTH in the per-view Attributes card and in the XML explorer
    view — hence a widget of its own rather than a section of either.

    Props::

        xml         : the object's serialized XML ("" = nothing to show)
        trail       : [{uuid, title}] — the references walked to reach it;
                      the last entry is what `xml` holds
        tabs        : [{title}] — explorer only; omit for a single object
        active_tab  : index of the open tab
        note        : why a follow led nowhere (a reference outside the data)
        empty_label : the gesture that fills the empty state (the explorer
                      and the Attributes card are filled differently)
        framed      : True in the explorer view (the panel frame with its
                      title); False inside a card, whose frame is the title
        hits        : {query, hits: [{uuid, title, type, partial}], total,
                      note} — the answer to the last search (explorer only)
        relations   : {uuid: {target, source}} — the Graph reading's
                      relations, as far as the host has fetched them
        relations_supported : False when this plugin build does not answer
                      the relationship query
        raws        : [{uuid, title, type, xml, pinned}] — objects read beside
                      the graph (a box right-clicked), pinned ones kept

    Events::

        follow({uuid, title})   a DataObjectReference was clicked
        back(depth)             a breadcrumb step (depth = entries to keep)
        select_tab(i) / close_tab(i) / new_tab()
        search(text)            the find row changed (explorer only)
        pick({uuid, title})     a found object was chosen
        need_relations(uuid)    the Graph reading needs that object's relations
        raw({uuid, title, type, action})  show an object's XML beside the
                                graph ("show"), pin or release it ("pin"),
                                or close it ("close")

    The host owns every piece of that state; the component fetches nothing.
    """

    def __init__(self, children=None, **kwargs):
        super().__init__("xml-viewer", children, **kwargs)
        self._attr_names += [
            "xml", "trail", "tabs",
            ("active_tab", "activeTab"),
            "note",
            ("empty_label", "emptyLabel"),
            "framed",
            "hits",
            # The Graph reading: the relations fetched so far, and whether
            # this plugin build answers the relationship query at all.
            "relations",
            ("relations_supported", "relationsSupported"),
            # objects read beside the graph, a right-click away
            "raws",
        ]
        self._event_names += [
            "follow", "back",
            ("select_tab", "selectTab"),
            ("close_tab", "closeTab"),
            ("new_tab", "newTab"),
            "search", "pick",
            # The Graph reading asks for what it does not hold yet: the
            # relations of one object, fetched on demand.
            ("need_relations", "needRelations"),
            "raw",
        ]


__all__ = ["XmlViewer"]
