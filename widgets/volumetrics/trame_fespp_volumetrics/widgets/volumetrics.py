from trame_client.widgets.core import AbstractElement

from trame_fespp_volumetrics import module


class HtmlElement(AbstractElement):
    """Base element: attaching it to a server enables the widget's JS module."""

    def __init__(self, _elem_name, children=None, **kwargs):
        super().__init__(_elem_name, children, **kwargs)
        if self.server:
            self.server.enable_module(module)


__all__ = ["VolumetricsPanel"]


class VolumetricsPanel(HtmlElement):
    """Volumetrics with fluid contacts: the host computes, the panel shows.

    Props in are the choices, the current parameters and the table that
    engine/volumetrics_dispatch builds; events out are the user's requests.
    Volumes arrive in cubic metres (standard cubic metres at surface).

    Props::

        data  {grids: [{path, title}], props: [{path, title, kind, unit, type}],
               params: {grid, poro, ntg, sw, region, goc, owc, show_contacts,
                        bo, bg, rf_oil, rf_gas},
               rows, totals: [{region_code, region, fluid, cells, grv, nrv, pv,
                               hcpv, stoiip, rec_oil, giip, rec_gas}],
               cells, active, units, convention, note, grid_title,
               surface: {bo, bg, rf_oil, rf_gas},
               percentile_terms: [{term, text}], csv: {name, header}}

    Events::

        set([key, value])   — one parameter
        compute()
    """

    def __init__(self, **kwargs):
        super().__init__("volumetrics-panel", **kwargs)
        self._attr_names += ["data"]
        self._event_names += ["set", "compute"]
