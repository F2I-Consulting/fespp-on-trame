"""Tests for engine/categorical_palette: one colour per code for a discrete
or categorical property.

Covered: the codes found in the data and their names, the indexed LUT
written through the proxy's properties, the reader's colour edits kept
across reconciles, and the reasons a discrete property is still painted
with a ramp. The LUT is a fake proxy; the preset table is patched."""
import pytest

from fespp_on_trame.engine import categorical_palette as cp
from fespp_on_trame.engine.sources import chain_domain
from fespp_on_trame.engine.tree import Tree
from fespp_on_trame.engine.utils import categories as cat
from tests.unit.fake_assembly import FakeDataAssembly


class _Prop:
    def __init__(self):
        self.elems = []

    def SetNumberOfElements(self, n):
        self.elems = (self.elems + [0] * n)[:n]

    def SetElement(self, i, v):
        while len(self.elems) <= i:
            self.elems.append(0)
        self.elems[i] = v

    def GetElement(self, i):
        return self.elems[i]

    def GetNumberOfElements(self):
        return len(self.elems)


class _SMProxy:
    def __init__(self):
        self.props = {}
        self.updated = 0

    def GetProperty(self, name):
        if name not in ("IndexedLookup", "Annotations", "IndexedColors",
                        "IndexedOpacities", "EnableOpacityMapping"):
            return None
        return self.props.setdefault(name, _Prop())

    def UpdateVTKObjects(self):
        self.updated += 1


class FakeLut:
    """Stands in for pvsimple's LUT wrapper: `IndexedLookup` is not an
    attribute (it raises), only the proxy property reaches it."""
    def __init__(self):
        self.SMProxy = _SMProxy()

    def __getattr__(self, name):
        raise AttributeError(name)


# twelve colours standing in for the default preset; the fixture below serves
# them as Brewer Qualitative Set1, whatever the variable is called
KAAMS = [1, 1, 1, 1, 0, 0, 0, 1, 0, 0, 0, 1, 1, 1, 0, 1, 0, 1, 0, 1, 1,
         0.63, 0.63, 1, 1, 0.5, 0.5, 0.5, 1, 0.5, 0.5, 0.5, 1, 1, 0.5, 0.25]


@pytest.fixture(autouse=True)
def presets(monkeypatch):
    table = {"Brewer Qualitative Set1": KAAMS, "KAAMS": [0.9, 0.1, 0.1, 0.2, 0.5, 0.7]}
    monkeypatch.setattr(cp, "preset_colors", lambda name: list(table.get(name, [])))


def _cats(*codes):
    return [{"code": float(c), "label": str(c)} for c in codes]


def test_apply_paints_one_colour_per_code_and_names_them():
    lut = FakeLut()
    note = cp.apply(lut, [{"code": 1.0, "label": "Sand"}, {"code": 3.0, "label": "Shale"}])
    assert note == ""
    p = lut.SMProxy.props
    assert p["IndexedLookup"].elems == [1]
    assert p["Annotations"].elems == ["1", "Sand", "3", "Shale"]
    assert p["IndexedColors"].elems == KAAMS[:6]
    assert p["IndexedOpacities"].elems == [1.0, 1.0]
    assert cp.is_indexed(lut)
    assert cp.read(lut) == [
        {"code": 1.0, "label": "Sand", "color": "#ffffff", "opacity": 1.0},
        {"code": 3.0, "label": "Shale", "color": "#ff0000", "opacity": 1.0}]


