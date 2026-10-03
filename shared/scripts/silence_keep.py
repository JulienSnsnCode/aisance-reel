#!/usr/bin/env python3
"""Cut 2: detect REAL silences in a cut's audio and write a keep-EDL that removes them.

Usage:
  python silence_keep.py <cut.mp4> <out_edl.json> [--db -40] [--min 0.28]
                         [--pad-after 0.14] [--pad-before 0.07] [--pad-last 0.45]

Defaults validated on the first real reel ("fluid, not choppy"). They are safe only
because word tails are protected upstream by `splice_audit.py edl`.

Word-gap trimming is not enough: transcribers glue silences onto word durations. This uses
ffmpeg silencedetect. Defaults are GENTLE on purpose: -30/-32 dB eats soft word releases
("output" -> "out"). In a noisy room -40 may find nothing; try -35 before anything lower.
The last silence gets a wider pad so the final word is never clipped.
Then: cutjoin.py <out_edl.json> cutF.mp4 ; re-transcribe cutF ; verify no word is clipped.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cut", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--db", type=float, default=-40)
    ap.add_argument("--min", dest="min_sil", type=float, default=0.28)
    ap.add_argument("--pad-after", type=float, default=0.14, help="kept after the voice ends")
    ap.add_argument("--pad-before", type=float, default=0.07, help="kept before the voice resumes")
    ap.add_argument("--pad-last", type=float, default=0.45, help="pad on the final silence (protects the last word)")
    a = ap.parse_args()

    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                str(a.cut)], capture_output=True, text=True).stdout.strip())
    log = subprocess.run(["ffmpeg", "-i", str(a.cut), "-af", f"silencedetect=n={a.db}dB:d={a.min_sil}",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]
    sil = list(zip(starts, ends))

    keep, cur = [], 0.0
    for s0, s1 in sil:
        trailing = s1 >= dur - 0.15
        end = round(min(s0 + (a.pad_last if trailing else a.pad_after), dur), 2)
        if end > cur + 0.15:
            keep.append((round(cur, 2), end))
        cur = round(s1 - a.pad_before, 2)
    if dur > cur + 0.15:
        keep.append((round(cur, 2), round(dur, 2)))

    edl = {"version": 1, "sources": {"src": str(a.cut.resolve())},
           "ranges": [{"source": "src", "start": s, "end": e, "quote": ""} for s, e in keep],
           "total_duration_s": round(sum(e - s for s, e in keep), 2)}
    a.out.write_text(json.dumps(edl, indent=1))
    print(f"silences removed: {len(sil)} | {edl['total_duration_s']}s (was {dur:.1f}s) -> {a.out}")
    if not sil:
        print("  0 silences found: noisy room? retry with --db -35 (never below -32)")


if __name__ == "__main__":
    main()
