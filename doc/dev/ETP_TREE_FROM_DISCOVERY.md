# The OSDU tree from ETP discovery, not from the XML (design, 2026-10-14)

## Why

Loading a dataspace from a hosted store (ADME interop) takes 12 to 16 s for
`demo/Volve`, of which 10 to 14 s is the store serving the XML of the 4 485
objects the lean load keeps (`GetDataObjects`, charged per object), while
the discovery (`GetResources`) lists the 5 274 resources in 0.8 s. The XML
is read mostly to know who belongs to whom. The probe of 2026-10-14
(`doc/private/probes/edges_probe.cpp`) showed that ADME answers the same
discovery with the relations: `includeEdges = true` adds a
`GetResourcesEdgesResponse` of 20 107 edges (source URI, target URI,
relationship kind, all Primary) in 0.5 to 0.6 s, two messages, and the
edges cover everything the tree needs (89 type pairs: property to
representation, representation to interpretation to feature, frame and
marker frame to trajectory, trajectory to wellbore interpretation, sub
representation to grid, property sets, time series, string lookups, CRS,
MdDatum, stratigraphic column and units, activities).

Target: the tree in 2 to 3 s instead of 12 to 16 s, every object deferred,
its XML fetched at first use.

## What exists (FESPP, `ResqmlDataRepositoryToVtkPartitionedDataSetCollection`)

- `discoverDataspace(dataspace, types)`: `GetResources` on the dataspace
  (context depth 1, scope `self` then `targets`), no edges.
- `addDataspace`: discovery, then one `GetDataObjects` of every resource
  but the deferred types (`FESPP_ETP_LEAN`, 2026-10-13: stratigraphy and
  activities, `_deferred[uuid] = uri`), fesapi deserialises, then
  `buildDataAssemblyFromDataObjectRepo` walks the typed fesapi sets
  (`getIjkGridRepresentationSet`, polylines, triangulated sets, grids 2D,
  unstructured grids, point sets, then wells, time series, realizations)
  and builds the `vtkDataAssembly`.
- `ensureFetched(uuid)`: a deferred object is fetched with every deferred
  object of its type and dataspace in one `GetDataObjects`; called by the
  query channel (XML, relations, fields), by the marker frame fields and by
  the stratigraphy.
- Node contract read by the application (`engine/tree.py`, the tree widget
  from the assembly XML): node name `_<uuid>`, attributes `typeCode`,
  `type` (the `TreeViewNodeType` name), `label` (valid node name), `title`
  (as shown), plus the folders `_gridfolder_<uuid>`, `_propsfolder_<uuid>`,
  `_subrepfolder_<uuid>`, `_bwfolder_<uuid>`, `_logsfolder_<well>`,
  `_markersfolder_<well>`, and the marker nodes' `md` (2026-10-13).

## What was built first: the lazy leaves (2026-10-14)

Reading the whole builder showed why a tree built from the resources alone
is not enough: the property nodes carry attributes only the XML holds
(`propertyKind`, `uom`, `minvalue`/`maxvalue`, `componentCount`, the extra
metadata), read by a dozen modules of the application (statistics,
distribution, compare, calculator, log-vs-grid, health, time series, the
assistant); the time-series and realization groupings need the time and
realization indices of the XML. So the first step keeps the current builder
and leaves on the store only the objects the edges can place without
changing the tree, the leaves:

- the properties (continuous, discrete, categorical, comment, points) that
  hang from exactly one representation the tree shows its properties under,
  or from a wellbore frame, and that point at no time series and share no
  name with another property of the same representation (a realization);
- the wellbore frames whose channels can all wait and that have a
  trajectory.

On demo/Volve that is about half of the objects. Their nodes are added
after the wells (`addLazyLeaves`): a frame under the logs folder of its
wellbore, a channel under its frame, a property under its representation
(its properties folder for a grid) and inside its property sets, sorted by
title, each node with the `typeCode`, `type`, `label` and `title` the
current builder gives it, the title being the resource's name. Their XML
comes:

- at first use, by group: `ensureFetched` (now also called by every mapper
  before it resolves its object) fetches a leaf with the other leaves of the
  same representation or frame, and the frame itself, in one request;