def test_a_code_takes_its_own_opacity_and_every_code_at_once():
    """An indexed table reads one opacity per code (IndexedOpacities), not
    the opacity function: the card's slider of a code, and its "Opacity"
    row for every code (code None), with the opacity mapping on while a
    code is translucent; kept across reconciles like the colours."""
    lut = FakeLut()
    cp.apply(lut, _cats(1, 2, 3))
    p = lut.SMProxy.props
    assert cp.set_code_opacity(lut, 2, 0) is True
    assert [c["opacity"] for c in cp.read(lut)] == [1.0, 0.0, 1.0]
    assert p["EnableOpacityMapping"].elems == [1]
    cp.apply(lut, _cats(1, 2, 3))          # the next reconcile, same codes
    assert [c["opacity"] for c in cp.read(lut)] == [1.0, 0.0, 1.0]
    assert cp.set_code_opacity(lut, None, 0.5) is True
    assert [c["opacity"] for c in cp.read(lut)] == [0.5, 0.5, 0.5]
    assert cp.set_code_opacity(lut, None, 1.7) is False, "clamped to opaque"
    assert [c["opacity"] for c in cp.read(lut)] == [1.0, 1.0, 1.0]
    assert p["EnableOpacityMapping"].elems == [0]
    assert cp.set_code_opacity(lut, 9, 0) is None, "an unknown code is refused"
    assert cp.set_code_opacity(FakeLut(), 1, 0) is None, "not painted by code"


def test_the_codes_at_opacity_zero_are_the_hidden_ones():
    """A code at 0 takes its cells out of the grid (engine/nan_mask); a
    translucent one stays, a table not painted by code hides nothing."""
    lut = FakeLut()
    cp.apply(lut, _cats(1, 2, 3))
    assert cp.hidden_codes(lut) == ()
    cp.set_code_opacity(lut, 3, 0)
    cp.set_code_opacity(lut, 2, 0.4)
    assert cp.hidden_codes(lut) == (3.0,)
    cp.set_code_opacity(lut, None, 0)
    assert cp.hidden_codes(lut) == (1.0, 2.0, 3.0)
    assert cp.hidden_codes(FakeLut()) == ()


def test_a_reconcile_keeps_the_readers_colours():
    lut = FakeLut()
    cp.apply(lut, _cats(1, 2, 3))
    assert cp.set_code_color(lut, 2, "#123456")
    assert cp.read(lut)[1]["color"] == "#123456"
    cp.apply(lut, _cats(1, 2, 3))          # the next reconcile, same codes
    assert cp.read(lut)[1]["color"] == "#123456"
    cp.apply(lut, _cats(1, 2, 3, 4))       # a code appears: fresh palette
    assert [c["color"] for c in cp.read(lut)][:2] == ["#ffffff", "#ff0000"]
    assert not cp.set_code_color(lut, 9, "#000000"), "an unknown code is refused"


def test_more_codes_than_the_preset_has_colours_says_so():
    lut = FakeLut()
    note = cp.apply(lut, _cats(*range(15)))
    assert "15 codes for the 12 colors of Brewer Qualitative Set1" in note
    colors = lut.SMProxy.props["IndexedColors"].elems
    assert len(colors) == 45 and colors[:36] == KAAMS
    generated = [tuple(colors[i:i + 3]) for i in range(36, 45, 3)]
    assert len(set(generated)) == 3, "the generated colours differ"


def test_recolor_changes_the_colours_not_the_codes():
    lut = FakeLut()
    cp.apply(lut, _cats(1, 2))
    assert cp.recolor(lut, _cats(1, 2), "KAAMS") == ""
    assert lut.SMProxy.props["IndexedColors"].elems == [0.9, 0.1, 0.1, 0.2, 0.5, 0.7]
    assert lut.SMProxy.props["Annotations"].elems == ["1", "1", "2", "2"]
    note = cp.recolor(lut, _cats(1, 2), "Nope")
    assert "Nope is not a preset of this ParaView" in note


def test_a_code_is_written_whole_and_a_name_wins_over_it():
    labels = {1: "Sand", 2.0: "Shale"}
    assert cp._label(labels, 1.0) == "Sand"
    assert cp._label(labels, 2.0) == "Shale"
    assert cp._label(labels, 3.0) == "3"
    assert cp._label({}, 2.5) == "2.5"


def test_hex_round_trip():
    assert cp.rgb_to_hex([1, 0, 0.5]) == "#ff0080"
    assert cp.hex_to_rgb("#ff0080") == pytest.approx([1, 0, 128 / 255])
    assert cp.hex_to_rgb("junk") == [0.5, 0.5, 0.5]


# ---- the categories of a property, from the tree and the data ------------

