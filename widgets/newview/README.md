# trame-fespp-newview

What a second 3D view starts from: **an empty view**, or **a copy of an open
one** — its shown objects and its camera.

## Why it asks

Opening a view used to copy the view you were in, every time and without
asking. That is right when you want the same thing twice side by side, and
wrong when you want a clean view to build something else in — and the reader
had no way to say which. So the gesture asks, once, and the answer is two
words.

A copy takes the eyes and the camera, and **nothing else**: the two cameras
are not synchronized. A copy is a starting point, and a view that dragged its
neighbour along from the first click took that choice away before the user had
made it. Synchronizing is one tick in the view's own *Synchronize camera*
card, and it stays where the user put it.

A **Globe** view is not offered as a source: its camera lives in ECEF world
coordinates, so copying it into a local-CRS view would put the new one on the
other side of the planet.

## Contract

```
props   open        bool                      the dialog is up
        views       [{id, title, globe}]      the render views on offer
        defaultFrom str                       the view to propose (the active one)
events  create(sourceId)   "" = empty, else the view to copy
        close()
```

## Build

```
cd vue-components && npm install && npm run build
# -> trame_fespp_newview/module/serve/{*.umd.js, style.css}
```
