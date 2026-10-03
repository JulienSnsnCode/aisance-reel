#!/usr/bin/env python3
"""Audit splice points with the AUDIO, not the transcript (transcribers end words too early).

Usage:
  python splice_audit.py edl <edl.json> [--floor 36] [--max-extend 0.45] [--write fixed_edl.json]
  python splice_audit.py final <cutF.mp4> <transcript.json> [--floor 36]
  python splice_audit.py joins <edl.json> <edl_sil.json> <cutF.mp4> [--language fr] [--all]

edl    For every range of a keep-EDL, reads the RAW source audio around the boundaries.
       END: if the voice is still above the floor at the cut, suggests the first point where
       it stays below the floor for 60 ms (at most --max-extend later, never into the next
       loud onset). START: warns when the range starts on the tail of a previous word and
       suggests a later start. --write saves an EDL with the suggestions applied.
final  For every sentence end in the final cut, checks that the audio falls below the floor
       before the next sentence. A flag on a sentence the transcriber split mid-flow is fine.
joins  Reads every take join of the final cut as TEXT: re-transcribes 3 s around each join
       locally (faster-whisper, nothing uploaded) and prints the words with a ‖ at the cut, so
       you can check the sentence reads as intended ("…dans tous les cas. ‖ Et notamment…").
       --all also lists the joins made by the silence trim (inside a take).
Levels are 20*log10(rms) of 16-bit samples, 20 ms windows: room tone is usually 5-30,
speech 55-75, soft tails 30-45. --floor 36 works for a quiet room.
"""
from __future__ import annotations

import argparse
import array
import json
import math
import subprocess
import sys

FPS = 30  # frame rate the cut is built at (cutjoin --fps); set from --fps


def framed(r) -> float:
    """Length of an EDL piece in the built file: cutjoin rounds every piece up to whole frames."""
    sp = float(r.get("speed", 1) or 1)  # a sped-up wait (long videos) lasts 1/speed of its range
    return math.ceil(round((float(r["end"]) - float(r["start"])) / sp * FPS, 6)) / FPS


def load(path: str, a: float | None = None, d: float | None = None):
    cmd = ["ffmpeg", "-v", "error"]
    if a is not None:
        cmd += ["-ss", f"{max(0.0, a):.3f}"]
    cmd += ["-i", path]
    if d is not None:
        cmd += ["-t", f"{d:.3f}"]
    cmd += ["-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"]
    return array.array("h", subprocess.run(cmd, capture_output=True, check=True).stdout)


def level(s, t0: float, base: float = 0.0, win: float = 0.02) -> float:
    a = int((t0 - base) * 16000)
    seg = s[max(0, a):max(0, a) + int(win * 16000)]
    if not seg:
        return 0.0
    return 20 * math.log10(math.sqrt(sum(x * x for x in seg) / len(seg)) + 1)


def audit_edl(a) -> None:
    edl = json.load(open(a.edl))
    first = next(iter(edl["sources"].values()))
    changed = 0
    for i, r in enumerate(edl["ranges"]):
        if float(r.get("speed", 1) or 1) > 1:
            continue  # a sped-up wait has no voice to protect
        src = edl["sources"].get(r.get("source"), first)  # one EDL can take pieces from several raw files
        e, st = float(r["end"]), float(r["start"])
        s = load(src, e - 0.2, a.max_extend + 0.5)
        base = e - 0.2
        at_cut = level(s, e, base)
        new_e = e
        if at_cut >= a.floor:
            t = e
            while t < e + a.max_extend:
                if level(s, t, base) < a.floor and level(s, t + 0.02, base) < a.floor and level(s, t + 0.04, base) < a.floor:
                    new_e = round(t + 0.04 + a.margin, 2)
                    break
                t += 0.02
            else:
                new_e = None
        s2 = load(src, st - 0.3, 0.5)
        before = max(level(s2, st - k * 0.02, st - 0.3) for k in range(1, 6))
        new_st = st
        if before >= 55:  # a loud word right before the start: we are on its tail
            t = st
            while t < st + 0.3 and level(s2, t, st - 0.3) >= a.floor:
                t += 0.02
            new_st = round(t, 2)
        q = str(r.get("quote", ""))[:32]
        if new_e is None:
            print(f"range {i:2d} END {e:8.2f}  voice at {at_cut:.0f} dB and no fade within {a.max_extend}s (next word glued?) '{q}'")
        elif new_e != e:
            print(f"range {i:2d} END {e:8.2f} -> {new_e:8.2f}  (voice at {at_cut:.0f} dB at the cut) '{q}'")
            r["end"] = new_e
            changed += 1
        if new_st != st:
            print(f"range {i:2d} START {st:8.2f} -> {new_st:8.2f}  (previous word audible, {before:.0f} dB) '{q}'")
            r["start"] = new_st
            changed += 1
    print(f"{changed} boundary change(s) suggested")
    if a.write and changed:
        json.dump(edl, open(a.write, "w"), indent=1, ensure_ascii=False)
        print(f"written -> {a.write}")