def _tree():
    asm = FakeDataAssembly()
    grid = asm.add_node_with_attrs("_grid", 0, label="IjkGrid_G", title="G",
                                   type="IjkGrid", typeCode="2")
    asm.add_node_with_attrs("_facies", grid, label="P_Facies", title="Facies",
                            type="DiscreteProperty", typeCode="4")
    asm.add_node_with_attrs("_poro", grid, label="P_Poro", title="Poro",
                            type="ContinuousProperty", typeCode="4")
    asm.add_node_with_attrs("_lith", grid, label="P_Lith", title="Lith",
                            type="CategoricalProperty", typeCode="4")
    return Tree(asm), asm.GetNodePath(grid)


def test_a_continuous_property_is_a_ramp_without_a_word(monkeypatch):
    tree, grid = _tree()
    monkeypatch.setattr(cp, "scan_codes", lambda *a: ([0.1, 0.2], 2, 100))
    assert cp.categories_for(tree, grid, "Poro", object(), "CELLS") == (None, "")


def test_a_discrete_property_gives_its_codes_sorted(monkeypatch):
    tree, grid = _tree()
    monkeypatch.setattr(cp, "scan_codes", lambda *a: ([1.0, 3.0, 7.0], 3, 100))
    cats, note = cp.categories_for(tree, grid, "Facies", object(), "CELLS")
    assert note == ""
    assert cats == [{"code": 1.0, "label": "1"}, {"code": 3.0, "label": "3"},
                    {"code": 7.0, "label": "7"}]


def test_a_categorical_property_names_its_codes(monkeypatch):
    tree, grid = _tree()
    monkeypatch.setattr(cp, "scan_codes", lambda *a: ([1.0, 2.0], 2, 100))
    monkeypatch.setattr(cat, "labels_for", lambda *a, **k: {1: "Sand", 2: "Shale"})
    cats, _ = cp.categories_for(tree, grid, "Lith", object(), "CELLS")
    assert [c["label"] for c in cats] == ["Sand", "Shale"]


def test_too_many_codes_or_none_readable_say_why(monkeypatch):
    tree, grid = _tree()
    many = [float(i) for i in range(cp.MAX_CATEGORIES + 1)]
    monkeypatch.setattr(cp, "scan_codes", lambda *a: (many, len(many), 10 ** 6))
    cats, note = cp.categories_for(tree, grid, "Facies", object(), "CELLS")
    assert cats is None and "65 distinct values" in note and "continuous ramp" in note
    monkeypatch.setattr(cp, "scan_codes", lambda *a: ([], 0, 0))
    cats, note = cp.categories_for(tree, grid, "Facies", object(), "CELLS")
    assert cats is None and "could not be read" in note


def test_a_code_per_cell_is_an_index_not_categories(monkeypatch):
    """One code per cell is an index, not a set of categories.

    A cell index on a 4x3x2 grid gives 24 codes for 24 cells; painting it by
    code would list every cell on the bar. Above a dozen codes, each code has
    to cover a few cells on average to count as a category."""
    tree, grid = _tree()
    codes = [float(i) for i in range(24)]
    monkeypatch.setattr(cp, "scan_codes", lambda *a: (codes, 24, 24))
    cats, note = cp.categories_for(tree, grid, "Facies", object(), "CELLS")
    assert cats is None
    assert "24 distinct values over 24 cells, an index rather than categories" in note
    # thirty zones over a hundred thousand cells are categories
    codes = [float(i) for i in range(30)]
    monkeypatch.setattr(cp, "scan_codes", lambda *a: (codes, 30, 100000))
    cats, note = cp.categories_for(tree, grid, "Facies", object(), "CELLS")
    assert len(cats) == 30 and note == ""
    # and a dozen codes are categories however few the cells
    codes = [float(i) for i in range(12)]
    monkeypatch.setattr(cp, "scan_codes", lambda *a: (codes, 12, 12))
    cats, note = cp.categories_for(tree, grid, "Facies", object(), "CELLS")
    assert len(cats) == 12 and note == ""


def _indexed(n, named=True):
    lut = FakeLut()
    cp._set_int(lut, "IndexedLookup", 1)
    flat = []
    for i in range(n):
        flat += [str(i), f"2011-12-{i % 28 + 1:02d}" if named else str(i)]
    cp._set_strings(lut, "Annotations", flat)
    return lut


