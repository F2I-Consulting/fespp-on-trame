"""Tests for engine/progressive_load: a big read written in growing steps,
stoppable between two of them, superseded by a newer selection, and ending
on the very selection a one-shot read would have loaded.

`run_steps` is driven through callbacks: here a fake clock says how long
each step took, and `apply` records what each step wrote."""
import asyncio

from fespp_on_trame.engine import progressive_load as pl


def _run(leaves, base=(), final=None, durations=None, stop_after=None, supersede_after=None,
         per_object=None, learned=None):
    """Drive run_steps and return (outcome, loaded, the selectors each step
    wrote, the progress reports). `leaves` flat, or lots (lists)."""
    flat = [p for x in leaves for p in (x if isinstance(x, list) else [x])]
    final = list(final if final is not None else list(base) + flat)
    writes, reports = [], []
    durations = list(durations or [])
    clock = {"t": 0.0}

    def apply(selectors):
        writes.append(list(selectors))
        clock["t"] += durations.pop(0) if durations else 0.1

    async def pause(_seconds):
        return None

    outcome, loaded = asyncio.run(pl.run_steps(
        list(base), list(leaves), final, apply,
        lambda done, total: reports.append((done, total)),
        lambda: stop_after is not None and len(writes) >= stop_after,
        lambda: supersede_after is None or len(writes) < supersede_after,
        clock=lambda: clock["t"], pause=pause, per_object=per_object, learned=learned))
    return outcome, loaded, writes, reports


def test_the_leaves_group_in_lots_by_owner_in_order_of_appearance():
    owner = {"/w1/traj": "/w1", "/w1/gr": "/w1", "/s1": "/s1", "/w1/rhob": "/w1", "/g/poro": "/g", "/g/perm": "/g"}
    assert pl.lots(list(owner), owner.get) == [["/w1/traj", "/w1/gr", "/w1/rhob"], ["/s1"], ["/g/poro", "/g/perm"]]
    assert pl.lots([], owner.get) == []


def test_a_lot_arrives_whole_and_the_first_step_is_one_lot():
    """A wellbore's five objects are one step, not 1 + 2 + 2: the first
    step of a lotted read is one whole lot, and the next lots join a step
    while they fit its budget."""
    well = ["/w1/traj", "/w1/mf", "/w1/f", "/w1/gr", "/w1/rhob"]
    # no pace known: the first step is one lot, and the lots that fit its
    # budget (FIRST_MAX objects) join it — here everything, in one step
    outcome, loaded, writes, reports = _run([well, ["/s1"], ["/s2"]], durations=[0.1, 0.1, 0.1])
    assert outcome == "done" and loaded == well + ["/s1", "/s2"]
    assert writes == [well + ["/s1", "/s2"]] and reports == [(0, 7), (7, 7)]
    # a pace of 0.39 s an object budgets five objects: the well, whole,
    # then the two surfaces in the next step
    outcome, loaded, writes, reports = _run([well, ["/s1"], ["/s2"]], per_object=0.39, durations=[0.1, 0.1, 0.1])
    assert outcome == "done" and writes[0] == well
    assert [len(w) for w in writes] == [5, 7] and reports == [(0, 7), (5, 7), (7, 7)]


def test_a_lot_larger_than_the_budget_is_split_and_a_known_pace_sizes_the_first_step():
    """At 1.2 s an object a well of five would take six seconds, past
    ONE_SHOT_SECONDS: the first step reads FIRST_TARGET seconds' worth, one
    object, and the steps grow on a fast read; the pace this read measured
    is told back."""
    well = ["/w1/traj", "/w1/mf", "/w1/f", "/w1/gr", "/w1/rhob"]
    told = []
    outcome, _loaded, writes, _r = _run([well, ["/s1"]], per_object=1.2, learned=told.append,
                                        durations=[0.2, 0.3, 0.1])
    assert outcome == "done"
    # 1 object, then 2, then the 2 left of the well with the surface that
    # fits the grown budget: the one-shot end writes the same set, so no more
    assert writes == [well[:1], well[:3], well + ["/s1"]]
    assert told and abs(told[0] - 0.6 / 6) < 1e-9
    assert pl.first_batch(None) == 1 and pl.first_batch(0.1) == pl.FIRST_MAX and pl.first_batch(0.5) == 4


def test_a_first_lot_short_at_the_known_pace_is_read_in_one_step():
    """13/10, the PO: "récupérer l'ensemble d'un coup, puis un seul rendu".
    At 0.9 s an object a well of five is 4.5 s, within ONE_SHOT_SECONDS:
    the whole lot in one step, one redraw, although FIRST_TARGET alone
    would have asked for two objects."""
    well = ["/w1/traj", "/w1/mf", "/w1/f", "/w1/gr", "/w1/rhob"]
    outcome, _loaded, writes, reports = _run([well, ["/s1"]], per_object=0.9, durations=[0.2, 0.1])
    assert outcome == "done"
    assert writes[0] == well and reports[:2] == [(0, 6), (5, 6)]


