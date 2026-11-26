"""A slicer card (engine/slicer_card): boxes shown together, each in Range
(ranges joined by ∪ / ∩ inside the box) or Slice (cuts of one value)
mode, compiled into a sum of products — the Geometry and the Property
slicers alike (the PO's manager, 28/10). The players' steps
(engine/value_sweep.window_steps) close the file."""
from fespp_on_trame.engine import slicer_card as sc
from fespp_on_trame.engine import value_sweep as vs

EXT = {"i": [0, 9], "j": [0, 19], "k": [0, 4]}
WHOLE = ("i", "j", "k")


def _card():
    card = sc.empty(WHOLE)
    sc.defaults(card, EXT)
    return card


def test_a_card_starts_with_one_range_box_keeping_everything():
    card = _card()
    assert card["boxes"][0]["mode"] == sc.RANGE and sc.cutting(card)
    assert sc.boxes(card, EXT) == [[[0, 9], [0, 19], [0, 4]]]


def test_union_and_intersection_join_ranges_of_one_subject_inside_one_box():
    card = _card()
    box = card["boxes"][0]
    i = box["ranges"]["i"]
    i[0].update(low=0, high=3)
    i.append(dict(sc.new_range(card, EXT["i"], op=sc.OR), low=6, high=9))
    box["ranges"]["k"][0].update(low=1, high=2)
    # (I 0-3 ∪ I 6-9) ∩ K 1-2: two pieces, the J left whole
    assert sc.boxes(card, EXT) == [[[0, 3], [0, 19], [1, 2]], [[6, 9], [0, 19], [1, 2]]]
    i.append(dict(sc.new_range(card, EXT["i"], op=sc.AND), low=7, high=8))
    # ∩ binds tighter: 0-3 ∪ (6-9 ∩ 7-8)
    assert sc.boxes(card, EXT) == [[[0, 3], [0, 19], [1, 2]], [[7, 8], [0, 19], [1, 2]]]


def _cuts(card, box, subjects=WHOLE):
    """A cut through the middle of each of `subjects`, in `box`."""
    return [sc.new_cut(card, box, s, EXT[s], whole=True) for s in subjects]


def test_range_and_slice_boxes_mix_and_show_together():
    card = _card()
    card["boxes"][0]["ranges"]["i"][0].update(low=0, high=1)
    sliced = sc.new_box(card, EXT, mode=sc.SLICE, whole=WHOLE)
    _cuts(card, sliced)
    assert [c["at"] for s in WHOLE for c in sliced["cuts"][s]] == [4.0, 9.0, 2.0]
    sliced["cuts"]["i"][0]["visible"] = sliced["cuts"]["j"][0]["visible"] = False
    assert sc.boxes(card, EXT) == [[[0, 1], [0, 19], [0, 4]], [[0, 9], [0, 19], [2, 2]]]
    card["boxes"][0]["visible"] = False
    sliced["cuts"]["k"][0]["visible"] = False
    assert not sc.cutting(card)


def test_a_box_switched_to_slice_keeps_everything_until_a_cut_is_added():
    # the manager, 29/10: "by default everything visible"
    card = _card()
    box = card["boxes"][0]
    sc.set_mode(card, box, sc.SLICE, EXT, whole=WHOLE)
    assert box["cuts"] == {"i": [], "j": [], "k": []} and not sc.cutting(card)
    _cuts(card, box)
    assert sc.products(card, EXT) == [{"i": [4.0, 4.0]}, {"j": [9.0, 9.0]}, {"k": [2.0, 2.0]}]
    sc.set_mode(card, box, sc.RANGE, EXT)          # its ranges were kept
    assert sc.boxes(card, EXT) == [[[0, 9], [0, 19], [0, 4]]]


def test_boxes_join_by_union_or_intersection_the_intersection_binding_tighter():
    card = _card()
    card["boxes"][0]["ranges"]["i"][0].update(low=0, high=5)
    second = sc.new_box(card, EXT)
    second["ranges"]["i"][0].update(low=3, high=9)
    second["ranges"]["k"][0].update(low=1, high=2)
    assert sc.boxes(card, EXT) == [[[0, 5], [0, 19], [0, 4]], [[3, 9], [0, 19], [1, 2]]]
    second["op"] = sc.AND
    assert sc.boxes(card, EXT) == [[[3, 5], [0, 19], [1, 2]]]
    # a third box by ∪: (box 1 ∩ box 2) ∪ box 3
    third = sc.new_box(card, EXT, mode=sc.SLICE)
    sc.new_cut(card, third, "j", EXT["j"], whole=True)
    assert sc.boxes(card, EXT) == [[[3, 5], [0, 19], [1, 2]], [[0, 9], [9, 9], [0, 4]]]
    # boxes that share nothing keep nothing
    second["ranges"]["i"][0].update(low=7, high=9)
    third["visible"] = False
    assert sc.products(card, EXT) == []


