"""The assistant of fespp_on_trame, built in, with no external service.

- `nlu` — the command engine: a sentence, French or English, becomes one
  command of the application's catalogue.
- `llm` — the client of the optional local language-model service.
- `journal` — the dialogue journal the vocabulary is enriched from.

Pure Python + numpy: nothing here imports trame or ParaView. The adapter
that knows the application is app/assistant_host.py.
"""
