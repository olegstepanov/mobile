"""Compare baseline and baseline-after 3mf files for identical content."""
import os
import sys
import zipfile

SHAPES = "circle burst star heart shopify cup eclipse octopus smile sun blank".split()

ok = True
for s in SHAPES:
    a = f"baseline/{s}.3mf"
    b = f"baseline-after/{s}.3mf"
    if not os.path.exists(a):
        print(f"SKIP {s}: no baseline")
        continue
    if not os.path.exists(b):
        print(f"FAIL {s}: no after")
        ok = False
        continue
    za = zipfile.ZipFile(a)
    zb = zipfile.ZipFile(b)
    na = sorted(za.namelist())
    nb = sorted(zb.namelist())
    if na != nb:
        print(f"FAIL {s}: different entries {na} vs {nb}")
        ok = False
        continue
    diff = False
    for n in na:
        da, db = za.read(n), zb.read(n)
        if da != db:
            print(f"  DIFF {s}/{n}: size {len(da)} vs {len(db)}")
            diff = True
    status = "FAIL" if diff else "OK"
    print(f"{status} {s}")
    if diff:
        ok = False

sys.exit(0 if ok else 1)
