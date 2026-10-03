#!/usr/bin/env python3
"""Build <reel>/review/manifest.json for the aisance-video-editing tool (storyboard or final review).

Usage:
  python review_manifest.py <reel_dir> --stage storyboard [--no-snap]
  python review_manifest.py <reel_dir> --stage final [--video renders/x.mp4]

  Common overrides (defaults follow reel.json and the standard project layout):
    --reel reel.json  --beats cards/beats.json  --transcript edit/tF/transcripts/cutF.json
    --cues edit/cues.json  --captions <dir from reel.json>  --round N

Storyboard: one panel per beat, read from cards/timing.json (written by gen.py, so run gen.py
first). Card beats get two stills from `hyperframes snapshot`: mid-entrance and at rest. On the
band layout each still is composed with the face from the cut, so the panel shows the real 9:16
frame. "none" beats get a face-only frame. Each panel carries the card copy, its motion,
the sub-element landing times and the spoken excerpt.

Final: one track per reviewable thing. Cards come from timing.json and data-rid in index.html.
Captions come from captions/words.json. Cuts come from the EDL joins. Screen windows, SFX cues,
the music and the final mix (waveform) each get their own track. The html layer (cards/index.html)
lets the tool pick the exact sub-element under the cursor.

Writes review/manifest.<stage>.json (one per stage, so the app can switch between storyboard and
final) and review/manifest.json (the gate: the stage the skill is waiting on now).
Paths in the manifest are relative to review/. Nothing here talks to the network. Snapshots run
with GEMINI_API_KEY unset, like SKILL.md step 10. The review state (review/review.json) belongs
to the tool and is never touched here, except that a new round is announced by bumping "round".
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
HF = ["npx", "--yes", "hyperframes@0.8.91"]
HF_ENV = {"HYPERFRAMES_NO_TELEMETRY": "1", "DO_NOT_TRACK": "1", "HYPERFRAMES_NO_UPDATE_CHECK": "1"}

# role suffix of a data-rid -> (beats.json field, label); "items.2" -> /items/2
FIELD_LABEL = {"eyebrow": "eyebrow", "text": "title", "sub": "subtitle", "stat": "number", "unit": "unit",
               "chart": "chart", "items": "item", "lines": "line", "rows": "row", "msgs": "message",
               "src": "image", "caption": "caption", "day": "day", "meter": "meter", "a": "side A", "b": "side B",
               "title": "title", "name": "name"}
MOTION = ("rises from below out of a blur (0.55 s), breathes with a slow push-in while on screen, "
          "leaves upward into a blur")
TYPE_MOTION = {
    "title": "words revealed one by one from a mask",
    "cta": "words revealed, accent word underlined, meter filling up",
    "stat": "number blurs in and counts up, unit slides in, bar stretches",
    "graph": "curve drawn left to right, a dot follows it",
    "list": "rows slide in from the left, check mark drawn, focus on the current row",
    "steps": "steps slide in from the left, number spins in, focus on the current step",
    "terminal": "lines typed character by character with a cursor",
    "versus": "two columns, bars fill row by row",
    "chat": "bubbles arrive one by one",
    "flow": "boxes drop one by one, arrows stretch",
    "calendar": "month grid, the day is highlighted",
    "image": "image blurs in, then a slow zoom",
}


def load(p: Path):
    return json.loads(p.read_text())


def rel(p: Path, review: Path) -> str:
    # abspath, not resolve: a symlinked music file stays addressed through its link inside the project
    return os.path.relpath(os.path.abspath(p), os.path.abspath(review))


def ffprobe(video: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,r_frame_rate:format=duration", "-of", "json", str(video)],
                         capture_output=True, text=True, check=True).stdout
    j = json.loads(out)
    st = j["streams"][0]
    num, den = (int(x) for x in st["r_frame_rate"].split("/"))
    return {"w": st["width"], "h": st["height"], "fps": round(num / den, 3), "duration": float(j["format"]["duration"])}


def load_style(name: str) -> dict:
    p = Path(name) if name.endswith(".json") else SKILL_DIR / "styles" / f"{name}.json"
    return load(p)


def strip_marks(s) -> str:
    return re.sub(r"\*([^*]+)\*", r"\1", str(s or ""))


def field_text(beat: dict, role: str) -> str:
    """Human text of a beat sub-element, e.g. role "items.1" -> the second list item's text."""
    parts = role.split(".")
    v = beat.get(parts[0])
    if len(parts) == 2 and isinstance(v, list) and int(parts[1]) < len(v):
        v = v[int(parts[1])]
    if isinstance(v, dict):
        v = v.get("text") or v.get("title") or v.get("label") or ""
    if parts[0] == "stat":
        v = f'{beat.get("count", "")}{beat.get("suffix", "")} {beat.get("unit", "")}'.strip()
    return strip_marks(v) if isinstance(v, (str, int, float)) else ""


