"""engine.wire — trame-transaction plumbing (doc/dev/TARGET_ARCHITECTURE.md,
Layer S).

RenderScheduler: dirty-view set drained once per handler (one render and one
frame push per dirty view). StateBatcher: debounce for continuous controls,
stamped with the session ``load_generation`` so stale callbacks no-op.
"""