- in the background: the application asks `LazyFetchKey = "<nonce>|200"`
  after each dataspace load, between the user's gestures and never during
  a read, and refreshes the tree once they are all in.

Either way the node gets the attributes only the XML holds
(`addDefaultToDataAssemblyNode` again). `FESPP_ETP_LAZY_LEAVES=0` (or
`FESPP_ETP_LEAN=0`) loads as before; the disk cache is not used for a lazy
load (it keeps no edges); a store that answers no edge loads as before.

Checked on 2026-10-14 (probe `doc/private/probes/tree_dump.py`): the tree is
the same node for node with and without the lazy leaves, on the local
open-etp-server (2 528 nodes, 833 leaves, which serves the edges too) and on
ADME (4 619 nodes, 2 598 leaves); the order of the children is the same
under every parent but the root, whose wellbores come in the order of
fesapi's hash map (no meaning, it already changes with the number of
objects loaded) and are sorted by the application anyway. The readings of
the grid, its properties, the wells and their channels are unchanged; the
EPC screenshots too. Measured loads of demo/Volve on ADME: 9.5, 7.5, 10.2,
7.8 s with the lazy leaves against 10.3, 15.0, 10.5, 10.7 s without; the
background read of the 2 598 leaves takes about 11 s.

**ADME's cost model** (probe `doc/private/probes/cost_probe.cpp`, quiet
store, two rounds that agree): a `GetDataObjects` costs about 0.13 s per
request, 2.0 ms per object whatever its type, and about 0.1 s per MB, which
only shows on heavy objects (the 29 marker frames, 5 MB, 0.45 to 0.57 s). So
the full load costs about 11 s of store time, the lazy load about 5 s, and
what remains is the skeleton: 1 733 objects (interpretations, features,
representations, wells, property kinds and sets, CRS), 3.8 s. A tree built
from the resources alone (below) would ask only the marker frames and the
time-series properties at load, about 1 s: the load step of demo/Volve
would go from 7.5 to 10 s to about 2.5 to 3.5 s, discovery and connection
included. That is the measured basis for the next step.

The full builder from the resources below remains the next step, for the
skeleton (representations, interpretations, features, wells).

## Step 2 built: the skeleton too (2026-10-14)

