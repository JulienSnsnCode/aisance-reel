#!/usr/bin/env python3
"""Automatic QA gates on a finished reel. Run after compose.py, before showing anything.

Usage:
  python qa_gates.py <reel.json> [--edl edit/edl.json] [--sil edit/edl_sil.json] [--cut-raw edit/cut.mp4]
                     [--transcript <final transcript>] [--max-air 0.30] [--max-still 1.5] [--strict]

Gates (FAIL = exit code 1; WARN only fails with --strict):
  air     FAIL  a quiet run >= --max-air seconds inside the voice (reel.json "cut"), outside the
                first 0.3 s and the final tail. Long gaps read as dead air.
  motion  WARN  the graphics area (above the captions) is frozen longer than --max-still seconds
                (1.5: a title may rest after its entrance; an empty or forgotten card may not).
                Fix by staging a second element, a counter, a sweep, or an earlier entrance.
  frames  FAIL  a blank frame in the render; WARN/FAIL layout: cards or the screen slot reaching
                into the Instagram top zone (style cards.safe_top) or under the captions; the
                caption sequence ending before the last spoken word (--transcript).
  takes   FAIL  a piece of the cut whose audio does not match its source at the EDL position
                (correlation < 0.8): the cut was built from the wrong file or range. Needs --edl
                (raw -> cut.mp4) and/or --sil (cut.mp4 -> final cut).
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

SKILL_DIR = Path(__file__).resolve().parent.parent
FPS = 30  # cutjoin --fps; set from --fps


def framed(r) -> float:
    """Length of an EDL piece in the built file: cutjoin rounds every piece up to whole frames."""
    return math.ceil(round((float(r["end"]) - float(r["start"])) * FPS, 6)) / FPS


def style_of(arg: str) -> dict:
    p = Path(arg)
    if p.suffix != ".json":
        p = SKILL_DIR / "styles" / f"{arg}.json"
    return json.loads(p.read_text())


def duration(path) -> float:
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                                capture_output=True, text=True).stdout.strip())


def audio(path, start=None, dur=None, sr=8000) -> np.ndarray:
    cmd = ["ffmpeg", "-v", "error"]
    if start is not None:
        cmd += ["-ss", f"{max(0.0, start):.3f}"]
    cmd += ["-i", str(path)]
    if dur is not None:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += ["-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"]
    return np.frombuffer(subprocess.run(cmd, capture_output=True, check=True).stdout, dtype=np.int16).astype(np.float32)


def gray_frames(path, fps, y0, y1, w=108):
    h = max(1, round((y1 - y0) * w / 1080))
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf",
                          f"fps={fps},crop=1080:{y1 - y0}:0:{y0},scale={w}:{h},format=gray", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.uint8).reshape(-1, h, w).astype(np.float32)


class Report:
    def __init__(self):
        self.fail = 0
        self.warn = 0

    def __call__(self, level, gate, msg):
        print(f"[{level:4}] {gate:6} {msg}")
        if level == "FAIL":
            self.fail += 1
        elif level == "WARN":
            self.warn += 1


def gate_air(cfg, a, R):
    cut = cfg["cut"]
    d = duration(cut)
    log = subprocess.run(["ffmpeg", "-i", cut, "-af", f"silencedetect=n=-40dB:d={a.max_air}", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    runs = [(float(s), float(e)) for s, e in zip(re.findall(r"silence_start: ([\d.]+)", log), re.findall(r"silence_end: ([\d.]+)", log))]
    bad = [(s, e) for s, e in runs if s > 0.3 and e < d - 0.05]
    for s, e in bad:
        R("FAIL", "air", f"quiet run {e - s:.2f}s at {s:.2f}-{e:.2f}s (max {a.max_air}s): tighten that join")
    if not bad:
        R("OK", "air", f"no quiet run >= {a.max_air}s inside the voice")


def gate_motion(cfg, st, a, R):
    out = cfg["out"]
    y1 = int(st["captions"]["y"]) - 10
    fr = gray_frames(out, 10, 0, y1)
    diff = np.abs(np.diff(fr, axis=0)).mean(axis=(1, 2))
    still = diff < 0.01  # a frozen frame measures exactly 0; typing, zooms and counters stay above
    run, start, found = 0, 0, 0
    for i, s in enumerate(list(still) + [False]):
        if s:
            if run == 0:
                start = i
            run += 1
        else:
            if run / 10 > a.max_still:
                R("WARN", "motion", f"graphics still for {run / 10:.1f}s at {start / 10:.1f}-{(start + run) / 10:.1f}s")
                found += 1
            run = 0
    if not found:
        R("OK", "motion", f"graphics never still longer than {a.max_still}s")


def gate_frames(cfg, st, a, R):
    out = cfg["out"]
    fr = gray_frames(out, 2, 0, 1920)
    blank = [i / 2 for i, f in enumerate(fr) if f.std() < 4]
    for t in blank:
        R("FAIL", "frames", f"blank frame at {t:.1f}s")
    if not blank:
        R("OK", "frames", f"no blank frame ({len(fr)} sampled)")
    cd, cap, scr = st["cards"], st["captions"], st["screen"]
    safe = cd.get("safe_top")
    if not safe:
        R("WARN", "frames", "style has no cards.safe_top: card content can sit under Instagram's top overlay")
    else:
        if scr["y"] < safe:
            R("FAIL", "frames", f"screen slot starts at y={scr['y']}, inside the top safe zone ({safe}px)")
    if scr["y"] + scr["h"] > cap["y"] - 5:
        R("FAIL", "frames", f"screen slot ends at y={scr['y'] + scr['h']}, under the captions (y={cap['y']})")
    if cd["content_h"] - 40 > cap["y"]:
        R("FAIL", "frames", f"cards reach y={cd['content_h'] - 40}, under the captions (y={cap['y']})")
    if a.transcript:
        last = json.load(open(a.transcript))["words"][-1]["end"]
        n = len(list(Path(cfg["captions"]).glob("*.png")))
        meta_p = Path(cfg["captions"]) / "meta.json"
        cfps = json.loads(meta_p.read_text()).get("fps", 30) if meta_p.exists() else cfg.get("captions_fps", 12)
        cover = n / float(cfps)
        if cover < last:
            R("FAIL", "frames", f"captions stop at {cover:.2f}s, last word ends {last:.2f}s")
        else:
            R("OK", "frames", "captions cover the last word")


def ncc(x, y, max_lag):
    """Best normalised correlation over lags: a coarse pass every 4 samples, then every sample
    around the best one (re-encoded pieces sit a fraction of a millisecond off, which a coarse
    step alone reads as a mismatch)."""
    def at(lag):
        if lag >= 0:
            p, q = x[lag:], y[:len(y) - lag] if lag else y
        else:
            p, q = x[:lag], y[-lag:]
        n = min(len(p), len(q))
        if n < 1000:
            return 0.0
        p, q = p[:n] - p[:n].mean(), q[:n] - q[:n].mean()
        den = np.sqrt((p * p).sum() * (q * q).sum())
        return float((p * q).sum() / den) if den > 0 else 0.0
    best, best_lag = max((at(lag), lag) for lag in range(-max_lag, max_lag + 1, 4))
    return max([best] + [at(lag) for lag in range(best_lag - 3, best_lag + 4)])


def check_chain(label, edl_path, built, R):
    edl = json.load(open(edl_path))
    src = next(iter(edl["sources"].values()))
    acc, bad = 0.0, 0
    for i, r in enumerate(edl["ranges"]):
        d = framed(r)
        if d < 0.4:  # too short to judge by correlation
            acc += d
            continue
        probe = min(0.8, d - 0.1)
        x = audio(built, acc + 0.05, probe)
        y = audio(src, float(r["start"]) + 0.05, probe)
        if np.abs(y).max() < 300:  # silent piece: nothing to compare
            acc += d
            continue
        c = ncc(x, y, max_lag=640)  # +-80 ms at 8 kHz
        if c < 0.8:
            R("FAIL", "takes", f"{label} piece {i} ({r.get('quote', '')[:30]!r}) matches its source at only {c:.2f}")
            bad += 1
        acc += d
    if not bad:
        R("OK", "takes", f"{label}: every piece matches its source")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config")
    ap.add_argument("--edl", default=None)
    ap.add_argument("--sil", default=None)
    ap.add_argument("--cut-raw", default="edit/cut.mp4", help="the cut built from --edl (input of --sil)")
    ap.add_argument("--transcript", default=None)
    ap.add_argument("--max-air", type=float, default=0.30)
    ap.add_argument("--max-still", type=float, default=1.5)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--fps", type=int, default=30, help="cutjoin --fps the cut was built with")
    a = ap.parse_args()
    global FPS
    FPS = a.fps

    cfg = json.loads(Path(a.config).read_text())
    st = style_of(cfg["style"])
    R = Report()
    gate_air(cfg, a, R)
    gate_motion(cfg, st, a, R)
    gate_frames(cfg, st, a, R)
    if a.edl:
        check_chain("edl", a.edl, a.cut_raw, R)
    if a.sil:
        check_chain("silence", a.sil, cfg["cut"], R)
    print(f"\n{R.fail} fail, {R.warn} warn")
    sys.exit(1 if R.fail or (a.strict and R.warn) else 0)


if __name__ == "__main__":
    main()