def audit_final(a) -> None:
    w = json.load(open(a.transcript))["words"]
    s = load(a.cut)
    flagged = 0
    for i, x in enumerate(w[:-1]):
        if not str(x["text"]).rstrip().endswith((".", "!", "?")):
            continue
        e, n = float(x["end"]), float(w[i + 1]["start"])
        steps = max(2, int((n - e + 0.4) / 0.02))
        quiet = min((level(s, e + k * 0.02) + level(s, e + (k + 1) * 0.02)) / 2 for k in range(steps - 1))
        ok = quiet < a.floor
        flagged += not ok
        print(f"{str(x['text']):>16} -> {str(w[i + 1]['text']):<10} quietest {quiet:4.1f} dB {'OK' if ok else 'CHECK (clipped tail, or a mid-sentence split)'}")
    print(f"{flagged} flagged")


def join_points(edl_path: str, sil_path: str, include_sil: bool):
    """Take joins (and optionally silence-trim joins) as times on the final-cut timeline."""
    edl = json.load(open(edl_path))["ranges"]
    sil = json.load(open(sil_path))["ranges"]
    pts = []
    acc = 0.0
    for r in edl[:-1]:
        acc += framed(r)
        f, run = None, 0.0
        for s in sil:
            a0, b0 = float(s["start"]), float(s["end"])
            if a0 - 1e-6 <= acc <= b0 + 1e-6:
                f = run + (acc - a0) / float(s.get("speed", 1) or 1)
                break
            if acc < a0:  # the take join fell inside a trimmed silence: the join is this range start
                f = run
                break
            run += framed(s)
        if f is not None:
            pts.append((round(f, 2), "take", str(r.get("quote", ""))[:30]))
    if include_sil:
        run = 0.0
        for s in sil[:-1]:
            run += framed(s)
            if all(abs(run - p) > 0.25 for p, *_ in pts):
                pts.append((round(run, 2), "silence", ""))
    return sorted(pts)


def audit_joins(a) -> None:
    import tempfile
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("faster-whisper is needed for the joins audit (local, nothing is uploaded)")
    model = WhisperModel(a.model, device="auto", compute_type="auto")
    for j, kind, quote in join_points(a.edl, a.sil, a.all):
        t0 = max(0.0, j - 1.8)
        with tempfile.TemporaryDirectory() as d:
            wav = f"{d}/j.wav"
            subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t0:.3f}", "-t", "3.2", "-i", a.cut, "-vn", "-ac", "1",
                            "-ar", "16000", wav], check=True)
            segs, _ = model.transcribe(wav, language=a.language, word_timestamps=True, vad_filter=False)
            words = [(t0 + w.start, w.word.strip()) for s in segs for w in s.words]
        before = " ".join(x for t, x in words if t < j)
        after = " ".join(x for t, x in words if t >= j)
        tag = f"after '{quote}'" if kind == "take" else "silence trim"
        print(f"{j:7.2f}s [{tag}]  …{before[-60:]} ‖ {after[:60]}…")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fps", type=int, default=30, help="cutjoin --fps the cut was built with")
    sub = ap.add_subparsers(dest="mode", required=True)
    p1 = sub.add_parser("edl")
    p1.add_argument("edl")
    p1.add_argument("--floor", type=float, default=36)
    p1.add_argument("--max-extend", type=float, default=0.45)
    p1.add_argument("--margin", type=float, default=0.10, help="extra room kept after the fade")
    p1.add_argument("--write", default=None)
    p2 = sub.add_parser("final")
    p2.add_argument("cut")
    p2.add_argument("transcript")
    p2.add_argument("--floor", type=float, default=36)
    p3 = sub.add_parser("joins")
    p3.add_argument("edl")
    p3.add_argument("sil")
    p3.add_argument("cut")
    p3.add_argument("--language", default="fr")
    p3.add_argument("--model", default="large-v3")
    p3.add_argument("--all", action="store_true")
    a = ap.parse_args()
    global FPS
    FPS = a.fps
    {"edl": audit_edl, "final": audit_final, "joins": audit_joins}[a.mode](a)


if __name__ == "__main__":
    sys.exit(main())
