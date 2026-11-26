# fespp-on-trame

## Overview

This project creates a Kitware Trame-based Docker image that embeds ParaView for remote visualization with the FESPP plugin. FESPP (F2I Energistics Standard ParaView Plugin) is a specialized plugin for visualizing Energistics data.

📦 **Pre-built image on Docker Hub:** [`f2iconsulting/fesppontrame`](https://hub.docker.com/r/f2iconsulting/fesppontrame) — pull and run it directly (see [Usage](#usage)), no build required.

**What is FESPP?**
FESPP is a ParaView plugin developed by F2I-Consulting that enables the visualization of Energistics data standard file formats. It provides support for various geoscience and petroleum engineering data formats, making it easier to visualize complex subsurface models and reservoir data directly in ParaView.

For more information about FESPP, visit: https://github.com/F2I-Consulting/fespp

## Developer documentation

A full developer/handoff wiki lives under [`doc/wiki/`](doc/wiki/) (GitHub-wiki
format — copy into the repo's wiki, or browse the `.md` files directly):

- **[Home](doc/wiki/Home.md)** — entry point and navigation.
- **[Architecture](doc/wiki/Architecture.md)** — layers, the per-view scene model, end-to-end data flows, and the `state.*` catalog.
- **[Build and Run](doc/wiki/Build-and-Run.md)** — image build, run, the dev loop, and runtime internals (where the logs actually go).
- **[Glossary](doc/wiki/Glossary.md)** — RESQML/EPC/FESAPI + ParaView + Trame terms.
- A precise **per-file reference** page per subsystem (Core/Sources, Element-Types, Engine, UI…).
- **[Refactoring Notes](doc/wiki/Refactoring-Notes.md)** — opportunities for the fork.

## Features

- **Remote Visualization**: Access ParaView through a web interface using Trame
- **FESPP Integration**: Built-in support for energy industry data formats
- **Flexible Deployment**: Choose between CPU-only or GPU-accelerated modes
- **Containerized**: Easy deployment using Docker

### System Requirements

**For GPU Mode:**
- NVIDIA GPU drivers installed on host system

## Build Instructions

The project requires a two-step build process:

1. **Build the ParaView Builder Image** (prerequisite)
2. **Build the FESPP-on-Trame Image**

### Step 1: Build ParaView Builder Image

```bash
docker build -t paraview:6.0.x -f Dockerfile.paraview .
```

This image is the toolchain only (compilers, CMake, a clone of paraview-superbuild); its name predates ParaView 6.1. ParaView itself (6.1.1) is compiled in step 2, rendering through EGL — see `doc/wiki/Build-and-Run.md`.

### Step 2: Build FESPP-on-Trame Image

After successfully building the ParaView builder image, return to the project root directory and build the main application image.


```bash
docker build -f Dockerfile -t fespp_on_trame:local .
```

This compiles FESPP from GitHub at the ref pinned in the `Dockerfile` (`FESPP_GIT_TAG`). To compile a local FESPP checkout instead, run `.\build.ps1 <path-to-fespp-sources>` from the project root (Windows): it builds the same `fespp_on_trame:local` image.

## Usage

### Running the Container

#### CPU Mode

```bash
docker run -p 8080:80 fespp_on_trame:local
```

#### GPU Mode

```bash
docker run --gpus all -p 8080:80 fespp_on_trame:local
```

#### On Windows

`.\run.ps1 8080` starts `fespp_on_trame:local` in a container named `fespp_8080`, with the host's GPU when one is reachable (`-NoGpu` for software rendering, `-Stop` to remove the container).

#### On Linux, behind Apache (public site)

`bash build.sh`, then `bash deploy/linux/run.sh` and, once, `sudo bash deploy/apache/setup.sh <domain> <user>`: see `doc/wiki/Build-and-Run.md`, section "Linux behind Apache".

#### With the local AI service

`compose.yaml` starts the app and its local AI service (the Assistant's answers, a Mistral model with retrieval over the project's documentation) together:

```bash
docker compose up -d                                       # the AI on the CPU
docker compose -f compose.yaml -f compose.gpu.yaml up -d   # both on an NVIDIA GPU
```

The AI image, its model and its index are prepared once beforehand (`ia/build.ps1`, `ia/get-model.ps1`, `ia/build-index.ps1`); the header of `compose.yaml` lists them, with the variables that override its defaults.

### Accessing the Application

Once the container is running, open your web browser and navigate to:

```
http://localhost:8080/index.html
```

You should see the ParaView interface with FESPP plugin capabilities available through the web browser.

> **Port mapping:** the container serves the app on port **80** internally (Apache). `-p 8080:80` exposes it on host port `8080`; the host side is free to change (e.g. `-p 8090:80` → `http://<host>:8090`).

## Test data

The harnesses (`test-visual.ps1`, `test-browser.ps1`, the unit tests that
read a file) take their data from `data/private/`, which is not in the
repository. What they expect there, and where each set comes from:

| Files | Origin | Used by |
|---|---|---|
| `Volve_Demo_Reservoir_Grid_Depth`, `Volve_Demo_Wells_Depth`, `Volve_Demo_Horizons_Depth`, `Volve_Demo_Faults_Depth` (`.epc` + `.h5`) | Equinor's Volve field data (open data licence), in the RESQML conversion of the OSDU Reservoir DDMS sample set (open-etp-server's `initVolveIntoRddms.sh` loads the same files) | the well-log, reconcile, cursor and time-series scenarios, browser specs 25/27/28 |
| `drogon.epc` + `.h5` | Equinor's synthetic Drogon model (open), RESQML export; 12 wellbores with trajectories, marker and log frames | most visual scenarios (first load, colouring, slicing, globe, session round-trips), the health unit test |
| `olympus/` (OnlyProp, Well, GridAndProp) | TNO's Olympus field case (open benchmark), RESQML export: a grid referenced as a partial object by one file and carried by another | the partial-grid scenarios and browser specs 22/26 |
| `testingPackageCpp_blockWellbore.epc` + `.h5` | written by fesapi's own C++ example (`testingPackageCpp`), the variant with a BlockedWellbore: the only set here with one | `bw_family`, `bw_grid_gone`, `volumetrics_bw`, `release_gates`, `surfaces_bulk` |
| `vector_props.epc` + `.h5` | synthetic, 29 KB, made for this app (vector and categorical properties); the candidate for a public test set | the vector-component scenarios, browser specs 03/12/15/30, two unit tests |
| `ALK_14Layers.epc` + `.h5` | unstructured grid with NaN values; origin to be confirmed before any redistribution | the unstructured threshold and hide-NaN scenarios |
| `eml23_pwls40.epc` | EML 2.3 sample (PWLS 4.0 property dictionary); origin to be confirmed; no test reads it | — |

Volve and Drogon are published by Equinor under open licences; check their
terms before redistributing a converted file. `test-visual.ps1` mounts
`data\private` as `/tmp/testdata` in the container, which is the path the
scenarios name.

## Troubleshooting

### Common Issues

**Build fails during ParaView builder step:**
- Verify internet connection for downloading dependencies

**GPU mode doesn't work:**
- Verify NVIDIA drivers are installed: `nvidia-smi`
- Check NVIDIA Container Toolkit installation: `docker run --rm --gpus all nvidia/cuda:11.0-base nvidia-smi`
- Ensure you're using the `--gpus all` flag when running the container

**Cannot access the web interface:**
- Verify the container is running: `docker ps`
- Check if port 8080 is available on your system
- Try accessing via `http://127.0.0.1:8080` instead of `localhost`

**Build takes too long:**
- Building ParaView from source can take 1-2 hours depending on your system
- Consider using a machine with more CPU cores for faster builds

## Support

For issues related to:
- **FESPP Plugin**: Visit https://github.com/F2I-Consulting/fespp

---

**Note**: Building this project requires significant computational resources and time. The initial build can take 1-2 hours depending on your system specifications.