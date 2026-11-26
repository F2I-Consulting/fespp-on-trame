"""The fespp_ia gateway's /v1 contract, against a fake llama-server.

Covers health, a plain reply, a reply constrained to a JSON schema, the
queue that answers busy, the choice of the model file, the RAG endpoints
(/v1/ask and /v1/command), the keywords of the hybrid search, the Markdown
sections, and the command schema and prompt the model reads."""
import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from fespp_ia.llama import command, find_model
from fespp_ia.server import create_app


def fake_llama(seen, delay=0.0, health=200):
    async def handler(request):
        if request.url.path == "/health":
            return httpx.Response(health, json={"status": "ok"})
        body = json.loads(request.content)
        seen.append(body)
        if delay:
            await asyncio.sleep(delay)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"action": "show"}'}}],
            "usage": {"completion_tokens": 7}})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://llama")


class FakeProcess:
    def __init__(self, model="ministral.gguf", alive=True):
        from pathlib import Path
        self.model = Path(model) if model else None
        self._alive = alive
        self.error = "no model: ..." if not model else ""

    def start(self):
        pass

    def stop(self):
        pass

    def alive(self):
        return self._alive


def test_health_says_the_model_is_ready():
    app = create_app(client=fake_llama([]), llama=FakeProcess())
    with TestClient(app) as c:
        h = c.get("/v1/health").json()
    assert h["status"] == "ok" and h["model"] == "ministral" and h["api"] == "1"


def test_health_says_loading_then_no_model_then_stopped():
    with TestClient(create_app(client=fake_llama([], health=503), llama=FakeProcess())) as c:
        assert c.get("/v1/health").json()["status"] == "loading"
    with TestClient(create_app(client=fake_llama([]), llama=FakeProcess(model=None))) as c:
        assert c.get("/v1/health").json()["status"] == "no_model"
    with TestClient(create_app(client=fake_llama([]), llama=FakeProcess(alive=False))) as c:
        assert c.get("/v1/health").json()["status"] == "error"


def test_a_reply_says_what_it_cost():
    seen = []
    with TestClient(create_app(client=fake_llama(seen), llama=FakeProcess())) as c:
        r = c.post("/v1/chat", json={"messages": [{"role": "user", "content": "bonjour"}]}).json()
    assert r["text"] == '{"action": "show"}' and r["tokens"] == 7
    assert "response_format" not in seen[0]


def test_a_schema_constrains_the_reply():
    seen = []
    schema = {"type": "object", "properties": {"action": {"enum": ["show"]}}}
    with TestClient(create_app(client=fake_llama(seen), llama=FakeProcess())) as c:
        c.post("/v1/chat", json={"messages": [{"role": "user", "content": "x"}], "schema": schema})
    assert seen[0]["response_format"]["json_schema"]["schema"] == schema


def test_a_bad_role_is_refused():
    with TestClient(create_app(client=fake_llama([]), llama=FakeProcess())) as c:
        r = c.post("/v1/chat", json={"messages": [{"role": "tool", "content": "x"}]})
    assert r.status_code == 422


@pytest.mark.anyio
async def test_the_queue_says_busy_instead_of_waiting_forever():
    """With every slot taken, a request waits at most `queue_timeout` and then
    gets 503, so a client never hangs behind a long generation."""
    app = create_app(client=fake_llama([], delay=0.5), llama=FakeProcess(),
                     parallel=1, queue_timeout=0.1)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gw") as c:
        body = {"messages": [{"role": "user", "content": "x"}]}
        first, second = await asyncio.gather(c.post("/v1/chat", json=body),
                                             c.post("/v1/chat", json=body))
    assert sorted([first.status_code, second.status_code]) == [200, 503]


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_the_model_is_the_only_gguf_or_the_one_named(tmp_path):
    assert find_model(tmp_path, "") is None
    (tmp_path / "a.gguf").write_bytes(b"")
    assert find_model(tmp_path, "").name == "a.gguf"
    (tmp_path / "b.gguf").write_bytes(b"")
    assert find_model(tmp_path, "") is None             # two files, none named: no guess
    assert find_model(tmp_path, "b.gguf").name == "b.gguf"
    assert find_model(tmp_path, "c.gguf") is None


