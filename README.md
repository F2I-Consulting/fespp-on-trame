# fespp-on-trame

## Overview

This project creates a Kitware Trame-based Docker image that embeds ParaView for remote visualization with the FESPP plugin. FESPP (F2I Energistics Standard ParaView Plugin) is a specialized plugin for visualizing Energistics data.

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

**Note**: The GPU build requires NVIDIA Docker support. Make sure your system has the NVIDIA Container Toolkit installed.

### Step 2: Build FESPP-on-Trame Image

After successfully building the ParaView builder image, return to the project root directory and build the main application image.


```bash
docker build -f Dockerfile -t fespp_on_trame:pv6.0.1 .
```

## Usage

### Running the Container

#### CPU Mode

```bash
docker run -p 8080:8080 fespp_on_trame:pv6.0.1
```

#### GPU Mode

```bash
docker run --gpus all -p 8080:8080 fespp_on_trame:pv6.0.1
```

### Accessing the Application

Once the container is running, open your web browser and navigate to:

```
http://localhost:8080/index.html
```

You should see the ParaView interface with FESPP plugin capabilities available through the web browser.

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