def beat_title(b: dict) -> str:
    kind = b.get("type", "title")
    main = b.get("text") or b.get("title") or b.get("eyebrow") or b.get("caption") or b.get("name") or ""
    if not main and kind == "stat":
        main = f'{b.get("count", "")}{b.get("suffix", "")} {b.get("unit", "")}'
    if not main and kind in ("list", "steps", "flow") and b.get("items"):
        main = b["items"][0].get("text") or b["items"][0].get("title") or ""
    return f"{kind} · {strip_marks(main)}".strip(" ·") if kind != "none" else "face only"


def beat_copy(b: dict) -> list[str]:
    """Every piece of on-screen copy in a beat, for the panel description."""
    out = []
    for k in ("eyebrow", "text", "sub", "title", "caption", "name"):
        if b.get(k):
            out.append(f"{FIELD_LABEL.get(k, k)}: \"{strip_marks(b[k])}\"")
    if b.get("type") == "stat":
        out.append(f'number: {b.get("count", "")}{b.get("suffix", "")} {b.get("unit", "")}')
    for k in ("items", "lines", "rows", "msgs"):
        for n, it in enumerate(b.get(k) or []):
            t = it.get("text") or it.get("title") or it.get("label") or ""
            sub = f' — {it["sub"]}' if it.get("sub") else ""
            out.append(f"{FIELD_LABEL[k]} {n + 1}: \"{strip_marks(t)}{sub}\"")
    if b.get("type") == "versus":
        out.append(f'versus: {b.get("a", {}).get("label") or b.get("a", {}).get("logo")} vs '
                   f'{b.get("b", {}).get("label") or b.get("b", {}).get("logo")}')
    if b.get("type") == "image":
        out.append(f'image: {b.get("src")} (frame {b.get("frame", "plain")})')
    return out


def excerpt(words: list, s: float, e: float) -> str:
    return " ".join(str(w["text"]).strip() for w in words if w.get("start") is not None and s <= w["start"] < e)


def snapshot(cards_dir: Path, times: list[float], out: Path) -> list[Path]:
    """hyperframes stills at the given times (no Gemini: the key is removed from the environment)."""
    if out.exists():
        shutil.rmtree(out)
    env = {k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"} | HF_ENV
    at = ",".join(f"{t:.2f}" for t in times)
    r = subprocess.run(HF + ["snapshot", ".", "--at", at, "--no-end", "-o", str(out.resolve())], cwd=cards_dir, env=env,
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"hyperframes snapshot failed:\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}")
    files = sorted(out.glob("frame-*.png"), key=lambda p: int(re.match(r"frame-(\d+)", p.name).group(1)))
    if len(files) != len(times):
        sys.exit(f"hyperframes snapshot wrote {len(files)} frames for {len(times)} times in {out}")
    return files


def face_frame(cut: Path, t: float, out: Path) -> Path:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0, t):.3f}", "-i", str(cut), "-frames:v", "1",
                    "-vf", "scale=1080:-2", str(out)], check=True)
    return out