def test_llama_server_listens_on_localhost_only():
    """llama-server binds 127.0.0.1 inside the container: the gateway is the
    only way in."""
    cmd = command("/models/a.gguf", port=8081)
    assert cmd[cmd.index("--host") + 1] == "127.0.0.1"


# ------------------------------------------------------------------ the RAG: /v1/ask and /v1/command
class FakeIndex:
    """An index of two chunks, the first about pillars: `search` records each
    query and returns the chunks scored."""
    meta = {"model": "fake", "count": 2}

    def __init__(self):
        self.queries = []
        self.chunks = [{"title": "AbstractIjkGridRepresentation: pillars", "source": "fesapi", "path": "a.h",
                        "text": "A pillar is a line of the grid along K joining the corner points of a column."},
                       {"title": "Glossary", "source": "fespp_on_trame", "path": "doc/wiki/Glossary.md",
                        "text": "A channel is a sinuous sand body."}]

    def search(self, query, k=6, sources=None, min_score=0.0):
        self.queries.append((query, k, sources))
        return [(0.8, self.chunks[0]), (0.5, self.chunks[1])][:k]


def fake_llama_saying(seen, content):
    async def handler(request):
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}],
                                         "usage": {"completion_tokens": 5}})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://llama")


def test_a_question_is_answered_from_the_extracts_and_says_its_sources():
    seen, idx = [], FakeIndex()
    with TestClient(create_app(client=fake_llama_saying(seen, "Un pilier est une ligne selon K [pillars]."),
                               llama=FakeProcess(), index=idx)) as c:
        h = c.get("/v1/health").json()
        r = c.post("/v1/ask", json={"question": "c'est quoi un pilier ?", "k": 2}).json()
    assert h["rag"] == {"model": "fake", "count": 2}
    assert idx.queries == [("c'est quoi un pilier ?", 2, None)]
    assert r["text"].startswith("Un pilier") and [s["title"] for s in r["sources"]][0].endswith("pillars")
    user = seen[0]["messages"][1]["content"]
    assert "Extraits" in user and "line of the grid along K" in user
    assert "UNIQUEMENT" in seen[0]["messages"][0]["content"]


def test_without_an_index_a_question_is_refused_not_invented():
    """Without an index, /v1/ask answers 503 rather than letting the model
    answer from its own memory."""
    with TestClient(create_app(client=fake_llama_saying([], "x"), llama=FakeProcess(), load_rag=False)) as c:
        r = c.post("/v1/ask", json={"question": "c'est quoi un pilier ?"})
    assert r.status_code == 503


def test_a_sentence_becomes_a_command_of_the_catalogue_with_the_glossary_read():
    seen, idx = [], FakeIndex()
    reply = json.dumps({"intent": "well_cells", "category": "gas", "kind": None, "min": None, "max": None,
                        "objects": [], "well_filter": "keep_crossing", "question": None})
    catalogue = [{"name": "show", "fr": "afficher"}, {"name": "well_cells", "fr": "les mailles traversées par les puits"}]
    text = "enlève les puits qui ne passent pas par le gaz autour du pilier"
    with TestClient(create_app(client=fake_llama_saying(seen, reply), llama=FakeProcess(), index=idx)) as c:
        r = c.post("/v1/command", json={"text": text, "catalogue": catalogue,
                                        "objects": [{"title": "Fluids", "type": "CategoricalProperty",
                                                     "categories": ["water", "oil", "gas"]}]}).json()
    assert r["command"]["intent"] == "well_cells" and r["command"]["well_filter"] == "keep_crossing"
    assert r["glossary"] == ["AbstractIjkGridRepresentation: pillars", "Glossary"]
    assert idx.queries == [(text, 2, ["docs", "pwls"])]        # two extracts, project documents and PWLS only
    schema = seen[0]["response_format"]["json_schema"]["schema"]
    assert schema["properties"]["intent"]["enum"] == ["ask", "show", "unknown", "well_cells"]
    system = seen[0]["messages"][0]["content"]
    assert "Fluids" in system and "keep_crossing" in system and "Glossaire" in system and "pillars" in system
    assert seen[0]["temperature"] == 0.0 and seen[0]["cache_prompt"] is True


