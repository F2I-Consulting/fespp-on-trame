"""BlockScope: one composite representation per view (doc/dev/TARGET_ARCHITECTURE.md).

One shared PDC (the FESPP collector), ONE composite representation per view
(`pdc_scene.PdcScene`), and an app "rep" is an assembly-path string resolved
by `assembly_index.AssemblyIndex`. It is the application's only scene model
since 19/10/2026: the per-representation model it replaced, and the
``FESPP_BLOCKSCOPE`` flag that chose between the two, are gone (overhaul,
decision Q2 bis).
"""
