"""Minimal .xlsx reader, standard library only.

The odds source publishes .xlsx and the project has no third-party
dependencies (load.py shells out to curl rather than take one).  An xlsx is
a zip of XML, and all this needs is the first worksheet as rows of strings,
so a reader is smaller than the argument for adding openpyxl.

Handles the two things that actually bite:
  * shared strings -- most cell text lives in a separate table, and cells
    reference it by index (t="s")
  * sparse rows -- empty cells are omitted entirely, so column position has
    to come from the cell reference (A1, B1, ...) and not from counting
"""

import re
import zipfile
import xml.etree.ElementTree as ET

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_COL = re.compile(r"([A-Z]+)")


def _col_index(ref):
    """'AB12' -> 27 (zero-based column)."""
    m = _COL.match(ref or "")
    if not m:
        return 0
    n = 0
    for ch in m.group(1):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _text(el):
    return "".join(el.itertext()) if el is not None else ""


def read(path, sheet=None):
    """Yield rows of the first (or named) worksheet as lists of strings."""
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            shared = [_text(si) for si in root.findall(f"{NS}si")]

        names = [n for n in z.namelist()
                 if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")]
        names.sort()
        target = names[0]
        if sheet:
            for n in names:
                if sheet in n:
                    target = n
                    break

        root = ET.fromstring(z.read(target))
        for row in root.iter(f"{NS}row"):
            cells = {}
            for c in row.findall(f"{NS}c"):
                i = _col_index(c.get("r"))
                t = c.get("t")
                if t == "s":                       # shared-string index
                    v = c.find(f"{NS}v")
                    val = shared[int(v.text)] if v is not None and v.text else ""
                elif t == "inlineStr":
                    val = _text(c.find(f"{NS}is"))
                else:
                    v = c.find(f"{NS}v")
                    val = v.text if v is not None and v.text else ""
                cells[i] = (val or "").strip()
            if cells:
                width = max(cells) + 1
                yield [cells.get(i, "") for i in range(width)]


def rows_as_dicts(path, sheet=None):
    """First row is the header; yields {column: value}."""
    it = read(path, sheet)
    header = next(it, None)
    if not header:
        return
    for r in it:
        r = r + [""] * (len(header) - len(r))
        yield {h: r[i] for i, h in enumerate(header) if h}


if __name__ == "__main__":
    import sys
    p = sys.argv[1]
    it = read(p)
    head = next(it)
    print(f"{len(head)} columns:")
    print("  " + ", ".join(head))
    for i, r in enumerate(it):
        if i >= 2:
            break
        print(f"  row: {r[:14]}")