def test_a_caller_without_vocab_gets_every_key_and_the_settled_command():
    """A caller that sends no vocab (the contract before it) is served as
    before: the kind is free text, the response holds every key -- null
    when the model left it out -- and the sentence settles the command: a
    zone hidden becomes a threshold that excludes it."""
    seen = []
    reply = json.dumps({"intent": "hide", "category": "oil"})          # the model wrote two keys only
    catalogue = [{"name": "hide", "fr": "masquer"}, {"name": "threshold", "fr": "filtrer"}]
    objects = [{"title": "Fluids", "type": "CategoricalProperty", "categories": ["Water", "Oil", "Gas"]}]
    with TestClient(create_app(client=fake_llama_saying(seen, reply), llama=FakeProcess(), load_rag=False)) as c:
        r = c.post("/v1/command", json={"text": "cache l'huile", "catalogue": catalogue, "objects": objects}).json()
    command = r["command"]
    assert (command["intent"], command["category"], command["exclude"]) == ("threshold", "oil", True)
    assert set(command) == {"intent", "kind", "category", "exclude", "min", "max", "objects", "well_filter", "panel",
                            "preset", "axis", "factor", "on", "question"}
    assert command["objects"] == [] and command["kind"] is None
    schema = seen[0]["response_format"]["json_schema"]["schema"]
    assert schema["properties"]["kind"] == {"type": ["string", "null"]}
    assert schema["properties"]["category"]["enum"] == ["water", "oil", "gas", None]


def test_a_caller_vocab_enumerates_the_names_the_model_may_write():
    """With the caller's vocab the schema enumerates its kinds, panels and
    colour tables, the prompt lists them and the examples spell them as the
    vocab does; a name outside it comes back null."""
    seen = []
    reply = json.dumps({"intent": "open_panel", "kind": "porosity_avg", "panel": "Stats"})
    vocab = {"kinds": ["porosity", "permeability"], "panels": ["stats", "welllog"],
             "presets": ["Inferno (matplotlib)", "Jet"]}
    with TestClient(create_app(client=fake_llama_saying(seen, reply), llama=FakeProcess(), load_rag=False)) as c:
        r = c.post("/v1/command", json={"text": "les stats de la poro", "catalogue": [{"name": "open_panel"}],
                                        "vocab": vocab}).json()
    assert (r["command"]["intent"], r["command"]["kind"], r["command"]["panel"]) == ("open_panel", None, "stats")
    props = seen[0]["response_format"]["json_schema"]["schema"]["properties"]
    assert props["kind"]["enum"] == ["porosity", "permeability", None]
    assert props["panel"]["enum"] == ["stats", "welllog", None]
    assert props["preset"]["enum"] == ["Inferno (matplotlib)", "Jet", None]
    system = seen[0]["messages"][0]["content"]
    assert "kind : le type de propriété nommé, parmi porosity, permeability ;" in system
    assert "parmi stats, welllog (les logs d'un puits)" in system
    assert '→ {"intent": "colormap", "preset": "Inferno (matplotlib)"}' in system
    assert '"panel": "stats"}' in system


def test_a_vocab_is_cleaned_rather_than_refused():
    """An empty, overlong or repeated name, or a list that is not one, is
    dropped from the vocab: refusing the request would cost the caller its
    whole command."""
    from fespp_ia.server import VOCAB_MAX, Vocab
    v = Vocab(kinds=["porosity", "", "  porosity ", "x" * 81, 7, "net  to gross"], panels="stats",
              presets=[f"p{i}" for i in range(VOCAB_MAX + 5)], categories=["ignored"])
    assert v.kinds == ["porosity", "net to gross"] and v.panels == [] and len(v.presets) == VOCAB_MAX
    seen = []
    with TestClient(create_app(client=fake_llama_saying(seen, '{"intent": "show"}'), llama=FakeProcess(),
                               load_rag=False)) as c:
        r = c.post("/v1/command", json={"text": "montre la poro", "catalogue": [{"name": "show"}],
                                        "vocab": {"kinds": ["porosity", ""], "panels": None}})
    assert r.status_code == 200 and r.json()["command"]["intent"] == "show"


