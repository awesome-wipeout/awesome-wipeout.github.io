#!/usr/bin/env python3
"""Scaffold data/marks.toml entries for mark files that don't have one yet.

Every file in marks/ needs exactly one [asset."folder/slug"] entry (1:1). This
scans marks/ and, for any SVG (or PNG-without-SVG) with no entry, prints a
ready-to-fill stub; it also lists entries that have no file. With --write it
appends the stubs to data/marks.toml (you still fill in each `credit`).

Usage:
    python3 tools/scaffold.py            # dry run — print stubs + orphans
    python3 tools/scaffold.py --write    # append stubs to data/marks.toml
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build  # reuse SECTIONS, ASSETS_META, MARKS, DATA, title_case


def _esc(v):
    return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'


def scan_files():
    """(folder, slug, hosted) for every mark file, in section + name order."""
    out = []
    for folder, _ in build.SECTIONS:
        d = os.path.join(build.MARKS, folder)
        if not os.path.isdir(d):
            continue
        names = set(os.listdir(d))
        for fn in sorted(names):
            if fn.endswith(".svg"):
                out.append((folder, fn[:-4], True))
            elif fn.endswith(".png") and (fn[:-4] + ".svg") not in names:
                out.append((folder, fn[:-4], False))
    return out


def _filekey(folder, slug, hosted):
    return f"{folder}/{slug}{'.svg' if hosted else '.png'}"


def stub_for(folder, slug, hosted):
    lines = ["[[asset]]",
             f"file = {_esc(_filekey(folder, slug, hosted))}",
             f"name = {_esc(build.title_case(slug))}   # optional — remove if the auto title is fine",
             'credit = ""   # TODO: contributor id from data/contributors.toml']
    if not hosted:
        lines.append('source = ""   # reference-only: where to get the vector')
    return "\n".join(lines)


def main():
    write = "--write" in sys.argv
    files = scan_files()
    have = set(build.ASSETS_META)                                  # file paths in marks.toml
    present = {_filekey(fo, sl, h) for fo, sl, h in files}         # file paths on disk
    missing = [(fo, sl, h) for fo, sl, h in files if _filekey(fo, sl, h) not in have]
    orphans = sorted(have - present)

    stubs = [stub_for(*m) for m in missing]
    if stubs:
        print(f"# {len(stubs)} mark(s) missing metadata — stubs below:\n")
        print("\n\n".join(stubs))
    else:
        print("# Every mark file has an entry. ✓")
    if orphans:
        print("\n# Entries with no file (remove them, or add the file):")
        for k in orphans:
            print(f"#   {k}")

    if write and stubs:
        with open(os.path.join(build.DATA, "marks.toml"), "a") as f:
            f.write("\n# --- scaffolded stubs (fill in each credit) ---\n"
                    + "\n\n".join(stubs) + "\n")
        print(f"\nAppended {len(stubs)} stub(s) to data/marks.toml — now fill in the credits.")
    elif stubs:
        print("\n# Re-run with --write to append these to data/marks.toml.")


if __name__ == "__main__":
    main()
