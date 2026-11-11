"""python cli.py course.imscc [--list] [--modules 1,2,3] [--combined] [--out folder]"""
import argparse
from pathlib import Path

from splitter import Course, split

ap = argparse.ArgumentParser(description="Split a Canvas course export into one .imscc per module")
ap.add_argument("imscc")
ap.add_argument("--list", action="store_true", help="only list the modules")
ap.add_argument("--modules", help="positions from --list, e.g. 2,3,4 (default: all)")
ap.add_argument("--combined", action="store_true", help="one package with all chosen modules")
ap.add_argument("--out", default="modules")
a = ap.parse_args()

if a.list:
    for m in Course(a.imscc).modules:
        print(f"{m.index:3}  {m.label:12}  {m.title}  ({len(m.refs())} items)")
    raise SystemExit
choose = {int(x) for x in a.modules.split(",")} if a.modules else None
out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
for name, data, info in split(a.imscc, choose, a.combined):
    (out / name).write_bytes(data)
    i = info["items"]
    print(f"{name}: {i['pages']} pages, {i['assignments']} assignments, {i['quizzes']} quizzes, "
          f"{i['discussions']} discussions, {info['media']} media files, {info['size']//1024} KB"
          + (f"  ERRORS: {info['errors']}" if info["errors"] else "")
          + (f"  ({len(info['warnings'])} warnings)" if info["warnings"] else ""))
    for w in info["warnings"]:
        print("   -", w)