def compose_band(card_png: Path | None, face_png: Path | None, st: dict, crop_y: int, out: Path) -> Path:
    """Band layout preview: cards band on top, face crop below, like compose.py (no captions/screens)."""
    from PIL import Image
    band_h = st["cards"]["band_h"]
    face_y, face_h = st["band"]["face_y"], st["band"]["face_h"]
    canvas = Image.new("RGB", (1080, 1920), st["colors"]["bg"])
    if face_png and face_png.exists():
        f = Image.open(face_png).convert("RGB")
        canvas.paste(f.crop((0, crop_y, 1080, crop_y + face_h)), (0, face_y))
    if card_png:
        c = Image.open(card_png).convert("RGB")
        canvas.paste(c.crop((0, 0, 1080, band_h)), (0, 0))
    canvas.save(out)
    return out


def build_animatic(a, reel: dict, st: dict, review: Path) -> Path:
    """Draft render of the WHOLE reel (cards at 15 fps draft quality + compose), about a minute of compute.
    It shows every animation in place: cards, screen windows rising/fading in and zooming, captions, punch-ins.
    No sound effects (they belong to the final stage)."""
    cache = review / ".cache"
    cache.mkdir(parents=True, exist_ok=True)
    for key, hint in (("cut", "the final cut (step 6)"), ("captions", "captions.py (step 11)")):
        if not reel.get(key) or not (a.reel_dir / reel[key]).exists():
            sys.exit(f"animatic: reel.json \"{key}\" is missing or absent on disk: run {hint} first, or pass --no-animatic")
    win_p = a.reel_dir / reel["windows"] if reel.get("windows") else None
    if win_p and win_p.exists():
        sdir = a.reel_dir / reel.get("screens_dir", "seg/screens")
        need = [sdir / f"w{n}.mp4" for n, _ in enumerate(load(win_p).get("windows", []))]
        if any(not f.exists() for f in need):
            sys.exit(f"animatic: screen window clips missing in {sdir}: run screen_windows.py (step 13) first")
    cards = cache / "cards_draft.mp4"
    env = {k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"} | HF_ENV
    r = subprocess.run(HF + ["render", ".", "-o", str(cards.resolve()), "--fps", "15", "--quality", "draft", "--quiet"],
                       cwd=a.beats.parent, env=env, capture_output=True, text=True)
    if r.returncode != 0 or not cards.exists():
        sys.exit(f"animatic: hyperframes render failed:\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}")
    cfg = dict(reel)
    out = review / "animatic.mp4"
    cfg["cards"] = str(cards.resolve())
    cfg["out"] = str(out.resolve())
    if st.get("layout") == "band":  # band: seg_dir only holds generated masks; keep them out of the project's seg/
        cfg["seg_dir"] = str((cache / "seg").resolve())
    cfg_p = cache / "reel.animatic.json"
    cfg_p.write_text(json.dumps(cfg, indent=1))
    r = subprocess.run([sys.executable, str(Path(__file__).with_name("compose.py")), str(cfg_p.resolve())],
                       cwd=a.reel_dir, capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        sys.exit(f"animatic: compose.py failed:\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}")
    return out


def still(video: Path, t: float, out: Path) -> Path:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0, t):.3f}", "-i", str(video), "-frames:v", "1", str(out)],
                   check=True)
    return out


