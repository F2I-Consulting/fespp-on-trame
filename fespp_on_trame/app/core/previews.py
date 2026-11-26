"""The features not offered yet (the PO, 18/10: "c'est un peu trop tôt pour
les ajouter — nos connaissances ne sont pas assez poussées sur ces éléments").

Their code stays and is tested: a server shows one only when it is started
with its switch set to "1" (``docker run -e FESPP_VOLUMETRICS=1 ...``; the
wslink launcher hands the container's environment down to every session).
The visual and browser benches set every switch, so the features keep their
coverage while the public server does not show them.
"""
import os

# the feature's key (its tool card, its view kind, "assistant" for the panel,
# "log_sample" for the log view's "From grid" sampling) -> its switch. Log <->
# Grid and Stratigraphy wait for the PO and his manager to settle them.
SWITCHES = {
    "assistant": "FESPP_ASSISTANT",
    "volumetrics": "FESPP_VOLUMETRICS",
    "reconcile": "FESPP_RECONCILE",
    "stratigraphy": "FESPP_STRATIGRAPHY",
    "log_sample": "FESPP_LOG_SAMPLE",
}


def offered(key):
    """Whether the feature `key` is shown: always, unless it is a preview
    whose switch is not "1"."""
    env = SWITCHES.get(key)
    return env is None or (os.environ.get(env) or "").strip() == "1"
