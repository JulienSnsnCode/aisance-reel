#!/usr/bin/env python3
"""Mix sound-effect cues under a composed reel (video stream untouched).

Usage:
  python sfx_mix.py <cues.json> <in.mp4> <out.mp4> [--dry-run]

cues.json: {"cues": [{"file": "sfx/pop.mp3", "t": 12.34, "vol": 0.3}, ...]}
Compute every "t" from the FINAL transcript's word times (never hard-coded seconds) so a
re-cut re-times the cues automatically. The limiter runs with level=false: its default
auto-level re-boosts the mix to 0 dB and clips. Verify afterwards with volumedetect
(max_volume <= -1 dB).
"""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cues", type=Path)
    ap.add_argument("inp", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    cues = json.loads(a.cues.read_text())["cues"]
    if not cues:
        raise SystemExit("no cues")
    inputs = ["-i", str(a.inp)]
    parts, labels = [], []
    for n, c in enumerate(cues):
        f = Path(c["file"])
        if not f.exists():
            raise SystemExit(f"sfx file not found: {f}")
        inputs += ["-i", str(f)]
        ms = int(round(float(c["t"]) * 1000))
        parts.append(f"[{n + 1}:a]volume={float(c.get('vol', 0.3))},adelay={ms}|{ms}[s{n}]")
        labels.append(f"[s{n}]")
    fc = ";".join(parts) + f";[0:a]{''.join(labels)}amix=inputs={len(cues) + 1}:normalize=0:duration=first," \
                           "alimiter=limit=0.891:level=false[aout]"
    cmd = ["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", fc, "-map", "0:v", "-map", "[aout]",
           "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(a.out)]
    if a.dry_run:
        print(shlex.join(cmd))
        return
    subprocess.run(cmd, check=True)
    print(f"{len(cues)} cues mixed -> {a.out}")


if __name__ == "__main__":
    main()
