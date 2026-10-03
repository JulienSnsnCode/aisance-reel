#!/usr/bin/env python3
"""Dual-source alignment: camera video + separate audio recording (e.g. an OBS .mov).

Usage:
  python align_sources.py <camera_transcript.json> <audio_transcript.json>
         [--mux <camera.mp4> <audio.mov> <out_master.mp4>]

Both files were transcribed separately (transcribe.py). Words are matched by text near the
running estimate; the offset = audio_time - camera_time is the median of the inliers.
--mux writes a master with the camera VIDEO and the good AUDIO (video stream copied, so
rotation metadata survives; cutjoin.py rotates on re-encode).
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
from pathlib import Path


def norm(s: str) -> str:
    return re.sub(r"[^\w]", "", s.lower())


def load(p: Path):
    return [w for w in json.loads(p.read_text())["words"] if w.get("start") is not None and norm(w["text"])]


def estimate(cam, aud, window=30.0):
    diffs = []
    est = 0.0
    j0 = 0
    for w in cam:
        t = w["start"]
        target = t + est
        best = None
        for j in range(j0, len(aud)):
            a = aud[j]
            if a["start"] < target - window:
                continue
            if a["start"] > target + window:
                break
            if norm(a["text"]) == norm(w["text"]):
                d = a["start"] - t
                if best is None or abs(d - est) < abs(best - est):
                    best = d
        if best is not None:
            diffs.append(best)
            if len(diffs) >= 5:
                est = statistics.median(diffs[-25:])
    if len(diffs) < 5:
        raise SystemExit(f"only {len(diffs)} matched words: are these the same take?")
    med = statistics.median(diffs)
    inl = [d for d in diffs if abs(d - med) <= 0.25]
    return statistics.median(inl), len(inl), len(diffs)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("camera_transcript", type=Path)
    ap.add_argument("audio_transcript", type=Path)
    ap.add_argument("--mux", nargs=3, metavar=("CAMERA", "AUDIO", "OUT"))
    a = ap.parse_args()

    off, n_in, n_all = estimate(load(a.camera_transcript), load(a.audio_transcript))
    print(f"offset (audio - camera) = {off:.3f}s   inliers {n_in}/{n_all} matched words")
    if a.mux:
        cam, aud, out = a.mux
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", cam]
        if off >= 0:
            cmd += ["-ss", f"{off:.3f}", "-i", aud]
        else:
            cmd += ["-itsoffset", f"{-off:.3f}", "-i", aud]
        cmd += ["-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", out]
        subprocess.run(cmd, check=True)
        print(f"master -> {out}")


if __name__ == "__main__":
    main()
