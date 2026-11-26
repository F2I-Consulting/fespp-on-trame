"""Tests for three widget contracts: the Attributes card's events reach the
server, the Statistics CSV export names every metric column, and
no .gitignore keeps a widget's built bundle out of git.

A name missing from an element's `_event_names` is the one failure trame
keeps quiet about: the binding is never written into the tag, and the
button emits an event nobody listens to. The check runs on the element as
trame renders it.

The Compare export writes one column per metric, named by its CSV table; a
metric without an entry there gets a header such as "undefined (mD)", or
none at all in a block without a unit. The check runs on the built bundle,
the file the browser runs, and holds the names to the Statistics export's,
so that a metric reads the same in both files.

The Docker image is built from the checkout as it is, bundles included: a
bundle git ignores is missing from a fresh clone, and the image built from
that clone serves no such widget.
"""
import fnmatch
import importlib.util
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WIDGETS = ROOT / "widgets"
ATTRIBUTES = WIDGETS / "attributes"
COMPARE = WIDGETS / "compare"
COMPARE_BUNDLE = (COMPARE / "trame_fespp_compare" / "module" / "serve"
                  / "trame_fespp_compare.umd.js")


def _version(init):
    text = init.read_text(encoding="utf-8")
    found = re.search(r'__version__\s*=\s*"(\d+)\.(\d+)\.(\d+)"', text)
    assert found, f"no __version__ in {init.relative_to(ROOT)}"
    return tuple(int(v) for v in found.groups())


# ---- the Attributes card: Explore -------------------------------------------

def _stub_server():
    """Return the parts of a server an element touches while it renders: a
    state with a translator that leaves an expression as is, the client
    type, the module hook the widget package calls, and the name a
    controller method is triggered by."""
    class Translator:
        def translate_js_expression(self, state, expr):
            return expr

    state = types.SimpleNamespace(translator=Translator(), defaults={})
    state.setdefault = lambda name, value: state.defaults.setdefault(name, value)
    return types.SimpleNamespace(client_type="vue3", state=state, controller=None,
                                 enable_module=lambda module: None,
                                 trigger_name=lambda method: method.__name__)


def _attributes_widget():
    """The repository's attributes.py, loaded from its file: the image puts
    a copy of the package in site-packages, and that copy may already be
    imported under the package's name."""
    pytest.importorskip("trame_client.widgets.core")
    if str(ATTRIBUTES) not in sys.path:
        sys.path.insert(0, str(ATTRIBUTES))
    path = ATTRIBUTES / "trame_fespp_attributes" / "widgets" / "attributes.py"
    spec = importlib.util.spec_from_file_location("_repo_attributes_widget", path)
    widget = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(widget)
    return widget


def node_highlight(indices, view_id):
    """Stands for the controller method tools_config binds to highlight."""


def test_the_attributes_element_declares_every_event_its_panel_emits():
    """The `emits` list of the Vue panel, read from its source, is what the
    element must declare: an event it does not declare is never bound."""
    element = _attributes_widget().AttributesPanel(trame_server=_stub_server())
    src = (ATTRIBUTES / "vue-components" / "src" / "AttributesPanel.vue").read_text(
        encoding="utf-8")
    emits = re.search(r"emits:\s*\[([^\]]*)\]", src)
    assert emits, "no emits list in AttributesPanel.vue"
    emitted = re.findall(r"""["']([\w-]+)["']""", emits.group(1))
    assert "highlight" in emitted
    declared = {n if isinstance(n, str) else n[0] for n in element._event_names}
    missing = [e for e in emitted if e.replace("-", "_") not in declared]
    assert not missing, f"emitted by the panel, never bound by trame: {missing}"


def test_the_rendered_tag_binds_highlight():
    """Bound the way tools_config binds it, a controller method and the
    view id, the event goes all the way to the tag trame writes."""
    element = _attributes_widget().AttributesPanel(
        trame_server=_stub_server(), highlight=(node_highlight, "[$event, 'view-1']"))
    html = element.html
    assert html and html.startswith("<attributes-panel ")
    assert "@highlight=\"trigger('node_highlight', [$event, 'view-1'])\"" in html


def test_the_attributes_bundle_emits_highlight():
    """The other half of the binding: the built panel emits the event."""
    bundle = (ATTRIBUTES / "trame_fespp_attributes" / "module" / "serve"
              / "trame_fespp_attributes.umd.js")
    if not bundle.exists():
        pytest.skip("the widget is not built here (npm run build in vue-components)")
    text = bundle.read_text(encoding="utf-8")
    assert re.search(r"""\$emit\(["']highlight["']""", text)


@pytest.mark.parametrize("init,floor", [
    (ATTRIBUTES / "trame_fespp_attributes" / "__init__.py", (0, 10, 1)),
    (COMPARE / "trame_fespp_compare" / "__init__.py", (0, 1, 1)),
], ids=["attributes", "compare"])
def test_the_widget_version_names_the_fixed_bundle(init, floor):
    """The served path `__<package>_<version>` is the cache-busting the
    application relies on: a browser holding the bundle from before a fix
    fetches the fixed one only under a new version."""
    assert _version(init) >= floor


# ---- the Statistics export --------------------------------------------------

def _compare_bundle_csv():
    """The metric list (METRIC_KEYS) and the CSV column names (CSV_METRIC) of
    the Statistics panel, read from its minified bundle."""
    assert COMPARE_BUNDLE.exists(), (
        "the compare bundle is missing: npm run build in widgets/compare/vue-components")
    text = COMPARE_BUNDLE.read_text(encoding="utf-8")
    keys = re.search(r'\[\s*"Cardinality"\s*,\s*"NaN_count"\s*,\s*"Minimum"[^\]]*\]', text)
    names = re.search(r'\{[^{}]*\bCardinality"?\s*:\s*"value_count"[^{}]*\}', text)
    assert keys and names, "the metric list or the CSV table is not in the compare bundle"
    pairs = re.findall(r'(?:"([^"]+)"|([A-Za-z_$][\w$]*))\s*:\s*"([^"]*)"', names.group(0))
    return (re.findall(r'"([^"]+)"', keys.group(0)),
            {quoted or bare: name for quoted, bare, name in pairs})


