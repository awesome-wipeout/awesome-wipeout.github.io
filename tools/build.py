#!/usr/bin/env python3
"""build.py — orchestrator for the awesome-wipeout site build.

The build logic lives in the awbuild package (core + per-page modules + pdf);
this file just wires them together and runs the pipeline. Run from the repo root:
  DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python3 tools/build.py   (arm64 macOS)
  python3 tools/build.py                                                (Linux)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from awbuild.core import *
from awbuild.pages.marks import build_pages
from awbuild.pages.prose import build_doc_pages
from awbuild.pdf import build_pdf_tearsheet


if __name__ == "__main__":
    force = "--force" in sys.argv or "-f" in sys.argv
    print("Rendering PNG + PDF derivatives…" + ("  (--force: rebuilding all)" if force else ""))
    try:
        n, skipped = render_derivatives(force=force)
        print(f"  {n} rendered, {skipped} up-to-date")
    except Exception as e:
        print(f"  !! skipped (cairosvg unavailable): {e}")
        print("     Keeping existing PNG/PDF derivatives. Font specimens + HTML still build.")
    print("Indexing marks…")
    m = build_manifest()
    print(f"  {m['total']} assets across {len(m['sections'])} sections")
    print("Generating font sample sheets…")
    miss, hints = generate_font_samples()
    if miss:
        print(f"  fonts not found on this machine (no specimen generated): {', '.join(miss)}")
        for fam in miss:
            if fam in hints:
                print(f"      · '{fam}' — closest installed: {', '.join(hints[fam])}")
    else:
        print("  all fonts found")
    print("Indexing fonts…")
    fm = build_font_manifest()
    print(f"  {fm['total']} fonts across {len(fm['sections'])} groups")
    print("Rendering reference thumbnails…")
    try:
        rn, rs = render_reference_thumbs(force=force)
        print(f"  {rn} made, {rs} up-to-date")
    except Exception as e:
        print(f"  !! skipped (Pillow unavailable): {e}")
        print("     Keeping existing thumbnails; grid falls back to full images where absent.")
    print("Indexing in-game reference…")
    rm = build_reference_manifest()
    print(f"  {rm['total']} screenshots across {len(rm['games'])} game(s)")
    print("Writing shared styles.css + analytics.js…")
    write_shared_assets()
    print("Writing pages…")
    build_pages(m, fm, rm)
    print(f"  {len(NAV_PAGES)} pages: " + ", ".join(p["file"] for p in NAV_PAGES))
    print("Rendering doc pages from Markdown…")
    docs = build_doc_pages()
    print(f"  {len(docs)} doc pages: " + ", ".join(docs))
    print("Writing tearsheet.pdf…")
    try:
        n = build_pdf_tearsheet(m)
        print(f"  {n} pages")
    except Exception as e:
        print(f"  !! tearsheet PDF failed: {e}")
    print("Done.")
