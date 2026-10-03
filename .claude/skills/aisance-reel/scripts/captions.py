#!/usr/bin/env python3
"""Karaoke captions (one word at a time) -> transparent PNG strip sequence for compose.py.

Usage:
  python captions.py <transcript.json> <out_dir> --style <name|path> [--fps 30] [--size N] [--y N]
                     [--accent <hex|subject>] [--beats cards/beats.json] [--accent-words W1,W2]

Colours, size, position and font come from the style (captions.*; font: captions.font, else
font.file). Fix transcriber typos in a COPY of the transcript first (edit "text" only, never
the times); card triggers keep using the original. Handles zero-width words, hyphenated
mega-words (split evenly across their window) and long words (font shrinks to fit
captions.max_width).

Motion (captions.pop, default true): each word pops in over ~0.13 s (scale 0.8 -> 1 with a small
overshoot, quick fade), then rests. Accent words (captions.accent_words): the *accent* words of
the card titles in --beats, plus --accent-words, are drawn in the accent colour.

Output: <out_dir>/%05d.png, each a 1080-wide strip, and <out_dir>/meta.json {"y": top, "fps": N}
that compose.py reads to place the strip. <out_dir>/words.json lists every caption word with its
time window and resting box in canvas pixels (the review tool uses it to pick a word in the frame). Frames that repeat the previous one are hard links,
so a 90 s reel writes a few hundred real images, not thousands.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

SKILL_DIR = Path(__file__).resolve().parent.parent
SHARED = SKILL_DIR.parents[2] / "shared"  # fonts live in shared/assets
W = 1080
POP = 0.13  # seconds of entrance per word


def load_style(arg: str) -> dict:
    p = Path(arg)
    if p.suffix != ".json":
        p = SKILL_DIR / "styles" / f"{arg}.json"
    if not p.exists():
        sys.exit(f"style not found: {arg} (looked at {p})")
    return json.loads(p.read_text())


def find_font(style: dict) -> str:
    cands = []
    if os.environ.get("CAPTION_FONT"):
        cands.append(os.environ["CAPTION_FONT"])
    for f in (style.get("captions", {}).get("font"), style.get("font", {}).get("file")):
        if f:
            cands += [f, str(SHARED / f)]
    for c in cands:
        if os.path.exists(c):
            return c
    sys.exit("caption font not found: set captions.font in the style or CAPTION_FONT=/path/to/font.ttf")


GLUE = re.compile(r"^(['’-]\S|\.\d|%$|,\d)")


def glue(words):
    """Rejoin tokens transcribers split off: 5 + .5, qu + 'il, Dis + -moi, 30 + %."""
    out = []
    for w in words:
        t = str(w["text"]).strip()
        if out and GLUE.match(t):
            prev = out[-1]
            prev["text"] = str(prev["text"]).strip() + t
            prev["end"] = w.get("end", prev.get("end"))
        else:
            out.append(dict(w, text=t))
    return out


def key(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s).upper())
    return re.sub(r"[^A-Z0-9.]", "", "".join(ch for ch in s if not unicodedata.combining(ch))).strip(".")


def entries(words, cap):
    ws = glue([w for w in words if w.get("start") is not None])
    ents = []
    for i, w in enumerate(ws):
        a = float(w["start"])
        nxt = float(ws[i + 1]["start"]) if i + 1 < len(ws) else a + 0.4
        b = min(nxt, a + 1.0)
        if b <= a:
            b = a + 0.12
        text = str(w["text"]).strip()
        if cap.get("uppercase", True):
            text = text.upper()
        if cap.get("strip_punct", True):
            text = text.rstrip(",.;:!?")
        if not text:
            continue
        parts = text.split("-") if (len(text) > 14 and text.count("-") >= 2) else [text]
        step = (b - a) / len(parts)
        for k, part in enumerate(parts):
            ents.append((a + k * step, a + (k + 1) * step, part))
    return ents


def accent_set(beats: Path | None, extra: str | None) -> set:
    out = set()
    if beats:
        for b in json.loads(beats.read_text()).get("beats", []):
            for m in re.findall(r"\*([^*]+)\*", str(b.get("text", ""))):
                out |= {key(x) for x in m.split()}
    if extra:
        out |= {key(x) for x in extra.split(",")}
    return {x for x in out if x}