def window_panels(a, reel: dict, review: Path) -> list[dict]:
    win_p = a.reel_dir / reel["windows"] if reel.get("windows") else None
    if not win_p or not win_p.exists():
        return []
    out = []
    for k, w in enumerate(load(win_p).get("windows", [])):
        s, e = float(w["start"]), float(w["end"]) + float(w.get("hold", 0))
        stages = w.get("stages") or []
        desc = [f"Screen window {k + 1}: the screen recording fills the screen slot from {s:.2f} s to {e:.2f} s. "
                "It fades and rises in, then fades out (no fade between two windows that touch)."]
        if stages:
            desc.append("Zoom stages: " + "; ".join(
                f"at +{float(z.get('at', 0)):.2f} s punch x{float(z.get('zoom', 1)):.2f} toward "
                f"({100 * float(z.get('fx', 0.5)):.0f} %, {100 * float(z.get('fy', 0.5)):.0f} %)" for z in stages) + ".")
        else:
            desc.append("No zoom: full view of the recording.")
        if w.get("src_t") is not None:
            desc.append(f"Source footage taken from {float(w['src_t']):.2f} s of the recording.")
        times = [("in", "after the entrance", s + 0.6)]
        times += [(f"z{i}", f"zoom {i + 1}", s + float(z.get("at", 0)) + 0.6) for i, z in enumerate(stages)]
        times += [("out", "before the exit", e - 0.25)]
        out.append({"id": f"win-{k}", "title": f"screen window {k + 1}", "kind": "window", "start": s, "end": e,
                    "_times": [(tag, label, min(max(t, s), e - 0.05)) for tag, label, t in times],
                    "description": "\n".join(desc), "data": w,
                    "source": {"file": rel(win_p, review), "pointer": f"/windows/{k}"}})
    return out


def storyboard(a, reel: dict, st: dict, review: Path, timing: dict, beats: list, words: list) -> dict:
    """The whole reel in order: one panel per beat (cards and face-only passages) and one per screen window.
    Default: an animatic (draft render of the whole reel); each panel plays its passage and its stills come
    from it. --no-animatic: cheaper stills only (hyperframes snapshots composed with the face)."""
    frames = review / "frames"
    if frames.exists():
        shutil.rmtree(frames)
    frames.mkdir(parents=True)
    animatic = None if a.no_animatic else build_animatic(a, reel, st, review)
    wins = window_panels(a, reel, review)

    panels = []
    for tb in timing["beats"]:
        n, bid, b = tb["n"], tb["id"], beats[tb["n"]]
        s, e = tb["start"], tb["end"]
        desc = [str(b["note"])] if b.get("note") else []
        desc += beat_copy(b)
        if tb["type"] != "none":
            desc.append(f"Motion: {MOTION}" + (f" ; {TYPE_MOTION[tb['type']]}" if tb["type"] in TYPE_MOTION else "") + ".")
            if tb["marks"]:
                lands = ", ".join(f"{FIELD_LABEL.get(r.split('.')[0], r)}{' ' + str(int(r.split('.')[1]) + 1) if '.' in r else ''}"
                                  f" at {t:.2f} s" for r, t in sorted(tb["marks"].items(), key=lambda x: x[1]))
                desc.append(f"Lands: {lands}.")
            land = max(list(tb["marks"].values()) + [s + 0.6])
            rest = max(min(max(land + 0.8, s + 1.0), e - 0.35), s + 0.35)
            times = [("in", "entrance", min(s + 0.3, e - 0.1)), ("rest", "rest", rest)]
        else:
            over = [w["title"] for w in wins if w["start"] < e and w["end"] > s]
            desc.append("No card on the band." + (f" On screen: {', '.join(over)} (see its panel)." if over
                                                    else " Only the face is on screen."))
            times = [("mid", "face only" if not over else "passage", (s + e) / 2)]
        if tb.get("topic"):
            desc.append("Subject change: the transition sound plays here.")
        panels.append({
            "id": bid, "title": beat_title(b), "kind": tb["type"], "start": s, "end": e, "_times": times,
            "description": "\n".join(desc), "excerpt": f"\"{excerpt(words, s, e)}\"" if words else "",
            "source": {"file": rel(a.beats, review), "pointer": f"/beats/{n}"}, "data": b,
        })
    for w in wins:
        w["excerpt"] = f"\"{excerpt(words, w['start'], w['end'])}\"" if words else ""

    def covered(p) -> float:
        """Share of a passage hidden behind screen windows."""
        cut = sum(max(0.0, min(p["end"], w["end"]) - max(p["start"], w["start"])) for w in wins)
        return cut / max(1e-6, p["end"] - p["start"])
    # a face-only beat entirely under screen windows would duplicate their panels: the windows tell that part
    panels = [p for p in panels if not (p["kind"] == "none" and covered(p) >= 0.95)]
    panels = sorted(panels + wins, key=lambda p: (p["start"], p["kind"] == "window"))

    if animatic:
        for p in panels:
            p["images"] = [{"src": f"frames/{still(animatic, t, frames / (p['id'] + '_' + tag + '.png')).name}",
                            "label": label, "t": round(t, 3)} for tag, label, t in p.pop("_times")]
            p["clip"] = {"start": p["start"], "end": p["end"]}
        return {"panels": panels, "duration": timing["total"], "media": {"video": rel(animatic, review)}}

    # --no-animatic: card stills from hyperframes, composed with the face on the band layout
    band = st.get("layout") == "band"
    cut = (a.reel_dir / reel["cut"]) if reel.get("cut") else None
    crop_y = int(reel.get("crop_y", st.get("band", {}).get("crop_y_default", 0)))
    want = [(p["id"], tag, label, t) for p in panels if p["kind"] not in ("none", "window") for tag, label, t in p["_times"]]
    files = snapshot(a.beats.parent, [t for *_, t in want], review / ".cache" / "snaps") if want else []
    snaps = {(pid, tag): (label, t, f) for (pid, tag, label, t), f in zip(want, files)}
    for p in panels:
        times = p.pop("_times")
        p["images"] = []
        for tag, label, t in times:
            out = frames / f"{p['id']}_{tag}.png"
            face = face_frame(cut, t, review / ".cache" / f"face-{p['id']}-{tag}.png") if cut and cut.exists() else None
            card = snaps.get((p["id"], tag), (None, None, None))[2]
            if band:
                compose_band(card, face, st, crop_y, out)
            elif card or face:
                shutil.copy(card or face, out)
            else:
                continue
            p["images"].append({"src": f"frames/{out.name}", "label": label, "t": round(t, 3)})
    return {"panels": panels, "duration": timing["total"]}