def test_the_command_schema_requires_the_intent_only_and_keeps_its_order():
    """Only the intent is required: the model writes the keys the sentence
    fills and stops, and on a CPU every character of output costs. The
    keys keep one order (llama.cpp's grammar keeps the schema's), the one
    the examples are written in; nothing else may be written."""
    from fespp_ia.server import COMMAND_KEYS, command_schema
    schema = command_schema(["show"])
    assert schema["required"] == ["intent"] and schema["additionalProperties"] is False
    assert list(schema["properties"]) == ["intent", *COMMAND_KEYS]
    props = schema["properties"]
    assert props["exclude"] == {"type": ["boolean", "null"]} and props["on"] == {"type": ["boolean", "null"]}
    assert props["axis"]["enum"] == ["i", "j", "k", None] and props["factor"] == {"type": ["number", "null"]}
    assert props["category"] == {"type": ["string", "null"]}                       # a session without categories
    schema = command_schema(["show"], {"kinds": ["porosity"]}, ["Shale", "shale", "Grès"])
    assert schema["properties"]["kind"]["enum"] == ["porosity", None]
    assert schema["properties"]["category"]["enum"] == ["shale", "gres", None]
    assert schema["properties"]["panel"] == {"type": ["string", "null"]}            # no panels in the vocab


def test_an_example_s_keys_follow_the_schema_order():
    from fespp_ia.server import COMMAND_KEYS, _COMMAND_EXAMPLES
    for text, out in _COMMAND_EXAMPLES:
        keys = list(out)
        assert keys[0] == "intent" and keys[1:] == [k for k in COMMAND_KEYS if k in out], text


def test_the_glossary_is_skipped_when_the_prompt_already_names_every_notion():
    """No glossary lookup when the prompt already names every notion of the
    sentence: the rules name the property kind and the catalogue names the
    verb. A lookup would only lengthen the prompt, and the prompt's length
    is what a call costs."""
    from fespp_ia.server import new_words
    seen, idx = [], FakeIndex()
    reply = json.dumps({"intent": "show", "category": None, "kind": "permeability", "min": None, "max": None,
                        "objects": [], "well_filter": None, "question": None})
    catalogue = [{"name": "show", "fr": "afficher"}, {"name": "hide", "fr": "cacher un objet"}]
    with TestClient(create_app(client=fake_llama_saying(seen, reply), llama=FakeProcess(), index=idx)) as c:
        r = c.post("/v1/command", json={"text": "cache moi la perm", "catalogue": catalogue}).json()
    assert r["glossary"] == [] and idx.queries == []
    assert "Glossaire" not in seen[0]["messages"][0]["content"]
    prompt = "Commandes : cacher un objet ; kind parmi porosity, permeability"
    assert new_words("cache moi la perm, tu peux ?", prompt) == []          # a known stem and a command verb
    assert new_words("montre les trajectoires", prompt) == ["trajectoire"]  # a notion the prompt lacks


def test_an_intent_outside_the_catalogue_is_unknown():
    """An intent the client did not offer becomes "unknown": the client never
    receives a command it cannot run."""
    seen = []
    reply = json.dumps({"intent": "dance", "category": None, "kind": None, "min": None, "max": None,
                        "objects": [], "well_filter": None, "question": None})
    with TestClient(create_app(client=fake_llama_saying(seen, reply), llama=FakeProcess(), load_rag=False)) as c:
        r = c.post("/v1/command", json={"text": "danse", "catalogue": [{"name": "show", "fr": "afficher"}]}).json()
    assert r["command"]["intent"] == "unknown" and r["glossary"] == []