def back_out(k: float, s: float = 1.7) -> float:
    k -= 1
    return k * k * ((s + 1) * k + s) + 1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("transcript", type=Path)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--style", required=True)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--size", type=int, default=None, help="override captions.size")
    ap.add_argument("--y", type=int, default=None, help="override captions.y (canvas pixels from the top)")
    ap.add_argument("--accent", default=None, help="#RRGGBB or a subject from the style's accents table (same as gen.py)")
    ap.add_argument("--beats", type=Path, default=None, help="beats.json: its *accent* title words get the accent colour")
    ap.add_argument("--accent-words", default=None, help="extra comma-separated words drawn in the accent colour")
    a = ap.parse_args()

    st = load_style(a.style)
    cap = st["captions"]
    size = a.size or int(cap.get("size", 66))
    cy = a.y if a.y is not None else int(cap.get("y", 760))
    fill = tuple(cap.get("fill", [255, 255, 255, 255]))
    halo = tuple(cap.get("halo", [0, 0, 0, 180]))
    blur = float(cap.get("blur", 9))
    max_w = int(cap.get("max_width", 1000))
    pop = bool(cap.get("pop", True))
    acc_hex = st["colors"]["accent"]
    if a.accent:
        table = {k.lower(): v for k, v in (st.get("accents") or {}).items()}
        acc_hex = table.get(a.accent.lower(), a.accent)
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", acc_hex):
        sys.exit("--accent must be #RRGGBB or a subject from the style's accents table")
    acc_fill = tuple(int(acc_hex[i:i + 2], 16) for i in (1, 3, 5)) + (255,)
    accents = accent_set(a.beats, a.accent_words) if (cap.get("accent_words") or a.accent_words) else set()
    font_path = find_font(st)

    fonts = {}

    def font(sz):
        if sz not in fonts:
            f = ImageFont.truetype(font_path, sz)
            try:
                f.set_variation_by_axes([int(cap.get("weight", 900))])
            except Exception:
                pass
            fonts[sz] = f
        return fonts[sz]

    ents = entries(json.loads(a.transcript.read_text())["words"], cap)
    if not ents:
        sys.exit("no words to caption")
    a.out_dir.mkdir(parents=True, exist_ok=True)
    for old in a.out_dir.glob("*.png"):
        old.unlink()

    pad = int(blur * 3 + size * 0.35)
    top = max(0, cy - pad)
    SH = int(size * 1.35 + 2 * pad)
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    fitted = {}

    def fit(word):
        if word not in fitted:
            sz = size
            while True:
                bb = measure.textbbox((0, 0), word, font=font(sz))
                if bb[2] - bb[0] <= max_w or sz <= 36:
                    break
                sz -= 4
            fitted[word] = sz
        return fitted[word]

    def draw(word, sz, alpha):
        img = Image.new("RGBA", (W, SH), (0, 0, 0, 0))
        f = font(sz)
        bb = measure.textbbox((0, 0), word, font=f)
        x = (W - (bb[2] - bb[0])) // 2 - bb[0]
        # keep the word's visual centre where the resting word sits while it scales
        bbb = measure.textbbox((0, 0), word, font=font(fit(word)))
        y = round(cy - top + (bbb[1] + bbb[3]) / 2 - (bb[1] + bb[3]) / 2)
        sh = Image.new("RGBA", (W, SH), (0, 0, 0, 0))
        ds = ImageDraw.Draw(sh)
        ha = halo[:3] + (int(halo[3] * alpha),)
        ds.text((x, y + 4), word, font=f, fill=ha)
        ds.text((x, y), word, font=f, fill=ha)
        img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(blur)))
        col = acc_fill if key(word) in accents else fill
        ImageDraw.Draw(img).text((x, y), word, font=f, fill=col[:3] + (int(col[3] * alpha),))
        return img

    total = ents[-1][1] + 0.3
    n = int(total * a.fps)
    prev_key, prev_path, written = None, None, 0
    for i in range(n):
        t = i / a.fps
        cur = next(((s, txt) for s, e, txt in ents if s <= t < e), None)
        if cur is None:
            fkey = ("blank",)
        else:
            s, word = cur
            k = min(1.0, (t - s) / POP) if pop else 1.0
            fkey = (word, s, round(k, 3))
        path = a.out_dir / f"{i:05d}.png"
        if fkey == prev_key and prev_path is not None:
            os.link(prev_path, path)
            continue
        if cur is None:
            Image.new("RGBA", (W, SH), (0, 0, 0, 0)).save(path)
        else:
            scale = 0.8 + 0.2 * back_out(k) if pop else 1.0
            alpha = min(1.0, k * 2.2) if pop else 1.0
            draw(word, max(8, round(fit(word) * scale)), alpha).save(path)
        written += 1
        prev_key, prev_path = fkey, path
    (a.out_dir / "meta.json").write_text(json.dumps({"y": top, "fps": a.fps, "frames": n}))
    boxes = []
    for s, e, word in ents:
        bb = measure.textbbox((0, 0), word, font=font(fit(word)))
        x = (W - (bb[2] - bb[0])) // 2
        boxes.append({"text": word, "start": round(s, 3), "end": round(e, 3), "accent": key(word) in accents,
                      "bbox": [x, cy + bb[1], bb[2] - bb[0], bb[3] - bb[1]]})
    (a.out_dir / "words.json").write_text(json.dumps({"words": boxes}, ensure_ascii=False))
    print(f"{n} caption frames at {a.fps} fps ({written} drawn, {len(ents)} words, {len(accents)} accent words, "
          f"strip y={top} h={SH}, style {st['name']}) -> {a.out_dir}")


if __name__ == "__main__":
    main()
