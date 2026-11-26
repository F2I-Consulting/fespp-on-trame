# trame-fespp-embed

The page that embeds FesTrame (an iframe) talks to it by `postMessage`, with
the session documents of the API (`app/features/session_api`):

    { festrame: "apply", document: {...} }   applies the document
    { festrame: "state" }                     asks for the session as one

and hears back, from the iframe to its parent:

    { festrame: "ready" }                     the page is mounted and listens
    { festrame: "status", status: {...} }     the Session door's status, on change
    { festrame: "state", state: {...} }       the document, on change

Only the origins the server lists (`FESPP_EMBED_ORIGINS`, "*" by default)
are heard; the answers go to the origin that spoke. No Python widget class:
the package only carries the bundle and its `module`.
