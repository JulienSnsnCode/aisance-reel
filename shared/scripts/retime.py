#!/usr/bin/env python3
"""Carry timings from an old cut to a new cut of the SAME speech (e.g. after tightening silences).

Usage:
  python retime.py <old_transcript.json> <new_transcript.json> --files a.json b.json ... [--suffix _retimed]
                   [--windows windows.json --windows-out windows2.json]

Why: re-transcribing a re-cut gives different hallucinations every run, so hand-patched
captions and word-index card anchors would have to be redone. Instead, transcribe the new cut
once, align it to the old raw transcript (shared words become anchors), and warp every time in
the patched files: words keep their corrected text and their indices, only times move.
--files: transcript-shaped JSONs ({"words": [...]}) timed on the OLD cut (the raw old
transcript itself, its caption copy...). Each is written next to itself with --suffix.
--windows: screen windows JSON; start/end are warped (a window at 0 stays at 0).
Prints the number of matched words and the worst anchor error; expect > 90 % and < 0.1 s.
"""
from __future__ import annotations

import argparse
import bisect
import difflib
import json
import re
import sys
from pathlib import Path


def norm(s) -> str:
    return re.sub(r"[^\w]", "", str(s).lower())


def build_warp(old, new):
    sm = difflib.SequenceMatcher(a=[norm(w["text"]) for w in old], b=[norm(w["text"]) for w in new], autojunk=False)
    pairs = set()
    blocks = sm.get_matching_blocks()
    for a, b, n in blocks:
        for k in range(n):
            pairs.add((old[a + k]["start"], new[b + k]["start"]))
            pairs.add((old[a + k]["end"], new[b + k]["end"]))
    chain = []
    for o, n in sorted(pairs):
        if not chain or (o > chain[-1][0] and n >= chain[-1][1]):
            chain.append((o, n))
    if len(chain) < 2:
        sys.exit("too few shared words: are these cuts of the same speech?")
    xs, ys = [o for o, _ in chain], [n for _, n in chain]

    def warp(t: float) -> float:
        i = bisect.bisect_left(xs, t)
        if i <= 0:
            return max(0.0, ys[0] - (xs[0] - t))
        if i >= len(xs):
            return ys[-1] + (t - xs[-1])
        x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
        return y0 + (y1 - y0) * (t - x0) / (x1 - x0) if x1 > x0 else y0

    matched = sum(n for *_, n in blocks)
    err = max((abs(warp(old[a + k]["start"]) - new[b + k]["start"]) for a, b, n in blocks for k in range(n)), default=0)
    return warp, matched, err


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--files", nargs="*", default=[])
    ap.add_argument("--suffix", default="_retimed")
    ap.add_argument("--windows", default=None)
    ap.add_argument("--windows-out", default=None)
    a = ap.parse_args()

    old = json.load(open(a.old))["words"]
    new = json.load(open(a.new))["words"]
    warp, matched, err = build_warp(old, new)
    print(f"matched {matched}/{len(old)} words ({100 * matched / max(1, len(old)):.0f} %), worst anchor error {err:.3f}s")
    for f in a.files:
        d = json.load(open(f))
        for w in d["words"]:
            s = warp(float(w["start"]))
            w["start"], w["end"] = round(s, 3), round(max(warp(float(w["end"])), s + 0.05), 3)
        p = Path(f)
        out = p.with_name(p.stem + a.suffix + p.suffix)
        json.dump(d, open(out, "w"), ensure_ascii=False, indent=1)
        print(f"  {f} -> {out}")
    if a.windows:
        c = json.load(open(a.windows))
        for w in c["windows"]:
            w["start"] = 0.0 if float(w["start"]) == 0 else round(warp(float(w["start"])), 2)
            w["end"] = round(warp(float(w["end"])), 2)
        out = a.windows_out or a.windows
        json.dump(c, open(out, "w"), indent=1)
        print(f"  windows -> {out} {[(w['start'], w['end']) for w in c['windows']]}")
        print("  remember to point windows.json edl_sil at the NEW silence EDL")


if __name__ == "__main__":
    main()
