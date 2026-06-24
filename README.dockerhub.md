# FESPP-on-Trame

Web-based viewer for **Energistics / RESQML** data (EPC + HDF5): ParaView with the
**FESPP** plugin, served in your browser through **Kitware Trame**, with NVIDIA
**EGL headless GPU** rendering.

- 📚 **Sources & full documentation:** https://github.com/F2I-Consulting/fespp-on-trame
- 🔌 **FESPP plugin:** https://github.com/F2I-Consulting/fespp

---

## Screenshots

A multi-object geoscience scene — an IJK reservoir grid (sliced) together with a
surface and a wellbore, each coloured by its own property, in a single view:

![FESPP-on-Trame — multi-object 3D scene](https://raw.githubusercontent.com/F2I-Consulting/fespp-on-trame/main/doc/img/Drogon_IJK_Slice_COE_Surface_COE_Wellbore.jpg)

Built-in per-view **descriptive statistics** and **distribution histograms** side by
side with the 3D view:

![FESPP-on-Trame — statistics & distribution](https://raw.githubusercontent.com/F2I-Consulting/fespp-on-trame/main/doc/img/Drogon_IJK_Slice_COE_VIEW_STATS_DIST.jpg)

---

## Quick start

```bash
docker pull f2iconsulting/fesppontrame
```

**CPU (software rendering):**
```bash
docker run -d -p 8080:80 f2iconsulting/fesppontrame
```

**GPU (NVIDIA):**
```bash
docker run -d --gpus all -p 8080:80 f2iconsulting/fesppontrame
```

Then open **http://localhost:8080/index.html**

> **Port mapping:** the container serves on port **80** internally (Apache).
> `-p 8080:80` exposes it on host port `8080`; change the host side freely
> (e.g. `-p 8090:80` → `http://<host>:8090`).

---

## Sessions

Each browser tab is an **independent, ephemeral** session. Imported data, settings
and view state are **lost when the tab is closed or refreshed** — re-import your data
for each session.

---

## Build from source

See [github.com/F2I-Consulting/fespp-on-trame](https://github.com/F2I-Consulting/fespp-on-trame)
(`README.md` → Build Instructions) to build the image yourself.
