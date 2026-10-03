#!/usr/bin/env python3
"""Synthesize the skill's sound-effect bank into assets/sfx/ (no downloads, no licence needed).

Usage:
  python make_sfx.py [--out <skill>/assets/sfx]

Writes 48 kHz mono 16-bit WAVs, peak about -6 dBFS, deterministic (fixed random seed):
  click.wav   25 ms  soft UI click (caption / sentence start, terminal line)
  pop.wav     90 ms  card entrance (pitch sweep down)
  tick.wav    35 ms  list item / step landing
  whoosh.wav 450 ms  screen window in (filtered noise sweep)
  ding.wav   600 ms  payoff / call to action
The files are already shipped with the skill; re-run only to regenerate them.
"""
from __future__ import annotations

import argparse
import math
import random
import struct
import wave
from pathlib import Path

SR = 48000


def write(path: Path, samples, peak=0.5):
    m = max(1e-9, max(abs(x) for x in samples))
    data = b"".join(struct.pack("<h", int(max(-1, min(1, x / m * peak)) * 32767)) for x in samples)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data)


def click(rng):
    n = int(SR * 0.025)
    out, prev = [], 0.0
    for i in range(n):
        t = i / SR
        noise = rng.uniform(-1, 1)
        hp = noise - prev  # crude high-pass: brighter, shorter
        prev = noise
        out.append((0.6 * hp + 0.4 * math.sin(2 * math.pi * 3200 * t)) * math.exp(-t / 0.004))
    return out


def pop():
    n = int(SR * 0.09)
    out, ph = [], 0.0
    for i in range(n):
        t = i / SR
        f = 300 + 600 * math.exp(-t / 0.02)
        ph += 2 * math.pi * f / SR
        out.append(math.sin(ph) * min(1, t / 0.002) * math.exp(-t / 0.025))
    return out


def tick():
    n = int(SR * 0.035)
    return [math.sin(2 * math.pi * 2400 * (i / SR)) * math.exp(-(i / SR) / 0.006) for i in range(n)]


def whoosh(rng):
    n = int(SR * 0.45)
    out, lp = [], 0.0
    for i in range(n):
        u = i / n
        a = 0.02 + 0.25 * math.sin(math.pi * u)  # low-pass opens then closes
        lp += a * (rng.uniform(-1, 1) - lp)
        out.append(lp * math.sin(math.pi * u) ** 1.5)
    return out


def ding():
    n = int(SR * 0.6)
    return [(math.sin(2 * math.pi * 1320 * t) + 0.45 * math.sin(2 * math.pi * 1980 * t) + 0.2 * math.sin(2 * math.pi * 2640 * t))
            * min(1, t / 0.003) * math.exp(-t / 0.18) for t in (i / SR for i in range(n))]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent.parent / "assets" / "sfx")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(7)
    for name, s in (("click", click(rng)), ("pop", pop()), ("tick", tick()), ("whoosh", whoosh(rng)), ("ding", ding())):
        write(a.out / f"{name}.wav", s)
        print(f"{name}.wav  {len(s) / SR * 1000:.0f} ms")
    print(f"-> {a.out}")


if __name__ == "__main__":
    main()