def test_the_compare_bundle_names_p10_and_p90():
    keys, names = _compare_bundle_csv()
    assert "P10" in keys and "P90" in keys
    assert names.get("P10") == "p10"
    assert names.get("P90") == "p90"


def test_every_compare_metric_has_a_csv_column_name():
    keys, names = _compare_bundle_csv()
    missing = [k for k in keys if not names.get(k)]
    assert not missing, f"exported under no column name of their own: {missing}"


def test_the_compare_csv_names_each_metric_in_the_order_of_the_engine():
    """Each metric under its own column name, in the canonical order of the
    engine (compare_matrix._METRIC_KEYS) that the widget mirrors."""
    from fespp_on_trame.engine import compare_matrix

    keys, names = _compare_bundle_csv()
    assert keys == list(compare_matrix._METRIC_KEYS)
    assert {k: names.get(k) for k in keys} == {
        "Cardinality": "value_count", "NaN_count": "no_value_count",
        "Minimum": "min", "Maximum": "max", "Mean": "mean",
        "Mean (V)": "mean_volume_weighted",
        "Mean (PV)": "mean_pore_volume_weighted",
        "Mean (L)": "mean_length_weighted",
        "Standard Deviation": "std_dev", "Variance": "variance",
        "Sum": "sum", "P10": "p10", "Q1": "q1", "Median": "median",
        "Q3": "q3", "P90": "p90",
        "Skewness": "skewness", "Kurtosis": "kurtosis",
        "M2": "m2", "M3": "m3", "M4": "m4"}


# ---- the bundles in git -----------------------------------------------------

def _package(widget):
    """The widget's Python package: the folder whose module/ holds serve/."""
    for package in sorted(widget.glob("trame*")):
        if (package / "module").is_dir():
            return package
    return None


def _bundle_paths(widget):
    """The serve folder of a widget and the files the build writes there,
    relative to the widget's folder (a trailing "/" marks the folder)."""
    name = _package(widget).name
    serve = f"{name}/module/serve"
    return [serve + "/", f"{serve}/{name}.umd.js", f"{serve}/style.css"]


def _ignores(pattern, rel):
    """Whether `pattern`, a line of a .gitignore at the widget's root,
    ignores `rel` or one of the folders above it. fnmatch's "*" also
    crosses "/", which errs towards a match: the safe side for a check
    that wants none."""
    if pattern.startswith("!"):
        return False
    dir_only = pattern.endswith("/")
    anchored = "/" in pattern.rstrip("/")
    glob = pattern.strip("/")
    parts = rel.rstrip("/").split("/")
    for i in range(1, len(parts) + 1):
        is_dir = i < len(parts) or rel.endswith("/")
        if dir_only and not is_dir:
            continue
        target = "/".join(parts[:i]) if anchored else parts[i - 1]
        if fnmatch.fnmatchcase(target, glob):
            return True
    return False


def _patterns(gitignore):
    lines = (line.strip() for line in gitignore.read_text(encoding="utf-8").splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def test_the_matcher_sees_a_rule_that_hides_the_bundle():
    """The check below is not vacuous: a rule naming the serve folder, and
    looser ones, are seen to hide the bundle; rules aimed elsewhere are not."""
    rel = "trame_fespp_tree/module/serve/trame_fespp_tree.umd.js"
    for pattern in ("trame_fespp_tree/module/serve/", "/trame_fespp_tree/module/serve",
                    "serve/", "module/", "trame_*/", "*.umd.js", "**/serve"):
        assert _ignores(pattern, rel), pattern
    for pattern in ("trame_fespp_attributes/module/serve/", "vue-components/node_modules/",
                    "__pycache__/", "*.py[cod]", "dist/", "!serve/"):
        assert not _ignores(pattern, rel), pattern


GITIGNORES = sorted(WIDGETS.glob("*/.gitignore"))


@pytest.mark.parametrize("gitignore", GITIGNORES, ids=[g.parent.name for g in GITIGNORES])
def test_no_widget_gitignore_hides_its_bundle(gitignore):
    widget = gitignore.parent
    if _package(widget) is None:
        pytest.skip("no widget package beside this .gitignore")
    hits = [f"{pattern!r} hides {rel}" for pattern in _patterns(gitignore)
            for rel in _bundle_paths(widget) if _ignores(pattern, rel)]
    assert not hits, f"{gitignore.relative_to(ROOT)}: " + "; ".join(hits)


def test_git_ignores_no_widget_bundle():
    """Every rule git reads, the root .gitignore's included, leaves each
    widget's bundle visible to git."""
    git = shutil.which("git")
    if git is None or not (ROOT / ".git").exists():
        pytest.skip("no git, or not a git checkout")
    paths = [f"widgets/{widget.name}/{rel}"
             for widget in sorted(WIDGETS.iterdir())
             if widget.is_dir() and _package(widget) is not None
             for rel in _bundle_paths(widget)]
    run = subprocess.run([git, "check-ignore", "--no-index", "-v", *paths],
                         cwd=ROOT, capture_output=True, text=True)
    # 0: some path is ignored, 1: none is, anything else: git could not tell
    if run.returncode not in (0, 1):
        pytest.skip(f"git check-ignore cannot run here: {run.stderr.strip()[:200]}")
    assert run.returncode == 1, "ignored by git:\n" + run.stdout
