"""Hide the cells whose property is NaN, so their neighbours' faces show.

A cell made transparent through the colour table (NaN opacity 0) leaves a
see-through hole: the Surface representation extracts the grid's SKIN, and
the faces a NaN cell shares with its neighbours are internal — never
extracted. Removing the cell BEFORE the geometry filter makes them skin.

The removal is VTK's own blanking: the HIDDENCELL bit (32) of the
`vtkGhostType` cell array, the one FESPP already sets on dead cells
(`BlankCell`). ParaView's CALCULATOR writes a new `vtkGhostType` on its own
output (the input grid keeps its array), equal to the old one with the bit
OR-ed in where the property is NaN (`x != x` holds for NaN only). The grid
keeps its type, so an explicit structured grid still feeds the IJK crops
downstream, which keep the mask (the crop copies the array). On a 3x3x3
grid with its top-centre cell NaN, the rendered skin goes from 54 faces to
58 (the hole's five inner faces, minus the cell's own top); dead cells stay
hidden.

Why the Calculator and not a Python filter (VTKPythonAlgorithmBase): a
Python algorithm in the RENDERED pipeline re-executes inside interactor
callbacks, and together with a Python observer on the camera that is a
segfault (see "NO OBSERVER ON THE CAMERA" in `blockscope/globe_scene.py`).
The 3D views carry Python wheel observers. The Calculator is C++.

The same mask hides the cells of the CODES a reader puts at opacity 0 on
a property painted by code (an indexed table's `IndexedOpacities`): a
transparent code is the same see-through hole as a NaN cell.

No ParaView import here: the expression and the proxy settings are plain
data, unit-tested; `IjkGrid.set_cell_mask` creates the proxy.
"""

HIDDEN = 32          # vtkDataSetAttributes.HIDDENCELL
GHOSTS = "vtkGhostType"  # vtkDataSetAttributes.GhostArrayName()


def expression(array_name, has_ghosts, nan=True, codes=()):
    """The Calculator function that ORs HIDDENCELL into the ghost array
    where `array_name` is NaN (`nan`) or holds one of `codes` — the codes
    of a property painted by code that the reader put at opacity 0: the
    same see-through hole as a NaN cell, the same cure. None when there is
    nothing to hide or the name cannot be written in one (it holds a double
    quote). The name is always quoted: ParaView's array names keep `-`,
    `.`, spaces and parentheses. Without a ghost array on the input the
    result is the mask alone. The conditions exclude each other (a NaN is
    no code, a value one code at most): their sum is 0 or 1."""
    if not array_name or '"' in array_name:
        return None
    q = f'"{array_name}"'
    terms = [f"({q} != {q})"] if nan else []
    terms += [f"({q} == {format(c, '.17g')})" for c in sorted({float(c) for c in codes or ()})]
    if not terms:
        return None
    hit = terms[0] if len(terms) == 1 else "(" + " + ".join(terms) + ")"
    if not has_ghosts:
        return f"{HIDDEN}*{hit}"
    # + 32 only where the bit is not set yet: floor(g/32) % 2 is that bit
    return f"{GHOSTS} + {HIDDEN}*{hit}*(1 - (floor({GHOSTS}/{HIDDEN}) % 2))"


def calculator_settings(array_name, has_ghosts, nan=True, codes=()):
    """The Calculator properties, None when the name is unusable or there
    is nothing to hide."""
    fn = expression(array_name, has_ghosts, nan=nan, codes=codes)
    if fn is None:
        return None
    return {
        "AttributeType": "Cell Data",
        "ResultArrayName": GHOSTS,
        "ResultArrayType": "Unsigned Char",
        "Function": fn,
    }
