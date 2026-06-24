# FESPP-on-Trame

Web-based viewer for **Energistics / RESQML** data (EPC + HDF5): ParaView with the
**FESPP** plugin, served in your browser through **Kitware Trame**, with NVIDIA
**EGL headless GPU** rendering.

- 📚 **Sources & full documentation:** https://github.com/F2I-Consulting/fespp-on-trame
- 🔌 **FESPP plugin:** https://github.com/F2I-Consulting/fespp

---

## Quick start

```bash
docker pull f2iconsulting/fesppontrame
```

**CPU (software rendering):**
```bash
docker run -d -p 8080:80 f2iconsulting/fesppontrame
```

**GPU (NVIDIA, recommended):**
```bash
docker run -d --gpus all -p 8080:80 f2iconsulting/fesppontrame
```

Then open **http://localhost:8080/index.html**

> **Port mapping:** the container serves on port **80** internally (Apache).
> `-p 8080:80` exposes it on host port `8080`; change the host side freely
> (e.g. `-p 8090:80` → `http://<host>:8090`).

---

## GPU rendering

The image already bakes the EGL graphics capability
(`NVIDIA_DRIVER_CAPABILITIES=graphics,utility,compute`), so `--gpus all` is enough
with the [NVIDIA Container Toolkit](https://github.com/NVIDIA/nvidia-container-toolkit).

Useful environment variables:

| Variable | Purpose |
|----------|---------|
| `VTK_EGL_DEVICE_INDEX=<n>` | Select a GPU on multi-GPU hosts (0-indexed among visible devices) |
| `NVIDIA_VISIBLE_DEVICES=<ids>` | Restrict which GPUs the container sees |
| `NVIDIA_DRIVER_CAPABILITIES=all` | Force all driver capabilities (already includes `graphics`) |

Verify the GPU is actually used:
```bash
docker logs <container> | grep -A2 "EGL Status"
# expect "NVIDIA ..."; "llvmpipe" means it fell back to CPU rendering
```

> Running under **podman + CDI** on a cluster (and hitting issues such as a missing
> `/dev/nvidia-modeset`)? See the deployment notes in the GitHub repository.

---

## Sessions

Each browser tab is an **independent, ephemeral** session. Imported data, settings
and view state are **lost when the tab is closed or refreshed** — re-import your data
for each session.

---

## Screenshots

<!-- Host PNGs in the repo under doc/img/ and reference them by RAW URL so they
     render on Docker Hub (relative paths do NOT work here). -->
<!--
![Overview](https://raw.githubusercontent.com/F2I-Consulting/fespp-on-trame/main/doc/img/overview.png)
![3D view](https://raw.githubusercontent.com/F2I-Consulting/fespp-on-trame/main/doc/img/view3d.png)
-->

---

## Build from source

See [github.com/F2I-Consulting/fespp-on-trame](https://github.com/F2I-Consulting/fespp-on-trame)
(`README.md` → Build Instructions) to build the image yourself.
