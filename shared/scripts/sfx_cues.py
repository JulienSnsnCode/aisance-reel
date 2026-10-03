#!/usr/bin/env python3
"""Build cues.json for sfx_mix.py automatically from the reel's own timings.

Usage:
  python sfx_cues.py --hits cards/hits.json --captions <cutF_cap.json> [--cta-word commentaire]
                     [--every-card] [--no-sentence] [--gain 1.0] [--out edit/cues.json]

Cues (skill bank in assets/sfx, volumes are linear gains under a voice at -16 LUFS):
  change of subject      whoosh 0.16     only beats marked "topic": true in beats.json
  list item / step       tick   0.16     terminal line             click  0.14
  sentence start (caption click, first word after . ! ?)           click  0.10
  CTA keyword            ding   0.20     button click (subscribe) click  0.16
--no-sentence drops the sentence clicks (long videos: one every few seconds for 15 minutes is too much).
A transition sound on every card or window is too much: it plays on real subject changes
only. --every-card brings back the old pop on every card, title landing and window.
Cues closer than 0.12 s to a louder one are dropped, so a beat never gets a pile-up.
--gain scales everything (0.7 = quieter mix). Times come from gen.py's hits.json and the
caption transcript, so a re-cut re-times the sound automatically.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

BANK = Path(__file__).resolve().parent.parent / "assets" / "sfx"
SPEC = {"topic": ("whoosh", 0.16), "card": ("pop", 0.22), "title": ("pop", 0.16), "item": ("tick", 0.16),
        "type": ("click", 0.14), "sentence": ("click", 0.10), "window": ("whoosh", 0.12), "cta": ("ding", 0.20),
        "click": ("click", 0.16)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hits", required=True)
    ap.add_argument("--captions", required=True)
    ap.add_argument("--windows", default=None, help="with --every-card: a whoosh at each screen window")
    ap.add_argument("--every-card", action="store_true", help="old behaviour: a pop on every card and title, whoosh on windows")
    ap.add_argument("--cta-word", default=None, help="caption word that gets the ding (e.g. commentaire)")
    ap.add_argument("--no-whoosh", action="store_true")
    ap.add_argument("--no-sentence", action="store_true", help="no click on sentence starts (long videos)")
    ap.add_argument("--gain", type=float, default=1.0)
    ap.add_argument("--out", default="edit/cues.json")
    a = ap.parse_args()

    raw = []
    for h in json.load(open(a.hits))["hits"]:
        k = h["kind"]
        if k not in SPEC:
            continue
        if k in ("card", "title") and not a.every_card:
            continue
        if k == "topic":
            raw.append((max(0.0, float(h["t"]) - 0.08), k))  # the swoosh peaks as the new card lands
        else:
            raw.append((float(h["t"]), k))
    tops = sorted(t0 for t0, k in raw if k == "topic")
    for x, y in zip(tops, tops[1:]):
        if y - x < 6.0:
            print(f"warning: subject changes at {x:.1f}s and {y:.1f}s are {y - x:.1f}s apart. Keep \"topic\" for real "
                  "changes of subject (about one every 10 to 15 s), or the transition sound gets repetitive.")
    if not a.every_card and not any(k == "topic" for _, k in raw):
        print('note: no beat has "topic": true, so no transition sound. Mark the subject changes in beats.json.')
    words = [w for w in json.load(open(a.captions))["words"] if str(w.get("text", "")).strip()]
    for i, w in enumerate(words):
        if not a.no_sentence and (i == 0 or str(words[i - 1]["text"]).rstrip().endswith((".", "!", "?"))):
            raw.append((float(w["start"]), "sentence"))
        if a.cta_word and re.sub(r"[^\w]", "", str(w["text"]).lower()) == a.cta_word.lower():
            raw.append((float(w["start"]), "cta"))
    if a.windows and a.every_card and not a.no_whoosh:
        for win in json.load(open(a.windows))["windows"]:
            raw.append((max(0.0, float(win["start"]) - 0.08), "window"))

    for name in {SPEC[k][0] for _, k in raw}:
        if not (BANK / f"{name}.wav").exists():
            raise SystemExit(f"missing {BANK / name}.wav: run make_sfx.py")
    kept = []
    for t, k in sorted(raw, key=lambda x: (-SPEC[x[1]][1], x[0])):  # louder cues win the slot
        if all(abs(t - kt) >= 0.12 for kt, _ in kept):
            kept.append((t, k))
    kept.sort()
    cues = [{"file": str(BANK / f"{SPEC[k][0]}.wav"), "t": round(t, 3), "vol": round(SPEC[k][1] * a.gain, 3), "kind": k}
            for t, k in kept]
    Path(a.out).write_text(json.dumps({"cues": cues}, indent=1))
    counts = {}
    for c in cues:
        counts[c["kind"]] = counts.get(c["kind"], 0) + 1
    print(f"{len(cues)} cues -> {a.out}  {counts}")


if __name__ == "__main__":
    main()