def final(a, reel: dict, st: dict, review: Path, timing: dict | None, beats: list) -> dict:
    video = a.video or newest_render(a.reel_dir)
    info = ffprobe(video)
    band = st.get("layout") == "band"
    tracks, layers = [], []

    if timing:
        items = []
        for tb in timing["beats"]:
            if tb["type"] == "none":
                continue
            b, bid = beats[tb["n"]], tb["id"]
            ptr = f"/beats/{tb['n']}"
            kids = [{"id": f"{bid}.{r}", "rid": f"{bid}.{r}", "start": t, "end": tb["end"],
                     "label": f"{FIELD_LABEL.get(r.split('.')[0], r)}{' ' + str(int(r.split('.')[1]) + 1) if '.' in r else ''}",
                     "text": field_text(b, r),
                     "source": {"file": rel(a.beats, review), "pointer": ptr + "/" + r.replace(".", "/")
                                if r.split(".")[0] in b else ptr}}
                    for r, t in sorted(tb["marks"].items(), key=lambda x: x[1])]
            items.append({"id": bid, "rid": bid, "kind": tb["type"], "start": tb["start"], "end": tb["end"],
                          "label": beat_title(b), "data": b, "children": kids,
                          "source": {"file": rel(a.beats, review), "pointer": ptr}})
        tracks.append({"id": "cards", "label": "Cards", "kind": "component", "items": items})
        page = a.beats.parent / "index.html"
        if page.exists():
            if band:
                bh = st["cards"]["band_h"]
                layers.append({"kind": "html", "src": rel(page, review), "timeline": "main", "size": [1080, 1920],
                               "crop": [0, 0, 1080, bh], "rect": [0, 0, 1080, bh], "track": "cards"})
            else:
                layers.append({"kind": "html", "src": rel(page, review), "timeline": "main", "size": [1080, 1920],
                               "rect": [0, 0, 1080, 1920], "track": "cards"})
            if "data-rid=" not in page.read_text():
                print("warning: cards/index.html has no data-rid (made by an older gen.py): re-run gen.py for element picking")

    cap_dir = a.captions or (a.reel_dir / reel["captions"] if reel.get("captions") else None)
    wj = cap_dir / "words.json" if cap_dir else None
    if wj and wj.exists():
        ws = load(wj)["words"]
        tracks.append({"id": "captions", "label": "Captions", "kind": "word", "items": [
            {"id": f"w-{k}", "text": w["text"], "start": w["start"], "end": w["end"], "bbox": w["bbox"],
             "data": {"accent": w["accent"]}, "source": {"file": rel(wj, review), "pointer": f"/words/{k}"}}
            for k, w in enumerate(ws)]})
    elif cap_dir:
        print(f"warning: no {wj}: re-run captions.py to make caption words pickable")

    edl_p = a.reel_dir / reel["cut_edl"] if reel.get("cut_edl") else None
    if edl_p and edl_p.exists():
        rs = load(edl_p)["ranges"]
        joins, acc = [], 0.0
        for k, r in enumerate(rs):
            if k:
                joins.append({"id": f"cut-{k}", "start": round(acc, 3), "label": f"cut {k}",
                              "data": {"before": rs[k - 1], "after": r},
                              "source": {"file": rel(edl_p, review), "pointer": f"/ranges/{k}"}})
            acc += float(r["end"]) - float(r["start"])
        tracks.append({"id": "cuts", "label": "Cuts", "kind": "marker", "items": joins})

    win_p = a.reel_dir / reel["windows"] if reel.get("windows") else None
    if win_p and win_p.exists():
        scr = st.get("screen") or {}
        slot = [scr["x"], scr["y"], scr["w"], scr["h"]] if band and scr else None
        items = []
        for k, w in enumerate(load(win_p).get("windows", [])):
            it = {"id": f"win-{k}", "start": float(w["start"]), "end": float(w["end"]) + float(w.get("hold", 0)),
                  "label": f"screen window {k + 1}", "data": w, "source": {"file": rel(win_p, review), "pointer": f"/windows/{k}"}}
            if slot:
                it["bbox"] = slot
            items.append(it)
        tracks.append({"id": "windows", "label": "Screen windows", "kind": "region", "items": items})

    cues_p = a.cues or a.reel_dir / "edit" / "cues.json"
    if cues_p.exists():
        tracks.append({"id": "sfx", "label": "SFX", "kind": "audio-cue", "items": [
            {"id": f"sfx-{k}", "start": float(c["t"]), "label": f'{Path(c["file"]).stem} ({c.get("kind", "")}, vol {c.get("vol")})',
             "kind": c.get("kind"), "data": {k2: v for k2, v in c.items() if k2 != "file"} | {"file": Path(c["file"]).name},
             "source": {"file": rel(cues_p, review), "pointer": f"/cues/{k}"}}
            for k, c in enumerate(load(cues_p)["cues"])]})

    tracks.append({"id": "mix", "label": "Final mix", "kind": "audio", "src": rel(video, review)})
    if reel.get("music") and (a.reel_dir / reel["music"]).exists():
        tracks.append({"id": "music", "label": f"Music (vol {reel.get('music_vol', '?')})", "kind": "audio",
                       "src": rel(a.reel_dir / reel["music"], review)})

    if band:
        tracks.append({"id": "face", "label": "Face", "kind": "region", "items": [
            {"id": "face", "start": 0, "end": info["duration"], "label": "face (framing, punch-ins)",
             "bbox": [0, st["band"]["face_y"], 1080, st["band"]["face_h"]],
             "source": {"file": rel(a.reel, review), "pointer": "/punch"}}]})

    return {"media": {"video": rel(video, review)}, "tracks": tracks, "layers": layers, "duration": info["duration"],
            "_canvas": info}


