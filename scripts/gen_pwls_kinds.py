"""Derive ``fespp_on_trame/assets/pwls40_kinds.json`` from Energistics'
PWLS 4.0 EPC (``eml23_pwls40.epc``: one ``PropertyKind`` part per kind,
each naming its parent and its quantity class).

    python scripts/gen_pwls_kinds.py <path to eml23_pwls40.epc> \
        fespp_on_trame/assets/pwls40_kinds.json

Plain zipfile and regular expressions, with no fesapi and no schema: the
parts are small and regular, and a full XML parse of a few thousand of them
buys nothing here. The output is ``{title: [parent_title | null,
quantity_class]}``, sorted by title, so that a regeneration diffs cleanly.
"""
import json
import re
import sys
import zipfile

_TITLE = re.compile(r"<eml23:Title[^>]*>([^<]*)</eml23:Title>")
_UUID = re.compile(r'uuid="([0-9a-fA-F-]{36})"')
_PARENT = re.compile(r"<eml23:Parent.*?<eml23:Uuid[^>]*>([0-9a-fA-F-]{36})</eml23:Uuid>", re.S)
_QCLASS = re.compile(r"<eml23:QuantityClass[^>]*>([^<]*)<")


def derive(epc_path):
    """Return ``{title: [parent_title or None, quantity_class]}`` for every
    PropertyKind part of the EPC, sorted case-insensitively by title.

    A root kind has None for parent; a kind with no quantity class has "".
    """
    titles, parents, qclass = {}, {}, {}
    with zipfile.ZipFile(epc_path) as z:
        for name in z.namelist():
            if "PropertyKind_" not in name:
                continue
            xml = z.read(name).decode("utf-8", "replace")
            uuid, found = _UUID.search(xml), _TITLE.findall(xml)
            if not uuid or not found:
                continue
            u = uuid.group(1).lower()
            titles[u] = found[0].strip()          # the Citation's Title, before the Parent's
            parent = _PARENT.search(xml)
            p = parent.group(1).lower() if parent else None
            # the root names ITSELF as its parent: a cycle, not an ancestor
            parents[u] = None if p == u else p
            q = _QCLASS.search(xml)
            qclass[u] = q.group(1).strip() if q else ""
    out = {}
    for u, title in titles.items():
        p = parents.get(u)
        out[title] = [titles.get(p) if p else None, qclass.get(u, "")]
    return dict(sorted(out.items(), key=lambda kv: kv[0].lower()))


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    table = derive(src)
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(table, f, ensure_ascii=False, indent=0)
    roots = [t for t, (p, _q) in table.items() if p is None]
    print(f"{len(table)} kinds, {len(roots)} roots: {roots[:8]}")
