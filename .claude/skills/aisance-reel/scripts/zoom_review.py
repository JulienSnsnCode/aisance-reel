#!/usr/bin/env python3
"""Zoom REVIEW (mandatory after screen_windows.py): catches "zoomed in on nothing".

Usage:
  python zoom_review.py <windows.json> <screens_dir> [--threshold 1.5]

For every window stage it samples frames of the rendered w<N>.mp4 during the settled hold
and scores visual detail (mean gradient of the central 80 %). Blank dark/white areas score
below ~1.5, readable UI/text above ~3. Flagged stages get a suggested fx/fy from a 12x12
sliding-viewport scan of the SOURCE frame. Suggestions are starting points: pick the
semantically right target (the input WITH text, the banner, the popup), not just the busiest.
Exit code 1 while anything is flagged. Never compose with a flagged stage.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from screen_windows import build_chain  # noqa: E402


def grab(path, t, vf=None):
    fd, tmp = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", path]
    if vf:
        cmd += ["-vf", vf]
    cmd += ["-frames:v", "1", tmp]
    subprocess.run(cmd, check=True)
    im = Image.open(tmp).convert("L")
    im.load()
    os.unlink(tmp)
    return im


def detail(im, box=None):
    if box:
        im = im.crop(box)
    im = im.resize((240, 135))
    px = list(im.get_flattened_data()) if hasattr(im, "get_flattened_data") else list(im.getdata())
    w, h = 240, 135
    tot = n = 0
    for y in range(0, h - 1, 2):
        row = y * w
        for x in range(0, w - 1, 2):
            p = px[row + x]
            tot += abs(p - px[row + x + 1]) + abs(p - px[row + w + x])
            n += 2
    return tot / n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("windows_json")
    ap.add_argument("screens_dir")
    ap.add_argument("--threshold", type=float, default=1.5)
    a = ap.parse_args()

    cfg = json.load(open(a.windows_json))
    to_master = build_chain(cfg)
    flagged = []
    for n, w in enumerate(cfg["windows"]):
        A, B = float(w["start"]), float(w["end"])
        D = B - A
        stages = w.get("stages") or [{"at": w.get("hold", 0.5), "zoom": w.get("zoom", 1.5),
                                      "fx": w.get("fx", 0.5), "fy": w.get("fy", 0.4)}]
        wp = os.path.join(a.screens_dir, f"w{n}.mp4")
        for si, st in enumerate(stages):
            t0 = float(st["at"]) + float(w.get("punch", 0.35)) + 0.15
            t1 = float(stages[si + 1]["at"]) - 0.1 if si + 1 < len(stages) else D - 0.1
            if t1 <= t0:
                t1 = t0 + 0.05
            scores = []
            for frac in (0.15, 0.5, 0.85):
                im = grab(wp, min(t0 + (t1 - t0) * frac, D - 0.05))
                W, H = im.size
                scores.append(detail(im, (int(W * 0.1), int(H * 0.1), int(W * 0.9), int(H * 0.9))))
            sc = sum(scores) / len(scores)
            ok = sc >= a.threshold
            print(f"w{n} stage{si} zoom {st['zoom']} @({st['fx']},{st['fy']}) score={sc:.2f} "
                  f"{'PASS' if ok else 'FLAG <- zooming on nothing?'}")
            if ok:
                continue
            mid = (t0 + t1) / 2
            src_t = (float(w["src_t"]) + mid) if "src_t" in w else to_master(A + mid) + w.get("offset", cfg.get("offset", 0.0))
            crop = w.get("src_crop", cfg.get("src_crop"))
            im = grab(w.get("screen_src", cfg["screen_src"]), src_t, vf=(f"crop={crop}," if crop else "") + "scale=960:540")
            z = float(st["zoom"])
            vw, vh = int(960 / z), int(540 / z)
            best = None
            for gy in range(12):
                for gx in range(12):
                    fx, fy = gx / 11, gy / 11
                    x, y = int((960 - vw) * fx), int((540 - vh) * fy)
                    s = detail(im, (x, y, x + vw, y + vh))
                    if best is None or s > best[0]:
                        best = (s, fx, fy)
            flagged.append((n, si))
            print(f"   suggest fx={best[1]:.2f} fy={best[2]:.2f} (detail {best[0]:.2f}) - verify it is the RIGHT content")
    if flagged:
        print(f"\n{len(flagged)} stage(s) flagged")
        sys.exit(1)
    print("\nall stages PASS")


if __name__ == "__main__":
    main()