Besides the leaves, the representations, the wellbore trajectories, their
MD datums and deviation surveys, and the interpretations and features stay
on the store at load (`chooseSkeleton`). A deferred representation or
trajectory gets a partial stub (`DataObjectRepository::createPartial`, the
resource's name as title), and the walkers treat such a stub as a full
object wherever they only read its uuid, title, XML tag and relations
(`isLazyStub`): `searchRepresentations` builds its grid container, its
properties folder and its SolidColor node as for a loaded grid,
`addDefaultToDataAssemblyNode` skips the XML-only attributes of a partial
object, `resolveGroupingParent` takes the interpretation and feature from
the edges, `searchWellboreTrajectory` hands a stub to `addStubWellbore`
(the wellbore from the edges, then `searchWellboreFrame` on the stub), and
the horizon grids are listed without walking the deferred features
(`horizonGrid2dSet`). A representation stays loaded when the walkers need
its XML (a realization among its properties, a blocked wellbore or a
representation set pointing at it), a trajectory too (a blocked wellbore, a
set, or WITSML objects in the dataspace, for the completions).
`ensureFetched` adds the closure a node needs to be read (its targets that
hold geometry, MD, CRS, property kinds, lookups, time series, the wellbore
interpretation and feature: not the geological interpretations and
features), in the same request; `fetchLazy` completes the nodes (the
SolidColor title kept, the grid container's attributes, the trajectory's
`mdDatumPosition` once trajectory and datum are read).

Checked: the tree is the same node for node and in order on the local
store (2 528 nodes; 833 leaves and 981 skeleton objects deferred, 418
objects read at load) and on ADME (4 619 nodes); the grid, its properties,
the wells and their channels read as before. ADME demo/Volve: **4.8 and
5.5 s against 15.2 and 15.3 s** (discovery with edges 1.9 s, 458 objects and
7.2 MB in 1.7 to 2.3 s, tree 1.1 s).

**Opt-in in FESPP** (`FESPP_ETP_LAZY_LEAVES=1`, off by default): in
ParaView itself nothing reads the deferred objects in the background, so
a ParaView user keeps the load as it was. The fespp_on_trame image sets
the variable (Dockerfile). `FESPP_ETP_LAZY_SKELETON=0` keeps the skeleton
loaded (leaves only).

**The crash of 2026-10-14 (crhome, demo/Volve).** The first trial image
killed the session during the background read: fesapi's TYPED
`getDataObjectByUuid<T>` throws `std::invalid_argument` when the uuid is
an object of another type, and on ADME an MD datum's sources are
trajectories AND deviation surveys; the exception went through
`RequestData` to `std::terminate`. Every lookup of the lazy code is now
untyped plus a `dynamic_cast`, and every fetch (`ensureFetched`,
`fetchLazyLeaves`) and the lazy part of the tree build are behind a
catch that logs a warning. Checked on three ADME dataspaces (demo/Volve,
carl/teapot, geosiris/lutetia): tree identical with and without, the
whole background read done (4 027, 250 and 682 objects), wells, grid and
properties read with the lazy load on. The local store had no deviation
survey among a datum's sources: test the background read on ADME too.

## Step 3: read when opened (2026-10-14)

The first trial read everything in the background right after the load,
200 objects a request: about 1.1 s each on ADME, on the server loop that
also renders the views, so a camera turned by jerks for the 20 s of the
read (the PO). And the assistant's examples, built at every new tree,
asked the category names of the 33 categorical properties one by one:
thirty requests, 4.5 s added to the load. Now:

- **What is opened is read, in one request.** `addLazyFamily(uuid)`: the
  object if it waits on the store and, for a representation, a
  trajectory, a frame or a lazy property, every deferred property, frame
  and channel of that holder; `ensureFetched` (a selection: a grid comes
  with its properties) and `fetchLazyFor(uuids)` use it, plus the
  closure. `LazyFetchKey = "<nonce>|<max>|<uuid>,..."` is the channel
  (`repo_query.lazy_fetch(..., uuids=)`), and the XML query on a list
  reads the whole list at once first.
- **The tree widget announces an expanded node** (`node-open`, its path;
  not the ancestors a reveal opens); `boot.tree_node_open` asks for the
  node and its children. ADME demo/Volve: a properties folder 4 objects
  in 0.16 s, a wellbore 239 in 0.78 s, a logs folder 78 in 0.33 s.
- **A node still on the store says so**: `lazy` = `1` on the node, `0`
  once read (this VTK has no `RemoveAttribute`). The health check counts
  such properties apart ("still on the store") instead of reporting them
  without kind or unit.
- **The background read runs only while a view that weighs every
  property is open** (assistant, Statistics: `lazy_read_all`), 40 objects a
  request (0.25 s), never during a load and never while a camera is
  handled: `camera.ACTIVITY`, fed by observers on each view's interactor
  (the web protocol hands the presses and releases to it; a press without
  release counts 10 s at most).
- **The assistant builds its examples only while its view is shown**
  (`examples_wanted`), and reads the categorical properties in one
  request first (33 objects and their closure, 149 in 0.68 s).
- **A light refresh after a lazy read**: `lazy_rev` (health, the Statistics
  kind tree and the assistant's catalogue follow it), the browser tree's
  XML sent again at the end of the background read, or after an expand
  that read a vector property (its x N tag). Never `assembly_rev`, which
  means new data and wipes the Statistics reads and the cell geometry.
- The well log panel reads its wells' lazy frames and channels in one
  request before listing the unticked ones by kind; the volumetrics
  scenario reads its grid's properties first.

Not read when opened, and why it does not matter: the time series and
realization properties are never left on the store (`chooseLazyLeaves`).

Checked: unit suite (1 869), the browser scenarios tree, assistant,
Compare and session; on ADME (demo/Volve, carl/teapot, geosiris/lutetia)
the tree is identical with and without, the whole background read
completes, wells, grid and properties read.

## Design

### 1. Discovery with edges

`discoverDataspace` sends `GetResources` with `includeEdges = true` through
a handler of its own (`DiscoveryHandlers` subclass collecting the
`GetResourcesResponse` resources and the `GetResourcesEdgesResponse` edges,
as in the probe) and keeps, per dataspace:

- `_resources`: uri -> {uuid, type (from the URI), name};
- `_targets`: uri -> [target uris], `_sources`: uri -> [source uris].

Fallback when a store answers no edge: the current path (XML of every
non deferred object).

### 2. The tree from the resources

`buildDataAssemblyFromResources()` reproduces the structure of
`buildDataAssemblyFromDataObjectRepo` from types, names and edges:

| Node | From |
|---|---|
| Representation (grid 2D, IJK and truncated IJK, point set, polyline set, polyline, triangulated set, unstructured grid; 2.0.1 and 2.2 type names) | resource type and name; its interpretation and feature by the target edges (grouping nodes of the non flat hierarchy modes) |
| Properties folder and property nodes of a representation | source edges of the representation whose source type is a property; node type from the property type (continuous, discrete, categorical, points, comment) |
| Sub representations folder | source edges of type SubRepresentation |
| Wellbore, trajectory | `WellboreTrajectoryRepresentation` resources; the wellbore name from the trajectory's target `WellboreInterpretation` then `WellboreFeature` |
| Logs folder, channels | `WellboreFrameRepresentation` sources of the trajectory; a channel per property source of the frame |
| Markers folder, marker frames | `WellboreMarkerFrameRepresentation` sources of the trajectory |
| Markers | NOT in the discovery: a marker is an element of the frame's XML. The marker frames' XML is fetched at load (29 objects, 5 MB on Volve, a tenth of a second) and the markers are built as today through fesapi |
| Time series groups | the properties with a `TimeSeries` target edge; the index in the series is in the property XML: those properties' XML is fetched at load (150 on Volve) |
| Realizations | the realization index is in the property XML and has no edge: not grouped in this mode (documented limit; none on Volve) |
| Blocked wellbores, completions, perforations | source edges to the trajectory (`BlockedWellboreRepresentation`), as the current code; the WITSML completions keep their current path |

Titles are the resource names; the order of siblings as today (sorted by
title). The node attributes are the same, so `engine/tree.py` and the tree
widget do not change.

### 3. Everything deferred, fetched by dependency

Every resource goes to `_deferred[uuid] = uri` except what the tree itself
had to read (marker frames, time series properties). `ensureFetched(uuid)`
changes strategy: instead of "every deferred object of this type", it
fetches the object and the closure of its target edges (what fesapi needs
to deserialise it without partial stubs on its path: a property needs its
representation and property kind; a representation its CRS, interpretation,
HDF proxy reference; a frame its trajectory, which needs its MdDatum and
CRS), capped at a few dozen objects, in one `GetDataObjects`. The per type
batch stays for the stratigraphy (the column needs them all).

`loadMapper`, the query channel and the frame geometry cache already call
`ensureFetched` first; the mapper's reads of fesapi objects need no change.

### 4. Switch and comparison

`FESPP_ETP_TREE=resources` turns the new builder on (default `objects`
until validated). The two trees are compared on the local open-etp-server
(the probe `adme_load.py` prints the node count by type: 4 619 nodes on
`demo/Volve`): same paths, types and titles, markers and time series
included. Then the measurement on ADME, the image, the trial on 8082 and
the swap.

### Open points

- The probe's "sources depth 1" of one grid returned 6 resources where the
  grid has 154 continuous properties: ADME may cap or page the sources of a
  context; the dataspace listing with edges is complete, so the builder
  relies on that listing only.
- Whether open-etp-server serves the edges (to check with the probe and a
  basic authorization) decides where the comparison can run.
- Counts without the XML (cell count of a grid for the extent note, node
  count of a frame): from the resource's custom data when present, else at
  first use.

## Effort

Discovery with edges and the index: half a day. The builder: two to three
days, the wells and the markers being the long part. The dependency fetch:
one day with its tests. Measurement, image, swap: half a day. Each step
needs a FESPP rebuild (about 45 minutes).
