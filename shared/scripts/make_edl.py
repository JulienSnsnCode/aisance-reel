#!/usr/bin/env python3
"""Cut 1 (single-take raws only): transcript -> keep-EDL dropping pauses >= --gap.

Usage:
  python make_edl.py <transcript.json> <clip> <out_edl.json> [--gap 0.20] [--exclude 67.5-83.5,90-92]

--exclude drops any segment whose midpoint falls in one of the windows (source seconds).
For MULTI-TAKE raws, hand-write the EDL instead (the clean take of every sentence).
EDL shape: {"sources": {"src": "<clip>"}, "ranges": [{"start": a, "end": b, "quote": "..."}]}
Afterwards ALWAYS run silence_keep.py on the cut.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("transcript", type=Path)
    ap.add_argument("clip", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--gap", type=float, default=0.20, help="pause length that splits a segment")
    ap.add_argument("--exclude", default="", help='windows to drop, e.g. "67.5-83.5,90-92"')
    ap.add_argument("--pad-before", type=float, default=0.03)
    ap.add_argument("--pad-after", type=float, default=0.04)
    a = ap.parse_args()

    excl = []
    for part in filter(None, a.exclude.split(",")):
        lo, hi = part.split("-")
        excl.append((float(lo), float(hi)))

    ws = [w for w in json.loads(a.transcript.read_text())["words"] if w.get("start") is not None]
    if not ws:
        raise SystemExit("empty transcript")
    segs = [[ws[0]]]
    for prev, w in zip(ws, ws[1:]):
        if w["start"] - prev["end"] >= a.gap:
            segs.append([w])
        else:
            segs[-1].append(w)

    ranges = []
    for s in segs:
        start, end = s[0]["start"], s[-1]["end"]
        mid = (start + end) / 2
        if any(lo <= mid <= hi for lo, hi in excl) or end < 0.4:
            continue
        ranges.append({"source": "src",
                       "start": round(max(0.0, start - a.pad_before), 2),
                       "end": round(end + a.pad_after, 2),
                       "quote": " ".join(x["text"] for x in s)[:60]})
    edl = {"version": 1, "sources": {"src": str(a.clip.resolve())}, "ranges": ranges,
           "total_duration_s": round(sum(r["end"] - r["start"] for r in ranges), 2)}
    a.out.write_text(json.dumps(edl, indent=1, ensure_ascii=False))
    print(f"{len(ranges)} segments, {edl['total_duration_s']}s -> {a.out}")


if __name__ == "__main__":
    main()
