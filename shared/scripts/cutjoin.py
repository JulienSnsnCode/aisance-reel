#!/usr/bin/env python3
"""Cut + join from an EDL with sample-accurate A/V sync.

Usage:
  python cutjoin.py <edl.json> <out.mp4> [--fps 30] [--size 1080x1920] [--crf 19] [--keep-segs]

Each range is re-encoded as its own --size segment (1080x1920 for a reel, 1920x1080 or 2560x1440 for a
long video) at --fps (30, the phone camera rate: no dropped frames) of WHOLE frames (the end is
rounded up to the next frame with real source audio, so no silence is padded at the joins;
piece k starts at the sum of the previous pieces' frame-rounded durations), 12 ms audio micro-fades,
then the segments are joined with the concat FILTER (re-decoded). Never concat-copy AAC:
the encoder priming accumulates and audio drifts from video after ~40 s.
Relative source paths resolve against the EDL's folder. A source whose shape differs from --size is
center-cropped to it (a landscape camera in a reel: pre-crop it around the face first, see SKILL.md).
A range may name its source (`"source": "<key of sources>"`, default the first one), so one EDL can
take pieces from several raw files. A range with `"speed": N` (N > 1) is played N times faster with
silence instead of its audio: a long wait on screen, shown sped up (long videos).
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
from pathlib import Path


def run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("edl", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--size", default="1080x1920", help="output WxH (default 1080x1920, the reel)")
    ap.add_argument("--crf", type=int, default=19)
    ap.add_argument("--keep-segs", action="store_true")
    a = ap.parse_args()

    edl = json.loads(a.edl.read_text())
    if "sources" not in edl or not edl.get("ranges"):
        raise SystemExit('EDL needs {"sources": {...}, "ranges": [...]} (top-level key is "sources", a dict)')
    try:
        W, H = (int(v) for v in a.size.lower().split("x"))
    except ValueError:
        raise SystemExit(f"--size must look like 1920x1080, got {a.size!r}")
    sources = {}
    for key, p in edl["sources"].items():
        sp = Path(p)
        if not sp.is_absolute():
            sp = (a.edl.resolve().parent / sp).resolve()
        if not sp.exists():
            raise SystemExit(f"source not found: {sp}")
        sources[key] = sp
    first = next(iter(sources))

    out = a.out.resolve()
    segdir = out.parent / f"_segs_{out.stem}"
    segdir.mkdir(parents=True, exist_ok=True)
    segs = []
    for i, r in enumerate(edl["ranges"]):
        start, end = float(r["start"]), float(r["end"])
        if end - start <= 0:
            raise SystemExit(f"range {i} has non-positive length")
        key = r.get("source") if r.get("source") in sources else first
        src = sources[key]
        speed = float(r.get("speed", 1) or 1)
        seg = segdir / f"s{i:03d}.mp4"
        fit = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1"
        if speed > 1:
            # sped-up wait: N times faster, silent (the voice is not sped up)
            d = math.ceil(round((end - start) / speed * a.fps, 6)) / a.fps
            run(["ffmpeg", "-y", "-ss", f"{start:.3f}", "-t", f"{d * speed:.3f}", "-i", str(src),
                 "-f", "lavfi", "-t", f"{d:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
                 "-map", "0:v:0", "-map", "1:a:0", "-vf", f"setpts=PTS/{speed:g},{fit}", "-af", f"apad=whole_dur={d:.4f}",
                 "-c:v", "libx264", "-preset", "medium", "-crf", str(a.crf), "-pix_fmt", "yuv420p", "-r", str(a.fps),
                 "-frames:v", str(round(d * a.fps)),
                 "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-video_track_timescale", "12800", str(seg)])
            segs.append(seg)
            continue
        # whole frames of REAL audio: a fractional last frame made ffmpeg pad silence at every join
        d = math.ceil(round((end - start) * a.fps, 6)) / a.fps
        run(["ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", str(src), "-t", f"{d:.3f}",
             "-vf", fit,
             "-af", f"afade=t=in:st=0:d=0.012,afade=t=out:st={max(0.0, d - 0.012):.3f}:d=0.012",
             "-c:v", "libx264", "-preset", "medium", "-crf", str(a.crf), "-pix_fmt", "yuv420p", "-r", str(a.fps),
             # exact frame count: a start between two source frames can otherwise yield one extra frame
             "-frames:v", str(round(d * a.fps)),
             "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-video_track_timescale", "12800", str(seg)])
        segs.append(seg)

    inputs = []
    for s in segs:
        inputs += ["-i", str(s)]
    n = len(segs)
    fc = "".join(f"[{i}:v][{i}:a]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v][a]"
    run(["ffmpeg", "-y", *inputs, "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
         "-c:v", "libx264", "-preset", "medium", "-crf", str(a.crf), "-pix_fmt", "yuv420p", "-r", str(a.fps),
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(out)])
    if not a.keep_segs:
        shutil.rmtree(segdir, ignore_errors=True)

    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=duration",
                            "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.strip()
    aprobe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=duration",
                             "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.strip()
    print(f"OK {out}  video {probe}s / audio {aprobe}s  ({n} segments, concat filter)")


if __name__ == "__main__":
    main()
