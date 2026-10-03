#!/usr/bin/env python3
"""Head-popout matting for the popout layout (local rembg model, nothing leaves the machine).

Usage:
  python segment_popout.py <cut.mp4> <seg_dir> --style <name|path> --probe
  python segment_popout.py <cut.mp4> <seg_dir> --style <name|path> --offset N [--limit N]

--probe  samples 4 frames, prints the head-top row of each matte (source pixels, 1080-wide
         scale) and suggests the offset that makes the head pop `popout.pop_target` px above
         the frame line. Put that value in reel.json as offset_speaker.
run      streams the cut through ffmpeg (no frame dump on disk), mattes every frame with
         rembg (cached in seg_dir/mattes/), and writes seg_dir/popout/%05d.png: RGBA strips
         of the source rows [popout_top-offset, frame_top-offset), alpha eroded + blurred.
         ALWAYS run it on the FINAL cut file (the one compose.py uses).
Needs:   ~/.venvs/aisance-reel/bin/pip install rembg onnxruntime   (first run downloads the model)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageFilter

SKILL_DIR = Path(__file__).resolve().parent.parent


def load_style(arg: str) -> dict:
    p = Path(arg)
    if p.suffix != ".json":
        p = SKILL_DIR / "styles" / f"{arg}.json"
    if not p.exists():
        sys.exit(f"style not found: {arg} (looked at {p})")
    return json.loads(p.read_text())


def matte_fn():
    try:
        from rembg import new_session, remove
    except ImportError:
        sys.exit("rembg is not installed:  ~/.venvs/aisance-reel/bin/pip install rembg onnxruntime")
    session = new_session("u2net")

    def f(img: Image.Image) -> Image.Image:
        return remove(img, session=session, only_mask=True).convert("L")
    return f


def frame_at(cut: Path, t: float) -> Image.Image:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "f.png"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", str(cut), "-vf", "scale=1080:-2",
                        "-frames:v", "1", str(p)], check=True)
        im = Image.open(p).convert("RGB")
        im.load()
        return im


def head_top(matte: Image.Image) -> int | None:
    w, h = matte.size
    px = matte.load()
    need = max(1, w // 100)
    for y in range(h):
        if sum(1 for x in range(0, w, 2) if px[x, y] > 128) * 2 >= need:
            return y
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cut", type=Path)
    ap.add_argument("seg_dir", type=Path)
    ap.add_argument("--style", required=True)
    ap.add_argument("--offset", type=int, default=None, help="screen_y = source_y + offset")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--limit", type=int, default=0, help="stop after N frames (testing)")
    a = ap.parse_args()

    st = load_style(a.style)
    if st["layout"] != "popout":
        sys.exit(f"style {st['name']} is not a popout layout")
    po = st["popout"]
    if not a.cut.exists():
        sys.exit(f"cut not found: {a.cut}")
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                str(a.cut)], capture_output=True, text=True).stdout.strip())
    matte = matte_fn()

    if a.probe:
        tops = []
        for frac in (0.1, 0.35, 0.6, 0.85):
            im = frame_at(a.cut, dur * frac)
            y = head_top(matte(im))
            print(f"t={dur * frac:6.2f}s  head-top row: {y}")
            if y is not None:
                tops.append(y)
        if not tops:
            sys.exit("no person found in the sampled frames")
        tops.sort()
        med = tops[len(tops) // 2]
        want = po["frame_top"] - po.get("pop_target", 170)
        off = want - med
        W, H = frame_at(a.cut, dur * 0.5).size
        FH = 1920 - po["frame_top"] - po["bottom_margin"]
        lo = po["frame_top"] + FH - H  # smallest offset that keeps the frame inside the video
        print(f"median head-top {med}px -> suggested offset_speaker = {off}  "
              f"(head lands {po.get('pop_target', 170)}px above the frame line)")
        if off < lo:
            print(f"WARNING: offsets below {lo} crop past the bottom of the video. Use {lo} (the head pops "
                  f"{po['frame_top'] - (med + lo)}px instead) or reframe the clip with the head higher.")
        return

    if a.offset is None:
        sys.exit("--offset is required (run --probe first)")
    off = a.offset
    strip_h = po["frame_top"] - po["popout_top"]
    y0 = po["popout_top"] - off
    y1 = po["frame_top"] - off
    first = frame_at(a.cut, 0.0)
    W, H = first.size
    if y1 <= 0 or y0 >= H:
        sys.exit(f"strip rows {y0}..{y1} fall outside the source (height {H}): check --offset")
    mdir = a.seg_dir / "mattes"
    pdir = a.seg_dir / "popout"
    mdir.mkdir(parents=True, exist_ok=True)
    pdir.mkdir(parents=True, exist_ok=True)

    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(a.cut), "-vf", f"scale=1080:-2,fps={a.fps}",
                             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    n = 0
    frame_bytes = W * H * 3
    while True:
        buf = proc.stdout.read(frame_bytes)
        if len(buf) < frame_bytes:
            break
        img = Image.frombytes("RGB", (W, H), buf)
        mp = mdir / f"{n:05d}.png"
        if mp.exists():
            m = Image.open(mp).convert("L")
        else:
            m = matte(img)
            m.save(mp)
        strip = Image.new("RGBA", (W, strip_h), (0, 0, 0, 0))
        sy0, sy1 = max(0, y0), min(H, y1)
        rgb = img.crop((0, sy0, W, sy1))
        alpha = m.crop((0, sy0, W, sy1)).filter(ImageFilter.MinFilter(int(po.get("matte_erode", 5)) | 1))
        alpha = alpha.filter(ImageFilter.GaussianBlur(float(po.get("matte_blur", 1.2))))
        piece = rgb.convert("RGBA")
        piece.putalpha(alpha)
        strip.paste(piece, (0, sy0 - y0))
        strip.save(pdir / f"{n:05d}.png")
        n += 1
        if n % 25 == 0:
            print(f"  {n} frames ({n / a.fps:.1f}s)", flush=True)
        if a.limit and n >= a.limit:
            proc.kill()
            break
    proc.wait()
    print(f"{n} popout strips ({W}x{strip_h}) -> {pdir}   mattes cached in {mdir}")


if __name__ == "__main__":
    main()