def test_a_string_lookup_beyond_the_cap_becomes_a_ramp():
    # decatur_events' datetime: 5 373 dates put on the table by the plugin
    lut = _indexed(cp.MAX_CATEGORIES + 1)
    assert cp.tame(lut) == "ramp"
    assert not cp.is_indexed(lut) and cp.annotations_of(lut) == {}


def test_a_copy_that_lost_the_indexed_mode_is_tamed_all_the_same():
    # the view's copy of the plugin's table: the names kept, not the mode
    # (8082, 27/10 evening: a ramp drawing 5 373 labels)
    lut = _indexed(cp.MAX_CATEGORIES + 1)
    cp._set_int(lut, "IndexedLookup", 0)
    assert cp.tame(lut) == "ramp"
    assert cp.annotations_of(lut) == {}


def test_the_file_s_own_colours_stay_beyond_the_cap():
    lut = _indexed(cp.MAX_CATEGORIES + 1, named=False)
    assert cp.file_coloured(lut)
    assert cp.tame(lut) == "file colours"
    assert cp.is_indexed(lut) and len(cp.annotations_of(lut)) == cp.MAX_CATEGORIES + 1


def test_a_legend_s_worth_of_codes_is_left_alone():
    lut = _indexed(cp.MAX_CATEGORIES)
    assert cp.tame(lut) == "" and cp.is_indexed(lut)


def test_the_cap_is_the_threshold_sliders():
    assert cp.MAX_CATEGORIES == chain_domain._MAX_DISCRETE_UNIQUES


def test_scan_codes_drops_nan_and_the_integer_null_sentinel():
    np = pytest.importorskip("numpy")
    vtk_core = pytest.importorskip("vtkmodules.vtkCommonCore")
    from vtkmodules.util.numpy_support import numpy_to_vtk
    from vtkmodules.vtkCommonDataModel import vtkPolyData

    ds = vtkPolyData()
    arr = numpy_to_vtk(np.array([3.0, 1.0, float("nan"), 3.0, 2 ** 31 - 1], dtype=float))
    arr.SetName("Facies")
    ds.GetCellData().AddArray(arr)

    class _Src:
        def GetClientSideObject(self):
            return self

        def GetOutputDataObject(self, _i):
            return ds

    assert cp.scan_codes(_Src(), "Facies", "CELLS") == ([1.0, 3.0], 2, 3)
    assert cp.scan_codes(_Src(), "Nope", "CELLS") == ([], 0, 0)
    assert vtk_core is not None


def test_colors_by_code_answers_for_any_realization_of_the_property():
    # the realizations of one property share one table in a view: a chart
    # that read realization 0 wears the colours of a view painting the 3rd
    lut = FakeLut()
    cp.apply(lut, _cats(1, 2))
    assert cp.set_code_color(lut, 2, "#123456")

    class _Entry:
        def __init__(self, arr):
            self.color_array, self.categories = arr, _cats(1, 2)

    class _Scene:
        def __init__(self, arr):
            self.block_state = {"/data/g": _Entry(arr)}
            self.asked = []

        def scoped_lut(self, name):
            self.asked.append(name)
            return lut

    scene = _Scene("FACIES_real_3")
    assert cp.colors_by_code([1, 2], "FACIES_real_0", [scene]) == {1.0: "#ffffff", 2.0: "#123456"}
    assert scene.asked == ["FACIES_real_3"]
    assert cp.colors_by_code([2], "FACIES", [scene]) == {2.0: "#123456"}
    # another property: the default palette
    assert cp.colors_by_code([1, 2], "PORO", [scene]) == cp._default_colors([1.0, 2.0])


class _AnyPropProxy(_SMProxy):
    def GetProperty(self, name):
        return self.props.setdefault(name, _Prop())


def _twin():
    twin = FakeLut()
    twin.SMProxy = _AnyPropProxy()
    return twin


