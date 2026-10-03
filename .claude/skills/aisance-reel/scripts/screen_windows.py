#!/usr/bin/env python3
"""Screen-share windows with PUNCH-IN zooms (split-screen tutorial reels).

Usage:
  python screen_windows.py <windows.json> <outdir> [--fps 30] [--dry-run]

Maps every FINAL-timeline window back through the edit EDLs to the raw screen recording
(final -> extra_edls -> edl_sil -> edl -> master, then + offset), crops pillarbox bars, and
renders one clip per window: brief full view -> fast cosine punch onto the focus -> hold.
NEVER build a "companion cut" of the screen with the same EDLs and overlay by final time:
per-segment frame rounding accumulates and desyncs late windows.

windows.json (see references/screen-windows.md):
{
  "screen_src": "raw-screen.mov", "offset": 1.585,
  "src_crop": "1664:936:128:40",           # from cropdetect; omit for an exact 16:9 source
  "edl": "edit/edl.json", "edl_sil": "edit/edl_sil.json", "extra_edls": ["edit/edl_fix.json"],
  "windows": [
    {"start": 5.7, "end": 9.5, "hold": 0.5, "punch": 0.35,
     "stages": [{"at": 0.5, "zoom": 1.6, "fx": 0.0, "fy": 0.1}, {"at": 2.7, "zoom": 1.9, "fx": 1.0, "fy": 0.0}]}
  ]
}
Per-window overrides: screen_src, offset, src_crop, src_t (absolute source time: footage from
ANOTHER moment than the narration). Output: <outdir>/w<N>.mp4 (1920x1080 at --fps, no audio). During the hold the
view keeps creeping in (about 1 %/s) so a window is never a frozen frame.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shlex
import subprocess


SNAP = 0.12


FPS = 30  # cutjoin --fps; set from --fps


def load_ranges(p):
    # a built piece lasts its length rounded UP to whole frames (cutjoin), so map with that length
    out = []
    for r in json.load(open(p))["ranges"]:
        a, b = float(r["start"]), float(r["end"])
        out.append((a, a + math.ceil(round((b - a) * FPS, 6)) / FPS))
    return out


def make_mapper(ranges):
    def f(t):
        # strict "<": a time exactly on a splice belongs to the NEXT range (a window that starts
        # on a cut shows the footage after the cut, not the last frame before it)
        # Transcriber word starts are often a few hundredths early, so a window that starts
        # within SNAP seconds of a splice also snaps to the next range.
        acc = 0.0
        for k, (a, b) in enumerate(ranges):
            d = b - a
            end = acc + d
            if t < end - 1e-6 and not (k + 1 < len(ranges) and end - t < SNAP):
                return a + (t - acc)
            if k + 1 < len(ranges) and end - SNAP <= t < end + 1e-6:
                return ranges[k + 1][0]
            acc += d
        return ranges[-1][1]
    return f


def build_chain(cfg):
    chain = []
    for p in cfg.get("extra_edls", [])[::-1]:
        chain.append(make_mapper(load_ranges(p)))
    if cfg.get("edl_sil"):
        chain.append(make_mapper(load_ranges(cfg["edl_sil"])))
    chain.append(make_mapper(load_ranges(cfg["edl"])))

    def to_master(t):
        for m in chain:
            t = m(t)
        return t
    return to_master


def kf_chain(vals, frames, P):
    """Piecewise expression over the output frame counter 'on': cosine ease from vals[k-1] to
    vals[k] starting at frames[k], lasting P frames."""
    expr = f"{vals[-1]}"
    for k in range(len(vals) - 1, 0, -1):
        F = frames[k]
        a, b = vals[k - 1], vals[k]
        ease = f"({a}+({b}-{a})*(0.5-0.5*cos(PI*(on-{F})/{P})))"
        expr = f"if(lt(on,{F}),{vals[k - 1]},if(lt(on,{F + P}),{ease},{expr}))"
    return expr


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("windows_json")
    ap.add_argument("outdir")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    global FPS
    FPS = a.fps

    cfg = json.load(open(a.windows_json))
    os.makedirs(a.outdir, exist_ok=True)
    to_master = build_chain(cfg)

    for n, w in enumerate(cfg["windows"]):
        A, B = float(w["start"]), float(w["end"])
        D = B - A
        src = w.get("screen_src", cfg["screen_src"])
        off = w.get("offset", cfg.get("offset", 0.0))
        src_t = float(w["src_t"]) if "src_t" in w else to_master(A) + off
        crop = w.get("src_crop", cfg.get("src_crop"))
        pre = (f"crop={crop}," if crop else "") + f"scale=1920:1080,fps={FPS}"
        P = max(1, int(float(w.get("punch", 0.35)) * FPS))
        stages = w.get("stages") or [{"at": w.get("hold", 0.5), "zoom": w.get("zoom", 1.5),
                                      "fx": w.get("fx", 0.5), "fy": w.get("fy", 0.4)}]
        zs = [1.001] + [float(s["zoom"]) for s in stages]
        fxs = [float(stages[0]["fx"])] + [float(s["fx"]) for s in stages]
        fys = [float(stages[0]["fy"])] + [float(s["fy"]) for s in stages]
        frames = [0] + [max(1, int(float(s["at"]) * FPS)) for s in stages]
        creep = float(w.get("creep", 0.01))  # slow push during holds
        vf = (f"{pre},zoompan=z='({kf_chain(zs, frames, P)})*(1+{creep}*on/{FPS})':d=1"
              f":x='(iw-iw/zoom)*({kf_chain(fxs, frames, P)})':y='(ih-ih/zoom)*({kf_chain(fys, frames, P)})'"
              f":s=1920x1080:fps={FPS}")
        out = os.path.join(a.outdir, f"w{n}.mp4")
        cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{src_t:.3f}", "-i", src, "-t", f"{D:.3f}", "-an",
               "-vf", vf, "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", out]
        print(f"w{n}: final {A:.2f}-{B:.2f} <- source {src_t:.2f}  stages={stages}")
        if a.dry_run:
            print("   " + shlex.join(cmd))
            continue
        if not os.path.exists(src):
            raise SystemExit(f"screen source not found: {src}")
        subprocess.run(cmd, check=True)
    print(f"{'planned' if a.dry_run else 'rendered'} {len(cfg['windows'])} windows -> {a.outdir}")


if __name__ == "__main__":
    main()
