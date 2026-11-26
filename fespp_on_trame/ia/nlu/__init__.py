"""The command engine: a sentence, in French or in English, becomes ONE
command of the application's catalogue.

Built in, numpy only, no external service, no language model:

- `catalogue` — the commands the engine can give, and their parameters;
- `lexicon`   — the words of the trade, French and English (property kinds,
  panels, colour tables, bounds, category values);
- `text`      — the normalised text every other module reads;
- `bilingual` — a French word against the English title of an object;
- `generate`  — the training sentences, made from the catalogue;
- `corpus`    — the sentences written by people, next to the generated ones;
- `model`     — the intent classifier (hashed n-grams, softmax regression),
  trained by ``scripts/train_nlu.py`` into ``assets/nlu_intents.npz``;
- `slots`     — the parameters, read from the sentence (numbers, bounds,
  kinds, panels) and matched against the objects of the session;
- `multi`     — several requests in one sentence, cut apart;
- `engine`    — ``parse(text, objects)``: the command, its confidence, what
  is missing;
- `evaluation` — how the engine is measured: the hand-written sets, the
  session objects they are read against, the scores (the command, its
  parameters, the sure readings that are wrong).

The engine never acts: it proposes a command, the application checks it and
carries it out.
"""