def test_the_steps_of_an_indexed_table_hold_each_code_s_colour_around_it():
    """The table the composite's per-block road applies where it cannot
    apply an indexed one: each code's colour from half-way to the code
    before to half-way to the next, no indexed lookup left."""
    lut = FakeLut()
    cp.apply(lut, [{"code": 1.0, "label": "Sand"}, {"code": 3.0, "label": "Shale"}])
    twin = _twin()
    assert cp.steps_from(twin, lut)
    p = twin.SMProxy.props
    assert p["IndexedLookup"].elems == [0]
    assert p["Annotations"].elems == []
    points = p["RGBPoints"].elems
    assert points[0::4] == pytest.approx([0.5, 2.0, 2.0, 3.5])
    assert [points[k + 1:k + 4] for k in range(0, 16, 4)] == [KAAMS[:3], KAAMS[:3], KAAMS[3:6], KAAMS[3:6]]
    assert twin.SMProxy.updated == 1


def test_a_table_without_codes_makes_no_steps():
    twin = _twin()
    assert not cp.steps_from(twin, FakeLut())
    assert twin.SMProxy.props == {}


def _log_tube(np, name, values, gaps=0):
    """A log channel's block as the plugin makes it: its values on points,
    how many gaps it wrote (as negative zeros) in a field array."""
    from vtkmodules.util.numpy_support import numpy_to_vtk
    from vtkmodules.vtkCommonCore import vtkIdTypeArray
    from vtkmodules.vtkCommonDataModel import vtkPolyData
    tube = vtkPolyData()
    arr = numpy_to_vtk(np.array(values, dtype=float))
    arr.SetName(name)
    tube.GetPointData().AddArray(arr)
    count = vtkIdTypeArray()
    count.SetName(name + "_nanCount")
    count.InsertNextValue(gaps)
    tube.GetFieldData().AddArray(count)
    return tube


def test_the_codes_are_read_on_the_block_the_property_colours():
    np = pytest.importorskip("numpy")
    pytest.importorskip("vtkmodules.vtkCommonCore")
    from vtkmodules.util.numpy_support import numpy_to_vtk
    from vtkmodules.vtkCommonDataModel import vtkPartitionedDataSetCollection, vtkPolyData

    # the shared source: a grid first, whose cells hold another array, then the log
    grid = vtkPolyData()
    poro = numpy_to_vtk(np.array([0.1, 0.2], dtype=float))
    poro.SetName("Poro")
    grid.GetCellData().AddArray(poro)
    tube = _log_tube(np, "Zone Index", [0.0, 0.0, 1.0, 3.0, 3.0])
    pdc = vtkPartitionedDataSetCollection()
    pdc.SetPartition(0, 0, grid)
    pdc.SetPartition(1, 0, tube)

    class _Src:
        def GetClientSideObject(self):
            return self

        def GetOutputDataObject(self, _i):
            return pdc

    # on its own block, on points whatever the association asked
    assert cp.scan_codes(_Src(), "Zone Index", "CELLS", [tube]) == ([0.0, 1.0, 3.0], 3, 5)
    assert cp.held_array(tube, "Zone Index", "CELLS")[1] == "POINTS"
    # without the block: every leaf of the source that holds the array, not its first block alone
    assert cp.scan_codes(_Src(), "Zone Index", "POINTS") == ([0.0, 1.0, 3.0], 3, 5)
    assert cp.scan_codes(_Src(), "Zone Index", "POINTS", [grid]) == ([], 0, 0)


def test_the_gaps_of_a_log_are_no_code():
    np = pytest.importorskip("numpy")
    pytest.importorskip("vtkmodules.vtkCommonCore")
    # two samples without a value, written as negative zeros: 0 is no zone here
    gaps = _log_tube(np, "Zone Index", [-0.0, 1.0, 2.0, -0.0, 2.0], gaps=2)
    assert cp.scan_codes(None, "Zone Index", "POINTS", [gaps])[0] == [1.0, 2.0]
    # a real 0 beside the gaps stays a code
    mixed = _log_tube(np, "Zone Index", [-0.0, 0.0, 2.0], gaps=1)
    assert cp.scan_codes(None, "Zone Index", "POINTS", [mixed])[0] == [0.0, 2.0]