# ------------------------------------------------------------------ the hybrid search's words, the prompt
def test_the_question_s_notions_bridge_the_two_languages():
    """By vector, a French question is far from the English chunk that
    defines its notion: the keyword side pairs each notion with its wording
    in the other language and ignores the filler words."""
    from fespp_ia.rag import keyword_score, keywords
    terms = keywords("c'est quoi un pilier dans une grille IJK ?")
    assert ("pilier", "pillar") in terms and ("grid", "grille") in terms
    assert not any("quoi" in g or "dans" in g for g in terms)
    doc = {"title": "AbstractIjkGridRepresentation: getPillarKind", "text": "The kind of a pillar of the grid."}
    other = {"title": "Core - Sources", "text": "The ParaView pipeline of a source."}
    assert keyword_score(doc, terms) > keyword_score(other, terms) == 0.0


def test_a_markdown_document_is_cut_on_its_headings():
    from fespp_ia.corpus import markdown_sections
    doc = "# Glossaire\n\nintro\n\n## Grille\n\n### Pilier (pillar)\n\nUne ligne selon K.\n\n### Colonne (column)\n\nUne pile."
    got = markdown_sections(doc, "Glossaire")
    assert [t for t, _ in got] == ["Glossaire", "Glossaire › Pilier (pillar)", "Glossaire › Colonne (column)"]
    assert got[1][1].strip() == "Une ligne selon K."


def test_the_command_prompt_teaches_the_traps_the_bench_found():
    """The command prompt holds an example for each reading the model gets
    wrong without one: a fluid zone kept or hidden is a threshold (hidden:
    exclude), while a number does not make one (a highlight keeps every
    cell); a complaint is its own intent, and so is a short question about
    the last reply; bounding the colours is not choosing a palette; the
    wordings of keep_crossing; and one example for each slot of the other
    gestures. An example that only mirrors the schema is left out, since
    every example lengthens the prompt."""
    from fespp_ia.server import CommandRequest, command_prompt
    req = CommandRequest(text="x", catalogue=[{"name": "threshold", "fr": "filtrer", "en": "filter"}], lang="fr")
    prompt = command_prompt(req, [])
    for line in ('fais apparaître uniquement le siltstone » → {"intent": "threshold", "category": "siltstone"}',
                 'retire la zone à gaz de la vue » → {"intent": "threshold", "category": "gas", "exclude": true}',
                 'excède 150 » → {"intent": "highlight", "kind": "permeability", "min": 150}',
                 'ce n\'est pas ce que j\'attendais » → {"intent": "complain"}',
                 'laquelle ? je ne comprends pas de quoi tu parles » → {"intent": "complain"}',
                 'borne la palette de couleurs entre 5 et 40 » → {"intent": "color_range", "min": 5, "max": 40}',
                 'touchent l\'eau » → {"intent": "well_cells", "category": "water", "well_filter": "keep_crossing"}',
                 'en dehors du calcaire, enlève-les » → {"intent": "well_cells", "category": "limestone", '
                 '"well_filter": "keep_crossing"}',
                 '→ {"intent": "slice", "axis": "j"}', '→ {"intent": "z_scale", "factor": 8}',
                 '→ {"intent": "flat_colors", "on": false}',
                 "« vire tous les autres », « des puits sont encore hors de la zone »",
                 "- objects : seulement les titres que la phrase nomme, sinon [].",
                 "- question : seulement pour ask.",
                 "- ask : une question sur le métier ou l'application, pas sur la réponse précédente"):
        assert line in prompt, line
    assert "montre la porosité de la grille" not in prompt       # schema-shaped: teaches nothing
    # without a vocab: the application's kinds, and no panel or colour table spelt for it
    assert "parmi porosity, permeability, net to gross, water saturation," in prompt
    assert '"intent": "open_panel", "kind": "permeability"}' in prompt and '"preset"' not in prompt


