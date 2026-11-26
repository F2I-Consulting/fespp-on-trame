"""The two VTK filters of the scene cut (engine/blockscope/scene_crop), as a
ParaView Python plugin: `FesppScenePrep` (once per change of what the view
shows, each grid's geometry kept from one run to the next) and
`FesppSceneCut` (at each step). Plain VTKPythonAlgorithms in the pipeline,
so they run when a render pulls them, like every other filter — the first
version handed the mark to a TrivialProducer and forced `UpdatePipeline`
from the scene's projection, in the middle of a read: the render after it
crashed the session (the PO, 29/10, a log ticked on ADME while the scene
was cut). And not ProgrammableFilters: ParaView collects Python's garbage
after every run of one, 33 ms of the app's heap a step.

Loaded once per process by scene_crop (`paraview.simple.LoadPlugin`); the
work is in scene_crop's pure functions (`prep_into`, `cut_into`).
"""
import json

from paraview.util.vtkAlgorithm import smdomain, smproperty, smproxy
from vtkmodules.util.vtkAlgorithm import VTKPythonAlgorithmBase
from vtkmodules.vtkCommonDataModel import vtkDataObject


class _SameAsInput(VTKPythonAlgorithmBase):
    """One input, one output of the input's type (a whole collection) — or,
    for one dataset, of the type the stage makes of it (`STAGE`,
    scene_crop.output_class)."""

    STAGE = ""

    def __init__(self):
        super().__init__(nInputPorts=1, nOutputPorts=1, outputType="vtkDataObject")

    def FillInputPortInformation(self, port, info):
        info.Set(self.INPUT_REQUIRED_DATA_TYPE(), "vtkDataObject")
        return 1

    def RequestDataObject(self, request, inInfo, outInfo):
        from fespp_on_trame.engine.blockscope.scene_crop import output_class
        from vtkmodules.vtkCommonDataModel import vtkDataObjectTypes
        inp = inInfo[0].GetInformationObject(0).Get(vtkDataObject.DATA_OBJECT())
        out = outInfo.GetInformationObject(0).Get(vtkDataObject.DATA_OBJECT())
        if inp is None:
            return 1
        # a structured grid with layers of cells (a lattice) is an IJK grid,
        # one with none a horizon: the extent the pipeline announces says so
        # before any data has come
        from vtkmodules.vtkCommonExecutionModel import vtkStreamingDemandDrivenPipeline as sddp
        info = inInfo[0].GetInformationObject(0)
        whole = info.Get(sddp.WHOLE_EXTENT()) if info.Has(sddp.WHOLE_EXTENT()) else None
        if whole is None and inp.IsA("vtkStructuredGrid"):
            whole = inp.GetExtent()
        layered = whole is not None and whole[5] > whole[4]
        cls = output_class(self.STAGE, inp.GetClassName(), layered)
        if out is None or out.GetClassName() != cls:
            made = inp.NewInstance() if cls == inp.GetClassName() else vtkDataObjectTypes.NewDataObject(cls)
            outInfo.GetInformationObject(0).Set(vtkDataObject.DATA_OBJECT(), made)
        return 1

    def _io(self, inInfo, outInfo):
        return (inInfo[0].GetInformationObject(0).Get(vtkDataObject.DATA_OBJECT()),
                outInfo.GetInformationObject(0).Get(vtkDataObject.DATA_OBJECT()))


@smproxy.filter(name="FesppScenePrep", label="FesppScenePrep")
@smproperty.input(name="Input", port_index=0)
@smdomain.datatype(dataTypes=["vtkDataObject"], composite_data_supported=True)
class FesppScenePrep(_SameAsInput):
    """Each cell's id, an IJK grid made unstructured with its face table,
    lines and points made cells of their own, every cell's extent beside
    it; the grids' geometry kept from one run to the next."""

    STAGE = "prep"

    def __init__(self):
        super().__init__()
        self._cache = {}

    def RequestData(self, request, inInfo, outInfo):
        from fespp_on_trame.engine.blockscope.scene_crop import prep_into
        from fespp_on_trame.engine.blockscope.scene_crop import _trace
        _trace("prep in")
        inp, out = self._io(inInfo, outInfo)
        if inp is not None and out is not None:
            prep_into(inp, out, self._cache)
        _trace("prep out")
        return 1


@smproxy.filter(name="FesppSceneCut", label="FesppSceneCut")
@smproperty.input(name="Input", port_index=0)
@smdomain.datatype(dataTypes=["vtkDataObject"], composite_data_supported=True)
class FesppSceneCut(_SameAsInput):
    """The scene cut to the boxes (JSON): an IJK grid as its exposed faces,
    any other leaf as its kept cells."""

    STAGE = "cut"

    def __init__(self):
        super().__init__()
        self._boxes = "[]"

    @smproperty.stringvector(name="Boxes", default_values="[]")
    def SetBoxes(self, value):
        if value != self._boxes:
            self._boxes = value
            self.Modified()

    def RequestData(self, request, inInfo, outInfo):
        from fespp_on_trame.engine.blockscope.scene_crop import cut_into
        from fespp_on_trame.engine.blockscope.scene_crop import _trace
        _trace("cut in")
        inp, out = self._io(inInfo, outInfo)
        if inp is not None and out is not None:
            cut_into(inp, out, json.loads(self._boxes or "[]"))
        _trace("cut out")
        return 1


@smproxy.filter(name="FesppDomainConvert", label="FesppDomainConvert")
@smproperty.input(name="Input", port_index=0)
@smdomain.datatype(dataTypes=["vtkDataObject"], composite_data_supported=True)
class FesppDomainConvert(_SameAsInput):
    """The leaves of flat indices `Flats` (JSON) with their points' z
    converted on the velocity model `Cube` (its key in
    domain_convert.CUBES: the stage runs in the server's own process)
    `To` depth or time (engine/blockscope/domain_convert)."""

    STAGE = "convert"

    def __init__(self):
        super().__init__()
        self._flats, self._cube, self._to = "[]", "", "depth"

    @smproperty.stringvector(name="Flats", default_values="[]")
    def SetFlats(self, value):
        if value != self._flats:
            self._flats = value
            self.Modified()

    @smproperty.stringvector(name="Cube", default_values="")
    def SetCube(self, value):
        if value != self._cube:
            self._cube = value
            self.Modified()

    @smproperty.stringvector(name="To", default_values="depth")
    def SetTo(self, value):
        if value != self._to:
            self._to = value
            self.Modified()

    def RequestData(self, request, inInfo, outInfo):
        from fespp_on_trame.engine.blockscope.domain_convert import convert_into
        inp, out = self._io(inInfo, outInfo)
        if inp is not None and out is not None:
            convert_into(inp, out, json.loads(self._flats or "[]"), self._cube or "", self._to)
        return 1


@smproxy.filter(name="FesppSceneTrace", label="FesppSceneTrace")
@smproperty.input(name="Input", port_index=0)
@smdomain.datatype(dataTypes=["vtkDataObject"], composite_data_supported=True)
class FesppSceneTrace(_SameAsInput):
    """A witness after the cut, only while a scenario traces a crash: the
    cut ran when it runs."""

    def RequestData(self, request, inInfo, outInfo):
        from fespp_on_trame.engine.blockscope.scene_crop import _trace
        _trace("cut done, the representation next")
        inp, out = self._io(inInfo, outInfo)
        if inp is not None and out is not None:
            out.ShallowCopy(inp)
        return 1
