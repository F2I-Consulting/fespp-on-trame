"""The facts of the loaded data that gate the top bar's panels
(engine/data_facts), published as ``ui_data_facts`` at every load.

The tree gives the properties, the wellbores, the logs and the grid
properties; the reader's query channel the stratigraphic column ranks (the
Stratigraphy panel's own source, engine/repo_query). A fact the app could
not learn is left out: no button is greyed on a fact it does not have.
"""
from fespp_on_trame.engine import data_facts, repo_query


def register(core):
    """Wire the watcher that publishes ``ui_data_facts``."""
    state = core.state
    tree = core.tree
    active_data_source = core.active_data_source

    @state.change("assembly_xml")
    def _publish_data_facts(**_):
        out = data_facts.facts(tree)
        try:
            src = active_data_source.get_source()
            out["strati"] = len(repo_query.object_uuids(
                src, repo_query.TYPE_STRATI_RANK, cache_tag=repo_query.tag(src)))
        except repo_query.ChannelMissing:
            # an older plugin: the fact is left out, the button not greyed
            print("[fespp] data facts: no query channel, stratigraphy unknown", flush=True)
        except Exception as exc:
            print("[fespp] data facts: stratigraphic ranks unread:", exc, flush=True)
        state.ui_data_facts = out