def test_the_session_comes_after_the_rules_and_the_examples_so_the_prefix_cache_holds():
    """What changes from one call to the next comes last: the session's
    objects after the catalogue, the rules and the examples (the same for
    every session), the glossary last of all, at most 250 characters per
    extract. llama-server's prompt cache reuses everything before the first
    line that differs: two sessions share all but their objects."""
    from fespp_ia.server import CommandRequest, command_prompt
    one = CommandRequest(text="x", catalogue=[{"name": "show", "fr": "afficher", "en": "show"}], lang="en",
                         objects=[{"title": "Grid A", "type": "IjkGrid"}])
    two = CommandRequest(text="y", catalogue=[{"name": "show", "fr": "afficher", "en": "show"}], lang="en",
                         objects=[{"title": "Fluids", "type": "CategoricalProperty", "categories": ["oil", "gas"]}])
    glossary = [(0.9, {"title": "Pillar", "text": "p" * 300}), (0.8, {"title": "Column", "text": "c" * 10})]
    prompt = command_prompt(one, glossary)
    assert (prompt.index("Rules:") < prompt.index("Examples:") < prompt.index("Objects of the session:")
            < prompt.index("- Grid A (IjkGrid)") < prompt.index("Glossary")
            < prompt.index("- Pillar : " + "p" * 250 + "\n"))
    assert "p" * 251 not in prompt and prompt.endswith("- Column : " + "c" * 10)
    assert command_prompt(one, []) == prompt[:prompt.index("\nGlossary")]      # the cached prefix, unchanged
    other = command_prompt(two, [])
    # the examples that name a zone come last: said on each session's own
    # values, they and the objects are all that two sessions with other
    # zones do not share
    zone_examples = prompt.index("« surligne les zones d'huile")
    assert other.startswith(prompt[:zone_examples]) and "- Fluids (CategoricalProperty, values: oil, gas)" in other
    three = CommandRequest(text="z", catalogue=[{"name": "show", "fr": "afficher", "en": "show"}], lang="en",
                           objects=[{"title": "Fluids 2", "type": "CategoricalProperty", "categories": ["oil", "gas"]}])
    assert command_prompt(three, []).startswith(other[:other.index("Objects of the session:")])


def test_the_examples_name_only_zones_the_session_has():
    """The schema enumerates the session's category values, so an example
    whose zone the session lacks would show the model a category the
    grammar refuses. It is said with the session's own spelling of the same
    zone, or on another value of the session with the zone's words of the
    sentence replaced: every example and its lesson stay."""
    from fespp_ia.server import _COMMAND_EXAMPLES, CommandRequest, command_prompt, command_schema, session_categories
    catalogue = [{"name": n, "fr": n, "en": n} for n in ("threshold", "highlight", "well_cells")]
    sessions = {
        "fluids": [{"title": "Fluids", "type": "CategoricalProperty", "categories": ["Water", "Oil", "Gas"]}],
        "facies": [{"title": "FACIES", "type": "CategoricalProperty",
                    "categories": {"0": "Floodplain", "1": "Channel", "2": "Crevasse", "3": "Coal"}}],
        "french": [{"title": "Fluides", "type": "CategoricalProperty", "categories": ["Eau", "Huile", "Gaz"]}],
        "none": [{"title": "Grid", "type": "IjkGrid"}],
    }
    prompts = {}
    for name, objects in sessions.items():
        prompts[name] = command_prompt(CommandRequest(text="x", catalogue=catalogue, objects=objects, lang="fr"), [])
        category = command_schema(["threshold"], None, session_categories(objects))["properties"]["category"]
        lines = [line for line in prompts[name].split("\n") if line.startswith("« ")]
        assert len(lines) == len(_COMMAND_EXAMPLES), name
        for line in lines:
            out = json.loads(line.split(" → ", 1)[1])
            assert out.get("category") in category.get("enum", [out.get("category")]), (name, line)
    assert ('« fais apparaître uniquement la zone Channel » → {"intent": "threshold", "category": "channel"}'
            in prompts["facies"])
    assert ('« il y a encore des puits en dehors de la zone Coal, enlève-les » → {"intent": "well_cells", '
            '"category": "coal", "well_filter": "keep_crossing"}' in prompts["facies"])
    assert ('« retire la zone Crevasse de la vue » → {"intent": "threshold", "category": "crevasse", "exclude": true}'
            in prompts["facies"])
    assert ('« surligne les zones d\'huile sans rien cacher » → {"intent": "highlight", "category": "huile"}'
            in prompts["french"])
    assert '« laisse seulement les puits qui touchent l\'eau » →' in prompts["fluids"]
    assert '« fais apparaître uniquement le siltstone » → {"intent": "threshold", "category": "siltstone"}' in \
        prompts["none"]