def test_the_folders_wait_for_the_last_step():
    folders = {"/data/surfaces", "/data/wells/w1"}
    leaves, held = pl.plan(["/data/surfaces", "/data/surfaces/a", "/data/wells/w1",
                            "/data/wells/w1/traj"], lambda p: p in folders)
    assert leaves == ["/data/surfaces/a", "/data/wells/w1/traj"]
    assert held == ["/data/surfaces", "/data/wells/w1"]


def test_a_server_read_steps_from_two_objects():
    assert pl.worth_stepping(["a", "b"], remote=True)
    assert not pl.worth_stepping(["a"], remote=True)


def test_a_file_reads_in_one_load_unless_the_tests_ask_for_steps():
    # a local file reads fast in one load and steps only multiply the
    # redraws, many times over the one-shot time
    many = [str(i) for i in range(pl.LOCAL_MIN)]
    assert not pl.worth_stepping(many, remote=False, local_steps=False)
    assert pl.worth_stepping(many, remote=False, local_steps=True)
    assert not pl.worth_stepping(many[:-1], remote=False, local_steps=True)


def test_the_steps_grow_on_a_fast_read():
    assert pl.next_batch(1, 0.1) == 2
    assert pl.next_batch(pl.BATCH_MAX, 0.1) == pl.BATCH_MAX


def test_slow_objects_make_small_steps_so_stop_acts_soon():
    # a server taking two seconds an object, nothing to redraw yet: two a
    # step fit in STEP_MAX
    assert pl.next_batch(8, 16.0) == 2
    assert pl.next_batch(1, 3.0) == 1


def test_a_step_slowed_by_its_redraw_still_grows():
    # once the view holds many objects, the redraw sets a step's length:
    # adding one object costs about as much as adding sixteen. Sized on the
    # step's length alone the steps would shrink to two objects and the read
    # crawl; sized on the objects' share of the step, they grow.
    assert pl.next_batch(16, 3.0, redraw=2.8) == 32
    assert pl.next_batch(2, 1.5, redraw=1.4) == 4


def test_the_redraw_never_outweighs_a_fifth_of_the_step():
    # two seconds an object over OSDU, three seconds of redraw once the
    # view is full: one object a step would spend 60 % of the read
    # redrawing; six objects a step keep it to a fifth (13/10: a 44-property
    # grid on ADME spent 45 % of its load redrawing in steps of three or
    # four), at the price of a Stop that waits one step of fifteen seconds.
    assert pl.next_batch(4, 11.0, redraw=3.0) == 6
    # ...but a step never more than doubles
    assert pl.next_batch(1, 5.0, redraw=3.0) == 2


def test_the_last_step_is_judged_on_what_it_read():
    assert pl.next_batch(32, 3.0, size=4, redraw=2.8) == 64


def test_every_object_arrives_and_the_end_is_the_one_shot_selection():
    leaves = [f"/data/s{i}" for i in range(10)]
    final = ["/data"] + leaves              # the folder, held back
    outcome, loaded, writes, reports = _run(leaves, final=final)
    assert outcome == "done"
    assert loaded == final
    # one object first, then twice as many after each fast step: 1, 2, 4, 3
    assert [len(w) for w in writes[:-1]] == [1, 3, 7, 10]
    assert writes[-1] == final
    assert reports[0] == (0, 10) and reports[-1] == (10, 10)


def test_a_slow_server_is_read_one_object_at_a_time():
    leaves = [f"/data/s{i}" for i in range(4)]
    _, _, writes, _ = _run(leaves, durations=[3.0] * 10)
    assert [len(w) for w in writes] == [1, 2, 3, 4]


def test_the_last_step_is_skipped_when_it_would_write_the_same_set():
    leaves = ["/data/a", "/data/b", "/data/c"]
    outcome, _, writes, _ = _run(leaves, final=list(reversed(leaves)))
    assert outcome == "done"
    assert [len(w) for w in writes] == [1, 3]   # no third write of the same three


def test_what_stays_of_the_previous_selection_is_in_every_step():
    outcome, _, writes, _ = _run(["/data/new1", "/data/new2"], base=["/data/kept"])
    assert outcome == "done"
    assert all(w[0] == "/data/kept" for w in writes)


def test_stop_keeps_what_has_arrived_and_reads_nothing_more():
    leaves = [f"/data/s{i}" for i in range(20)]
    outcome, loaded, writes, _ = _run(leaves, base=["/data/kept"], stop_after=2,
                                      durations=[3.0] * 10)
    assert outcome == "stopped"
    assert len(writes) == 2
    assert loaded == ["/data/kept", "/data/s0", "/data/s1"]


def test_a_newer_selection_takes_over_and_nothing_more_is_written():
    leaves = [f"/data/s{i}" for i in range(20)]
    outcome, _, writes, _ = _run(leaves, supersede_after=1, durations=[3.0] * 10)
    assert outcome == "superseded"
    assert len(writes) == 1