def test_a_subject_of_one_value_is_never_cut_on():
    # the PO, 29/10: a constant property has its slicer disabled
    ext = {"poro": [0.25, 0.25], "facies": [0, 12]}
    card = sc.empty(())
    for s in ext:
        sc.add_subject(card, s, ext)
    sc.defaults(card, ext)
    card["boxes"][0]["ranges"]["facies"][0].update(low=2, high=4)
    assert sc.products(card, ext) == [{"facies": [2.0, 4.0]}]
    sliced = sc.new_box(card, ext, mode=sc.SLICE)
    sc.new_cut(card, sliced, "poro", ext["poro"])
    assert sc.products(card, ext) == [{"facies": [2.0, 4.0]}]
    assert sc.constant(ext["poro"]) and not sc.constant(ext["facies"])


def test_a_property_card_takes_and_drops_its_subjects():
    ext = {"poro": [0.0, 0.4], "facies": [0, 12]}
    card = sc.empty(())
    sc.add_subject(card, "poro", ext)
    sc.defaults(card, ext)
    sliced = sc.new_box(card, ext, mode=sc.SLICE)
    sc.add_subject(card, "facies", ext, values=[0, 5, 11])
    assert sc.new_cut(card, sliced, "facies", ext["facies"], [0, 5, 11])["at"] == 5.0
    assert set(card["boxes"][0]["ranges"]) == {"poro", "facies"}
    # the × of a property's line: out of THAT box (the manager, 29/10)
    sc.remove_subject(card, "facies", sliced)
    assert not sc.holds(sliced, "facies") and sc.holds(card["boxes"][0], "facies")
    assert sc.missing(card) == ["facies"]
    sc.add_subject(card, "facies", ext)            # "+ Property" gives it back
    assert sc.holds(sliced, "facies") and sc.missing(card) == []
    for box in list(card["boxes"]):
        sc.remove_subject(card, "facies", box)
    assert card["subjects"] == ["poro"]            # held by no box: forgotten
    sc.remove_subject(card, "poro")
    assert card["subjects"] == [] and "poro" not in card["boxes"][0]["ranges"]


def test_a_chain_or_crops_made_elsewhere_read_back_as_boxes():
    card = sc.from_boxes([[[2, 5], [0, 19], [0, 4]], [[0, 9], [3, 3], [0, 4]]], [True, False], EXT)
    assert sc.boxes(card, EXT) == [[[2, 5], [0, 19], [0, 4]]]
    card = sc.from_cuts({"i": [3], "k": [1, 2]}, {"k": [True, False]}, EXT)
    assert sc.boxes(card, EXT) == [[[3, 3], [0, 19], [0, 4]], [[0, 9], [0, 19], [1, 1]]]
    card = sc.from_paths([[("poro", 0.1, 0.2), ("facies", 5, 5)]], ["poro"])
    assert card["subjects"] == ["poro", "facies"]
    assert sc.products(card, {"poro": [0.0, 0.4], "facies": [0, 12]}) == [
        {"poro": [0.1, 0.2], "facies": [5.0, 5.0]}]


def test_the_range_player_slides_the_whole_window():
    s = vs.window_steps("Index", extent=[0, 5], low=1, high=3, mode="range")
    assert [(a, b) for a, b, _ in s] == [(0, 2), (1, 3), (2, 4), (3, 5)]
    assert vs.nearest_index(s, 2) == 2
    c = vs.window_steps("Continuous", extent=[0.0, 10.0], low=2.0, high=4.0, mode="range", positions=5)
    assert [round(b - a, 9) for a, b, _ in c] == [2.0] * 5
    assert [a for a, _b, _ in vs.window_steps("Index", extent=[3, 6])] == [3, 4, 5, 6]


def test_a_cut_keeps_its_value_only_or_everything_below_or_above_it():
    card = sc.empty(WHOLE)
    box = sc.new_box(card, EXT, mode=sc.SLICE, whole=WHOLE)
    cut = _cuts(card, box, ("i",))[0]              # at 4
    assert cut["cmp"] == sc.ONLY
    assert sc.boxes(card, EXT) == [[[4, 4], [0, 19], [0, 4]]]
    cut["cmp"] = sc.BELOW
    assert sc.boxes(card, EXT) == [[[0, 4], [0, 19], [0, 4]]]
    cut["cmp"] = sc.ABOVE
    assert sc.boxes(card, EXT) == [[[4, 9], [0, 19], [0, 4]]]


def test_each_box_of_a_property_card_holds_its_own_properties():
    # the PO, 30/10: a new box held every property of the card, one he had
    # never put there; a property left in no box stayed a hidden subject
    ext = {"soil": [0.07, 0.65], "k": [1, 14]}
    card = sc.empty(())
    first = sc.new_box(card, ext, subjects=())
    sc.add_subject(card, "k", ext, box=first)
    second = sc.new_box(card, ext, subjects=())
    assert sc.holds(first, "k") and not sc.holds(second, "k")
    # an empty box is as if it were not there: the first box still cuts
    first["ranges"]["k"][0].update(low=13, high=14)
    assert sc.products(card, ext) == [{"k": [13.0, 14.0]}]
    sc.add_subject(card, "soil", ext, box=second)
    assert sc.holds(second, "soil") and not sc.holds(first, "soil")
    assert len(sc.products(card, ext)) == 2
    # the box of soil removed: the card forgets soil
    card["boxes"].remove(second)
    sc.prune(card)
    assert card["subjects"] == ["k"]
