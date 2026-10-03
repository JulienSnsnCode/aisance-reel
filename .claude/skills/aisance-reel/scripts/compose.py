#!/usr/bin/env python3
"""Final composite from a project config (reel.json). One script for both layouts.

Usage:
  python compose.py <reel.json> [--dry-run]

reel.json keys (see examples/reel.example.json):
  style            "aisance-dark-band" | "aisance-light-popout" | "aisance-band" | "aisance-popout" | path to a style JSON
  accent           optional #RRGGBB or subject (claude, n8n...) from the style's accents table; use the
                   same value as gen.py --accent so frame shadows match the cards
  cut, cards       final cut (voice) and the rendered cards video (hyperframes)
  captions         PNG folder from captions.py (its meta.json gives the strip y and fps)
  fps              output frame rate (30: the phone camera's own rate, no dropped frames)
  out              output mp4
  music            path or null (no bundled track; use a licensed one)   music_vol  overrides style
  duck             true (default): the music dips under the voice (sidechain); false = flat level
  crop_y           band layout: source crop y so the face sits high in the lower band
  cut_edl          band layout: the EDL that built "cut" (e.g. edit/edl_sil.json). Enables punch-ins:
  punch            {"zoom": 1.1, "min_gap": 2.0}: the face alternates between normal and zoomed at the
                   joins of cut_edl (at most one switch per min_gap s), which hides jump cuts. false = off
  offset_speaker   popout layout: screen_y = source_y + offset (from segment_popout.py --probe)
  seg_dir          popout layout: masks/shadows (generated here) + popout/%05d.png strips
  windows          optional windows.json + screens_dir (clips from screen_windows.py)
  broll            optional [{file, start, end, src_start}] shown in the screen slot (popout) or full-bleed band
  title_png, title_window   optional hook title overlay [start, end]

Layers, band:   bg -> face crop (punch-ins) -> seam gradient -> cards top band -> screens/b-roll -> captions -> title
Layers, popout: cards full-frame -> screens/b-roll (rounded + shadow) -> frame shadow -> rounded face
                -> head popout strips -> captions -> title
Audio: voice loudnorm I=-16, optional music low with fades, +faststart. Paths go to ffmpeg as
arguments only (never into the filter graph); the graph is written to <seg_dir>/filter.txt.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shlex
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SKILL_DIR = Path(__file__).resolve().parent.parent


def load_style(arg: str) -> dict:
    p = Path(arg)
    if p.suffix != ".json":
        p = SKILL_DIR / "styles" / f"{arg}.json"
    if not p.exists():
        sys.exit(f"style not found: {arg} (looked at {p})")
    return json.loads(p.read_text())


def hex_ff(h: str) -> str:
    return "0x" + h.lstrip("#")


def hex_rgb(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rounded_mask(w, h, r, path: Path):
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w - 1, h - 1), radius=r, fill=255)
    m.save(path)


def shadow_png(geo: dict, x, y, w, h, accent: str, path: Path):
    """Solid offset shadow in the accent (offset_shadow > 0) or a soft black drop shadow."""
    im = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    r = geo.get("radius", 20)
    o = int(geo.get("offset_shadow", 0))
    if o > 0:
        ImageDraw.Draw(im).rounded_rectangle((x + o, y + o, x + w - 1 + o, y + h - 1 + o), radius=r, fill=(*hex_rgb(accent), 255))
    elif geo.get("shadow_alpha", 0) > 0:
        dy = geo.get("shadow_dy", 0)
        ImageDraw.Draw(im).rounded_rectangle((x, y + dy, x + w - 1, y + h - 1 + dy), radius=r, fill=(0, 0, 0, int(geo["shadow_alpha"])))
        if geo.get("shadow_blur", 0) > 0:
            im = im.filter(ImageFilter.GaussianBlur(geo["shadow_blur"]))
    im.save(path)
    return o > 0 or geo.get("shadow_alpha", 0) > 0


def border_png(geo: dict, x, y, w, h, path: Path):
    bw = int(geo.get("border_w", 0))
    if bw <= 0:
        return False
    im = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle((x, y, x + w - 1, y + h - 1), radius=geo.get("radius", 20),
                                         outline=(*hex_rgb(geo.get("border_color", "#FFFFFF")), 255), width=bw)
    im.save(path)
    return True


def seam_png(h, color, path: Path):
    """Background colour fading to transparent (smoothstep), laid over the top of the face."""
    im = Image.new("RGBA", (1080, h), (0, 0, 0, 0))
    r, g, b = hex_rgb(color)
    d = ImageDraw.Draw(im)
    for y in range(h):
        k = 1 - y / max(1, h - 1)
        d.line([(0, y), (1079, y)], fill=(r, g, b, int(255 * k * k * (3 - 2 * k))))
    im.save(path)


def punch_windows(cut_edl: Path, fps: int, min_gap: float, total: float):
    """[(start, end)] of the zoomed spans: the level switches at a join of the cut, never more than
    once per min_gap seconds. Join positions follow cutjoin (every piece rounded up to whole frames)."""
    ranges = json.loads(Path(cut_edl).read_text())["ranges"]
    joins, acc = [], 0.0
    for r in ranges[:-1]:
        acc += math.ceil(round((float(r["end"]) - float(r["start"])) * fps, 6)) / fps
        joins.append(round(acc, 3))
    switches, last = [], 0.0
    for j in joins:
        if j - last >= min_gap:
            switches.append(j)
            last = j
    edges = [0.0] + switches + [total + 1]
    return [(edges[k], edges[k + 1]) for k in range(1, len(edges) - 1, 2)]


def duration(path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config", type=Path)
    ap.add_argument("--dry-run", action="store_true", help="write masks + filter graph, print the commands, run nothing")
    a = ap.parse_args()

    cfg = json.loads(a.config.read_text())
    st = load_style(cfg["style"])
    fps = int(cfg.get("fps", 30))
    layout = st["layout"]
    c = st["colors"]
    if cfg.get("accent"):
        table = {k.lower(): v for k, v in (st.get("accents") or {}).items()}
        acc = table.get(str(cfg["accent"]).lower(), cfg["accent"])
        if not (isinstance(acc, str) and len(acc) == 7 and acc.startswith("#")):
            sys.exit(f"accent must be #RRGGBB or one of {sorted(table)}")
        c["accent"] = acc
    seg = Path(cfg.get("seg_dir", "seg"))
    seg.mkdir(parents=True, exist_ok=True)
    out = Path(cfg["out"])
    out.parent.mkdir(parents=True, exist_ok=True)
    for key in ("cut", "cards", "captions"):
        if not Path(cfg[key]).exists() and not a.dry_run:
            sys.exit(f"{key} not found: {cfg[key]}")

    inputs: list[str] = []

    def add(args) -> int:
        idx = sum(1 for x in inputs if x == "-i")
        inputs.extend(args)
        return idx

    i_cut = add(["-i", cfg["cut"]])
    i_cards = add(["-i", cfg["cards"]])
    fc: list[str] = []

    # screen-slot overlays: screen windows + b-roll
    scr = st["screen"]
    overlays = []
    if cfg.get("windows"):
        win = json.loads(Path(cfg["windows"]).read_text())["windows"]
        sdir = Path(cfg.get("screens_dir", seg / "screens"))
        for n, w in enumerate(win):
            overlays.append({"file": str(sdir / f"w{n}.mp4"), "start": float(w["start"]), "end": float(w["end"]),
                             "src_start": 0.0, "slot": "screen"})
    for b in cfg.get("broll", []) or []:
        overlays.append({"file": b["file"], "start": float(b["start"]), "end": float(b["end"]),
                         "src_start": float(b.get("src_start", 0.0)),
                         "slot": "band" if (layout == "band" and b.get("fit", "fill") == "fill") else "screen"})
    n_screen = sum(1 for o in overlays if o["slot"] == "screen")
    use_shadow = use_border = False
    if n_screen:
        rounded_mask(scr["w"], scr["h"], scr["radius"], seg / "screen_mask.png")
        use_shadow = shadow_png(scr, scr["x"], scr["y"], scr["w"], scr["h"], c["accent"], seg / "screen_shadow.png")
        use_border = border_png(scr, scr["x"], scr["y"], scr["w"], scr["h"], seg / "screen_border.png")
        i_smask = add(["-loop", "1", "-i", str(seg / "screen_mask.png")])
        fc.append(f"[{i_smask}:v]format=gray,split={n_screen}" + "".join(f"[smk{k}]" for k in range(n_screen)))
        if use_shadow:
            i_sshadow = add(["-loop", "1", "-i", str(seg / "screen_shadow.png")])
            fc.append(f"[{i_sshadow}:v]split={n_screen}" + "".join(f"[shd{k}]" for k in range(n_screen)))
        if use_border:
            i_sborder = add(["-loop", "1", "-i", str(seg / "screen_border.png")])
            fc.append(f"[{i_sborder}:v]split={n_screen}" + "".join(f"[sbd{k}]" for k in range(n_screen)))

    # base layer
    if layout == "band":
        band = st["band"]
        band_h = st["cards"]["band_h"]
        crop_y = int(cfg.get("crop_y", band.get("crop_y_default", 200)))
        fh = band["face_h"]
        fc.append(f"color=c={hex_ff(c['bg'])}:s=1080x1920:r={fps}[bgc]")
        punch = cfg.get("punch", {"zoom": 1.1, "min_gap": 2.0} if cfg.get("cut_edl") else False)
        spans = []
        if punch and cfg.get("cut_edl"):
            spans = punch_windows(Path(cfg["cut_edl"]), fps, float(punch.get("min_gap", 2.0)),
                                  duration(cfg["cut"]) if not a.dry_run else 600.0)
        if spans:
            z = float(punch.get("zoom", 1.1))
            zw = int(round(1080 * z / 2) * 2)
            cyz = (crop_y + fh / 2) * z  # zoom around the centre of the visible face window
            zy = int(max(0, min(cyz - fh / 2, 1920 * z - fh)))
            zx = (zw - 1080) // 2
            en = "+".join(f"between(t,{s0:.3f},{s1 - 0.001:.3f})" for s0, s1 in spans)
            fc.append(f"[{i_cut}:v]scale=1080:-2,fps={fps},split=2[f0][f1]")
            fc.append(f"[f0]crop=1080:{fh}:0:{crop_y}[fn]")
            fc.append(f"[f1]scale={zw}:-2,crop=1080:{fh}:{zx}:{zy}[fz]")
            fc.append(f"[fn][fz]overlay=0:0:enable='{en}'[face]")
            print(f"punch-ins: {len(spans)} zoomed spans at x{z}")
        else:
            fc.append(f"[{i_cut}:v]scale=1080:-2,fps={fps},crop=1080:{fh}:0:{crop_y}[face]")
        fc.append(f"[bgc][face]overlay=0:{band['face_y']}:shortest=1[stage]")
        if band.get("seam"):
            seam_png(int(band["seam"]), c["bg"], seg / "seam.png")
            i_seam = add(["-loop", "1", "-i", str(seg / "seam.png")])
            fc.append(f"[stage][{i_seam}:v]overlay=0:{band['face_y']}:shortest=1[stagef]")
            stage = "[stagef]"
        else:
            stage = "[stage]"
        fc.append(f"[{i_cards}:v]crop=1080:{band_h}:0:0[ctop]")
        fc.append(f"{stage}[ctop]overlay=0:0[base]")
    else:
        band_h = st["cards"]["band_h"]
        fc.append(f"[{i_cards}:v]fps={fps}[base]")
    cur = "[base]"

    # overlays in time order
    k_screen = 0
    for n, o in enumerate(sorted(overlays, key=lambda o: o["start"])):
        A, B = o["start"], o["end"]
        D = B - A
        idx = add(["-i", o["file"]])
        if o["slot"] == "band":
            fc.append(f"[{idx}:v]trim=start={o['src_start']}:duration={D:.3f},setpts=PTS-STARTPTS,fps={fps},"
                      f"scale=-2:{band_h},crop=1080:{band_h},setsar=1,setpts=PTS+{A:.3f}/TB[ov{n}]")
            fc.append(f"{cur}[ov{n}]overlay=0:0:enable='between(t,{A:.3f},{B:.3f})'[o{n}]")
        else:
            fc.append(f"[{idx}:v]trim=start={o['src_start']}:duration={D:.3f},setpts=PTS-STARTPTS,fps={fps},"
                      f"scale={scr['w']}:{scr['h']}:force_original_aspect_ratio=increase,crop={scr['w']}:{scr['h']},setsar=1[sc{n}]")
            # the window rises 36 px into place while it fades in, and fades out at its end; shadow
            # and border move with it. Back-to-back windows (no gap) cut straight, no fade.
            F = min(0.28, D / 3)
            prev_end = max((p["end"] for p in overlays if p["slot"] == "screen" and p["end"] <= A + 1e-3 and p is not o), default=-9)
            next_start = min((p["start"] for p in overlays if p["slot"] == "screen" and p["start"] >= B - 1e-3 and p is not o), default=9e9)
            fin = f",fade=t=in:st={A:.3f}:d={F:.3f}:alpha=1" if A - prev_end > 0.05 and A > 0.05 else ""
            fout = f",fade=t=out:st={B - F:.3f}:d={F:.3f}:alpha=1" if next_start - B > 0.05 else ""
            dy = f"36*pow(max(0,1-(t-{A:.3f})/{F + 0.12:.3f}),3)" if fin else "0"
            fc.append(f"[sc{n}][smk{k_screen}]alphamerge,setpts=PTS+{A:.3f}/TB,format=yuva420p{fin}{fout}[sca{n}]")
            if use_shadow:
                fc.append(f"[shd{k_screen}]format=rgba{fin}{fout}[shf{n}]")
                fc.append(f"{cur}[shf{n}]overlay=0:'{dy}':enable='between(t,{A:.3f},{B:.3f})'[os{n}]")
                cur = f"[os{n}]"
            fc.append(f"{cur}[sca{n}]overlay={scr['x']}:'{scr['y']}+{dy}':enable='between(t,{A:.3f},{B:.3f})'[ob{n}]")
            cur = f"[ob{n}]"
            if use_border:
                fc.append(f"[sbd{k_screen}]format=rgba{fin}{fout}[sbf{n}]")
                fc.append(f"{cur}[sbf{n}]overlay=0:'{dy}':enable='between(t,{A:.3f},{B:.3f})'[ow{n}]")
                cur = f"[ow{n}]"
            fc.append(f"{cur}null[o{n}]")
            k_screen += 1
        cur = f"[o{n}]"

    # speaker frame + popout (popout layout only)
    if layout == "popout":
        po = st["popout"]
        FH = 1920 - po["frame_top"] - po["bottom_margin"]
        off = int(cfg.get("offset_speaker", po.get("offset_default", 0)))
        fy0 = po["frame_top"] - off
        if fy0 < 0:
            sys.exit(f"offset_speaker {off} is larger than frame_top {po['frame_top']}: the frame would start above the source")
        if not a.dry_run:
            src_h = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                                    "-of", "csv=p=0", cfg["cut"]], capture_output=True, text=True).stdout.strip().split(",")
            h1080 = round(int(src_h[1]) * 1080 / int(src_h[0]))
            if fy0 + FH > h1080:
                sys.exit(f"offset_speaker {off} makes the frame read source rows {fy0}-{fy0 + FH}, past the video bottom ({h1080}). "
                         f"Raise offset_speaker to at least {fy0 + FH - h1080 + off}, or reframe the clip so the head sits higher.")
        rounded_mask(po["frame_w"], FH, po["radius"], seg / "frame_mask.png")
        shadow_png(po, po["frame_x"], po["frame_top"], po["frame_w"], FH, c["accent"], seg / "frame_shadow.png")
        has_fborder = border_png(po, po["frame_x"], po["frame_top"], po["frame_w"], FH, seg / "frame_border.png")
        i_fsh = add(["-loop", "1", "-i", str(seg / "frame_shadow.png")])
        i_fmk = add(["-loop", "1", "-i", str(seg / "frame_mask.png")])
        fc.append(f"{cur}[{i_fsh}:v]overlay=0:0:shortest=1[fs]")
        fc.append(f"[{i_cut}:v]scale=1080:-2,crop={po['frame_w']}:{FH}:{po['frame_x']}:{fy0}[vf]")
        fc.append(f"[{i_fmk}:v]format=gray[mk]")
        fc.append("[vf][mk]alphamerge[vfa]")
        fc.append(f"[fs][vfa]overlay={po['frame_x']}:{po['frame_top']}[sp]")
        cur = "[sp]"
        if has_fborder:  # border under the popout strips, so the head crosses the frame line
            i_fb = add(["-loop", "1", "-i", str(seg / "frame_border.png")])
            fc.append(f"{cur}[{i_fb}:v]overlay=0:0[spb]")
            cur = "[spb]"
        popout_dir = seg / "popout"
        if popout_dir.exists() and any(popout_dir.glob("*.png")):
            i_pop = add(["-framerate", str(fps), "-i", str(popout_dir / "%05d.png")])
            fc.append(f"{cur}[{i_pop}:v]overlay=0:{po['popout_top']}[pp]")
            cur = "[pp]"
        else:
            print("note: no popout strips in seg/popout -> composing the frame without the head cutout")

    # captions + optional title
    meta_p = Path(cfg["captions"]) / "meta.json"
    meta = json.loads(meta_p.read_text()) if meta_p.exists() else {"y": 0, "fps": cfg.get("captions_fps", 12)}
    i_cap = add(["-framerate", str(int(meta.get("fps", 30))), "-i", str(Path(cfg["captions"]) / "%05d.png")])
    fc.append(f"[{i_cap}:v]fps={fps}[capf]")
    fc.append(f"{cur}[capf]overlay=0:{int(meta.get('y', 0))}:eof_action=pass[cap]")
    cur = "[cap]"
    if cfg.get("title_png"):
        i_t = add(["-loop", "1", "-i", cfg["title_png"]])
        tw = cfg.get("title_window")
        en = f":enable='between(t,{float(tw[0]):.3f},{float(tw[1]):.3f})'" if tw else ""
        fc.append(f"{cur}[{i_t}:v]overlay=0:0:shortest=1{en}[final]")
    else:
        fc.append(f"{cur}null[final]")

    script = seg / "filter.txt"
    script.write_text(";\n".join(fc) + "\n")
    tmp = str(out) + ".noaudio.mp4"
    cmd_v = ["ffmpeg", "-y", "-v", "error", *inputs, "-/filter_complex", str(script),
             "-map", "[final]", "-map", f"{i_cut}:a", "-c:v", "libx264", "-preset", "medium", "-crf", "21",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-shortest", tmp]

    # audio pass
    music = cfg.get("music")
    mvol = cfg.get("music_vol", st.get("music", {}).get("vol", 0.06))
    mstart = st.get("music", {}).get("start", 4.0)
    dur = duration(cfg["cut"]) if not a.dry_run else 60.0
    fout = max(0.0, dur - 2)
    duck = cfg.get("duck", st.get("music", {}).get("duck", True))
    if music and duck:
        # the voice drives a compressor on the music: it dips under speech and comes back in the gaps
        af = (f"[0:a]loudnorm=I=-16:TP=-1.5:LRA=11,asplit=2[vo][sc];"
              f"[1:a]atrim=start={mstart},asetpts=PTS-STARTPTS,volume={mvol},"
              f"afade=in:st=0:d=0.5,afade=out:st={fout:.2f}:d=2[m0];"
              f"[m0][sc]sidechaincompress=threshold=0.03:ratio=4:attack=20:release=350:makeup=1[m];"
              f"[vo][m]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.84:level=false[a]")
    elif music:
        af = (f"[0:a]loudnorm=I=-16:TP=-1.5:LRA=11[vo];[1:a]atrim=start={mstart},asetpts=PTS-STARTPTS,volume={mvol},"
              f"afade=in:st=0:d=0.5,afade=out:st={fout:.2f}:d=2[m];[vo][m]amix=inputs=2:duration=first:normalize=0[a]")
    if music:
        cmd_a = ["ffmpeg", "-y", "-v", "error", "-i", tmp, "-i", str(music), "-filter_complex", af]
    else:
        cmd_a = ["ffmpeg", "-y", "-v", "error", "-i", tmp, "-filter_complex", "[0:a]loudnorm=I=-16:TP=-1.5:LRA=11[a]"]
    cmd_a += ["-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]

    if a.dry_run:
        print(f"filter graph -> {script}\n")
        print(shlex.join(cmd_v), "\n")
        print(shlex.join(cmd_a))
        return
    subprocess.run(cmd_v, check=True)
    subprocess.run(cmd_a, check=True)
    os.remove(tmp)
    print(f"DONE -> {out}")


if __name__ == "__main__":
    main()