def newest_render(reel_dir: Path) -> Path:
    vids = sorted((reel_dir / "renders").glob("*.mp4"), key=lambda p: p.stat().st_mtime)
    if not vids:
        sys.exit(f"no render in {reel_dir / 'renders'}: pass --video")
    return vids[-1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("reel_dir", type=Path)
    ap.add_argument("--stage", choices=["storyboard", "final"], required=True)
    ap.add_argument("--reel", type=Path, default=None, help="reel.json (default <reel_dir>/reel.json)")
    ap.add_argument("--beats", type=Path, default=None, help="beats.json (default <reel_dir>/cards/beats.json)")
    ap.add_argument("--transcript", type=Path, default=None, help="final transcript (default edit/tF/transcripts/cutF.json)")
    ap.add_argument("--video", type=Path, default=None, help="final stage: the render to review (default newest in renders/)")
    ap.add_argument("--cues", type=Path, default=None, help="sfx cues.json (default edit/cues.json)")
    ap.add_argument("--captions", type=Path, default=None, help="captions dir with words.json (default reel.json captions)")
    ap.add_argument("--round", type=int, default=None, help="force the round number")
    ap.add_argument("--no-animatic", action="store_true",
                    help="storyboard: stills only (hyperframes snapshots), no draft render of the whole reel")
    a = ap.parse_args()

    a.reel_dir = a.reel_dir.resolve()
    a.reel = (a.reel or a.reel_dir / "reel.json").resolve()
    a.beats = (a.beats or a.reel_dir / "cards" / "beats.json").resolve()
    for k in ("video", "cues", "captions", "transcript"):
        if getattr(a, k):
            setattr(a, k, getattr(a, k).resolve())
    reel = load(a.reel)
    st = load_style(reel["style"])
    review = a.reel_dir / "review"
    review.mkdir(exist_ok=True)

    timing_p = a.beats.parent / "timing.json"
    timing = load(timing_p) if timing_p.exists() else None
    beats = load(a.beats)["beats"] if a.beats.exists() else []
    if timing and len(timing["beats"]) != len(beats):
        sys.exit(f"{timing_p} is stale ({len(timing['beats'])} beats vs {len(beats)} in beats.json): re-run gen.py")
    if a.stage == "storyboard" and not timing:
        sys.exit(f"no {timing_p}: run gen.py first (it writes timing.json next to index.html)")

    tr_p = a.transcript or a.reel_dir / "edit" / "tF" / "transcripts" / "cutF.json"
    words = load(tr_p)["words"] if tr_p.exists() else []

    gate_p = review / "manifest.json"
    stage_p = review / f"manifest.{a.stage}.json"
    gate = load(gate_p) if gate_p.exists() else None
    prev = load(stage_p) if stage_p.exists() else (gate if gate and gate.get("stage") == a.stage else None)
    rnd = a.round or ((prev["round"] + 1) if prev else 1)

    fps = float(reel.get("fps", 30))
    m = {"schema": 1, "project": a.reel_dir.name, "title": f"{a.reel_dir.name} ({reel['style']})", "round": rnd,
         "stage": a.stage, "canvas": {"w": 1080, "h": 1920, "fps": fps}}
    if a.stage == "storyboard":
        m |= storyboard(a, reel, st, review, timing, beats, words)
        m["notes"] = ("Approve each panel (A) or click in an image to pin a comment. "
                      "Nothing is rendered until every panel is approved.")
    else:
        out = final(a, reel, st, review, timing, beats)
        info = out.pop("_canvas")
        m["canvas"] = {"w": info["w"], "h": info["h"], "fps": info["fps"]}
        m |= out
    # manifest.<stage>.json keeps each stage reviewable (the app switches between them);
    # manifest.json is the gate: the stage this skill is waiting on now
    text = json.dumps(m, indent=1, ensure_ascii=False)
    for dest in (stage_p, gate_p):
        tmp = dest.with_suffix(".json.tmp")
        tmp.write_text(text)
        tmp.replace(dest)
    what = f"{len(m.get('panels', []))} panels" if a.stage == "storyboard" else \
        ", ".join(f"{t['id']}:{len(t.get('items', []))}" for t in m["tracks"])
    print(f"{gate_p} (+ {stage_p.name}) — {a.stage}, round {rnd}: {what}")
    print(f"Open it: aisance-video-editing open {a.reel_dir}")


if __name__ == "__main__":
    main()
