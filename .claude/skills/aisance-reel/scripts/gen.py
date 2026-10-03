#!/usr/bin/env python3
"""Card generator: transcript + beats.json + style -> index.html for `npx hyperframes render`.

Usage:
  python gen.py <transcript.json> <beats.json> --style <name|path> [--accent <hex|subject>]
                [--tone dynamique|calme] [--out cards/index.html] [--copy-logos]

Each card ("beat") is anchored to a trigger word/phrase of the FINAL transcript. Card types:
title, stat, graph, list, steps, terminal, versus, chat, flow, calendar, cta, image, none.
Motion: every card arrives from below out of a blur, title words rise out of a mask, the card
breathes (slow push-in) while on screen and leaves upward into a blur. A style with
cards.look = "flow" also gets the moving aurora background, film grain and glass panels.
Field reference: references/cards.md. A trigger that is not found FAILS loudly; nothing is
silently placed at 0 s. Triggers search AFTER the previous beat's start by default, so a word
that also occurs earlier anchors to the right occurrence.

Safety: every label is HTML-escaped and every string handed to JavaScript is JSON-encoded.
Transcript words are used only to look up timings; they are never rendered as markup.
In title and cta text, *word* marks the one accent word (applied after escaping).
Logo names must match [a-z0-9_-]+ and resolve to assets/logos/<name>.svg next to the HTML.
Images must be plain file names inside assets/images/ next to the HTML (png, jpg, jpeg, webp, svg).
Every referenced logo and image is checked before the page is written: it must exist, a raster
must decode as a real image, and an SVG must contain no script, event handler, foreignObject or
external reference. A failing file stops the run.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
from pathlib import Path
from string import Template

SKILL_DIR = Path(__file__).resolve().parent.parent
SHARED = SKILL_DIR.parents[2] / "shared"  # shared engine: fonts, logos, textures, sfx
GSAP = "https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"
GSAP_MP = "https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/MotionPathPlugin.min.js"


# ---------- helpers ----------
def load_style(arg: str) -> dict:
    p = Path(arg)
    if p.suffix != ".json":
        p = SKILL_DIR / "styles" / f"{arg}.json"
    if not p.exists():
        sys.exit(f"style not found: {arg} (looked at {p})")
    return json.loads(p.read_text())


def apply_overrides(st: dict, accent=None, tone=None) -> dict:
    """--accent: a hex colour or a subject name from the style's "accents" table."""
    if accent:
        table = {k.lower(): v for k, v in (st.get("accents") or {}).items()}
        val = table.get(str(accent).lower(), accent)
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(val)):
            sys.exit(f"--accent must be #RRGGBB or one of {sorted(table)}")
        st["colors"]["accent"] = val
        st["colors"]["accent_bright"] = val
    if tone:
        st["cards"]["tone"] = tone
    return st


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def js(s) -> str:  # a safe JS string literal, also safe inside an inline <script> block
    return json.dumps(str(s)).replace("</", "<\\/").replace("<!--", "<\\!--")


def rich(s) -> str:
    """Escaped text where *word* becomes the accent span. Nothing else is interpreted."""
    return re.sub(r"\*([^*<>]+)\*", r'<span class="acc">\1</span>', esc(s))


def norm(s: str) -> str:
    return re.sub(r"[^\w\s]", "", str(s).lower()).strip()


def hex_rgb(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgba(h: str, a: float) -> str:
    r, g, b = hex_rgb(h)
    return f"rgba({r},{g},{b},{a})"


def luminance(h: str) -> float:
    r, g, b = hex_rgb(h)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def shade(h: str, hue=-0.035, light=0.78) -> str:
    """A deeper neighbour of the accent for the second aurora light (hue nudged, darker)."""
    import colorsys
    r, g, b = (x / 255 for x in hex_rgb(h))
    hh, ll, ss = colorsys.rgb_to_hls(r, g, b)
    r, g, b = colorsys.hls_to_rgb((hh + hue) % 1, ll * light, min(1, ss * 1.05))
    return "#%02X%02X%02X" % (round(r * 255), round(g * 255), round(b * 255))


def logo_src(name: str) -> str:
    if not re.fullmatch(r"[a-z0-9_-]+", str(name)):
        sys.exit(f"invalid logo name {name!r}: use letters, digits, - and _ only")
    REFERENCED.append(f"assets/logos/{name}.svg")
    return f"assets/logos/{name}.svg"


IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".svg"}
SVG_BAD = re.compile(r"<\s*script|\bon[a-z]+\s*=|<\s*foreignObject|javascript:|(?:xlink:)?href\s*=\s*[\"']\s*(?:https?:|//|data:text)|<!ENTITY|@import", re.I)
REFERENCED: list[str] = []


def image_src(name: str) -> str:
    name = str(name)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name) or ".." in name or Path(name).suffix.lower() not in IMG_EXT:
        sys.exit(f"invalid image name {name!r}: a plain file name in assets/images/ ending in {sorted(IMG_EXT)}")
    rel = f"assets/images/{name}"
    REFERENCED.append(rel)
    return rel


def check_assets(base: Path) -> None:
    """Every referenced file must exist and be a clean image. Called after --copy-logos."""
    for rel in sorted(set(REFERENCED)):
        f = base / rel
        if not f.is_file():
            sys.exit(f"missing asset: {f}  (provide it, or remove the card that uses it)")
        if f.stat().st_size > 25_000_000:
            sys.exit(f"asset over 25 MB: {f}")
        if f.suffix.lower() == ".svg":
            txt = f.read_text(errors="replace")
            if "<svg" not in txt.lower():
                sys.exit(f"not an SVG: {f}")
            m = SVG_BAD.search(txt)
            if m:
                sys.exit(f"unsafe SVG {f}: contains {m.group(0)!r}. Use a clean SVG or a PNG.")
        else:
            try:
                from PIL import Image
                with Image.open(f) as im:
                    im.verify()
            except Exception as e:  # noqa: BLE001
                sys.exit(f"not a valid image: {f} ({e})")


class Words:
    def __init__(self, words):
        self.w = [x for x in words if x.get("start") is not None and x.get("end") is not None]
        if not self.w:
            sys.exit("transcript has no timed words")
        self.tok = [norm(x["text"]) for x in self.w]
        self.total = round(self.w[-1]["end"], 2)

    def find(self, phrase: str, after: float = 0.0):
        tt = norm(phrase).split()
        if not tt:
            return None
        n = len(tt)
        for i in range(len(self.tok) - n + 1):
            if self.tok[i:i + n] == tt and self.w[i]["start"] >= after - 0.01:
                return round(self.w[i]["start"], 2)
        return None

    def at_index(self, i: int) -> float:
        if not 0 <= i < len(self.w):
            sys.exit(f"word index {i} out of range (0..{len(self.w) - 1})")
        return round(self.w[i]["start"], 2)


# ---------- CSS ----------
# Base layout shared by every look. Sizes come from the style; colours are style variables.
CSS = Template("""
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:1080px;height:1920px;overflow:hidden;background:$bg;font-family:"$font","Inter",sans-serif}
#root{position:relative;width:1080px;height:1920px;background:$bg}
#bgz{position:absolute;top:0;left:0;width:1080px;height:${band_h}px;overflow:hidden}
#grid{position:absolute;inset:-40px;background-image:linear-gradient($grid 1px,transparent 1px),linear-gradient(90deg,$grid 1px,transparent 1px);background-size:110px 110px}
#glow{position:absolute;top:120px;left:280px;width:520px;height:520px;border-radius:50%;background:radial-gradient(circle,$glow,transparent 65%);filter:blur(22px)}
.pt{position:absolute;border-radius:50%;background:$acc;box-shadow:0 0 12px $acc}
.stk{position:absolute;left:0;width:520px;height:2px;background:linear-gradient(90deg,transparent,$acc,transparent);opacity:0.3}
.beat{position:absolute;top:0;left:0;width:1080px;height:${content_h}px;opacity:0}
.drift{position:absolute;inset:0;transform-origin:50% 45%}
.inner{position:absolute;top:${safe}px;left:72px;right:72px;bottom:36px;display:flex;flex-direction:column;justify-content:center;gap:28px}
.eyebrow{align-self:flex-start;color:$acc;font-size:30px;font-weight:800;letter-spacing:6px;text-transform:uppercase;display:flex;align-items:center;gap:13px}
.eyebrow.negative{color:$neg}
.ebdot{width:14px;height:14px;border-radius:50%;background:$acc;box-shadow:0 0 14px $acc;flex:none}
.eyebrow.negative .ebdot{background:$neg;box-shadow:0 0 14px $neg}
.kw{color:$txt;font-size:112px;font-weight:900;line-height:0.98;letter-spacing:-1px}
.w{display:inline-block;overflow:hidden;vertical-align:top;padding:0.08em 0.03em 0.06em;margin:-0.08em -0.03em -0.06em}
.wi{display:inline-block;will-change:transform}
.acc{position:relative;color:$acc;--u:0}
.acc::after{content:"";position:absolute;left:0.02em;right:0.02em;bottom:0.13em;height:0.06em;border-radius:0.04em;background:$acc;transform:scaleX(var(--u));transform-origin:left center}
.sub{color:$muted;font-size:40px;font-weight:700}
.statrow{display:flex;align-items:flex-end;gap:30px}
.big{color:$txt;font-size:200px;font-weight:900;line-height:0.82;letter-spacing:-3px;transform-origin:left bottom}
.unitcol{display:flex;flex-direction:column;gap:16px;padding-bottom:22px}
.unit{color:$acc;font-size:64px;font-weight:900;text-transform:uppercase;line-height:1}
.ubar{width:260px;height:10px;border-radius:4px;background:$line;overflow:hidden}
.ubar span{display:block;height:100%;width:100%;background:$acc;transform:scaleX(0);transform-origin:left}
.chart{width:100%;height:380px;overflow:visible}
.gline{fill:none;stroke-width:9;stroke-linecap:round;stroke-linejoin:round;stroke-dasharray:1;stroke-dashoffset:1}
.ggrid{stroke:$gridc;stroke-width:2;stroke-dasharray:6 10}
.spark{width:100%;height:170px;overflow:visible}
.rows{display:flex;flex-direction:column;gap:18px}
.lrow{display:flex;align-items:center;gap:26px;background:$panel;border:1.5px solid $pborder;border-radius:24px;padding:24px 30px}
.lck{width:58px;height:58px;flex:none}.lck svg{width:100%;height:100%;overflow:visible}
.ckc{fill:$acc}.ckp{fill:none;stroke:$bg;stroke-width:4.5;stroke-linecap:round;stroke-linejoin:round;stroke-dasharray:1;stroke-dashoffset:1}
.lt{color:$txt;font-size:40px;font-weight:800;text-transform:uppercase;line-height:1}
.step{display:flex;align-items:center;gap:26px;background:$panel;border:1.5px solid $pborder;border-radius:24px;padding:22px 28px}
.snum{flex:none;width:76px;height:76px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:$acc;color:$bg;font-size:44px;font-weight:900;line-height:1}
.stx{display:flex;flex-direction:column;gap:6px}
.st1{color:$txt;font-size:38px;font-weight:900;text-transform:uppercase;line-height:1}.st2{color:$muted;font-size:28px;font-weight:600}
.term{background:$termbg;border:1.5px solid $pborder;border-radius:26px;overflow:hidden}
.tbar{display:flex;align-items:center;gap:12px;background:$termbar;padding:18px 24px;border-bottom:1px solid $line}
.td{width:16px;height:16px;border-radius:50%;background:$line}.td.r{background:$acc}
.ttitle{color:$muted;font-size:26px;font-weight:600;margin-left:12px}
.tbody{padding:28px 30px;min-height:250px}
.tline{font-size:40px;line-height:1.5;font-weight:500;white-space:pre-wrap;word-break:break-word;color:$txt;opacity:0}
.tline.muted{color:$muted}.tline.accent{color:$acc}.tline.negative{color:$neg}
.curw{opacity:0}.cur{color:$acc}
.vshead{display:flex;align-items:center;justify-content:center;gap:44px}
.vslogo{height:130px;width:130px;object-fit:contain}
.vslabel{color:$txt;font-size:64px;font-weight:900;text-transform:uppercase}.vs{color:$acc;font-size:56px;font-weight:900}
.vrow{display:grid;grid-template-columns:220px 1fr 1fr;align-items:center;gap:18px}
.vlabel{color:$muted;font-size:28px;font-weight:800;text-transform:uppercase;letter-spacing:2px}
.bar{height:40px;background:$panel;border:1.5px solid $pborder;border-radius:20px;overflow:hidden;position:relative}
.bar span.fill{position:absolute;left:0;top:0;height:100%;width:100%;transform-origin:left;transform:scaleX(0);background:$acc;border-radius:20px}
.bar.negative span.fill{background:$neg}
.bar.ref span.fill{background:$neutral}
.bval{position:absolute;right:16px;top:0;line-height:40px;color:$txt;font-size:26px;font-weight:800}
.wahead{display:flex;align-items:center;gap:16px;background:$termbar;border-radius:24px 24px 0 0;padding:22px 26px}
.waname{color:$txt;font-size:34px;font-weight:800;display:flex;flex-direction:column;line-height:1.1}.waname span{color:$acc;font-size:24px;font-weight:600}
.wabody{display:flex;flex-direction:column;gap:14px;background:$termbg;border-radius:0 0 24px 24px;padding:26px 24px}
.wbub{position:relative;max-width:84%;font-size:33px;font-weight:500;line-height:1.3;padding:20px 26px;border-radius:20px;color:$txt;background:$panel;border:1.5px solid $pborder}
.wbub.in{align-self:flex-start;border-top-left-radius:6px}.wbub.out{align-self:flex-end;border-top-right-radius:6px;border-color:$accd}
.vflow{display:flex;flex-direction:column;align-items:center;gap:12px}
.vbox{width:84%;display:flex;align-items:center;gap:22px;background:$panel;border:1.5px solid $pborder;border-radius:24px;padding:24px 30px}
.vic{font-size:54px;line-height:1}.vtx{display:flex;flex-direction:column;gap:6px}
.vt1{color:$txt;font-size:38px;font-weight:900;text-transform:uppercase;line-height:1}.vt2{color:$muted;font-size:26px;font-weight:600}
.varrow{width:4px;height:34px;border-radius:2px;background:$acc;transform-origin:top}
.calg{display:grid;grid-template-columns:repeat(7,1fr);gap:12px;background:$panel;border:1.5px solid $pborder;border-radius:26px;padding:30px}
.cal{aspect-ratio:1;display:flex;align-items:center;justify-content:center;color:$muted;font-size:34px;font-weight:700;border-radius:14px}
.cal.hot{background:$acc;color:$bg;font-weight:900}
.inner.cta{background:$panel;border:1.5px solid $accd;border-radius:32px;padding:44px;top:${safe}px;bottom:56px}
.meter{position:relative;width:100%;height:14px;background:$line;border-radius:7px;overflow:hidden}
.meter span{display:block;height:100%;width:100%;transform-origin:left;transform:scaleX(0);background:linear-gradient(90deg,$acc,$accb);border-radius:7px}
.shine{position:absolute;top:0;bottom:0;width:120px;left:-140px;background:linear-gradient(90deg,transparent,rgba(255,255,255,0.55),transparent)}
.imgwrap{flex:1;min-height:0;display:flex;align-items:center;justify-content:center}
.imgbox{max-width:100%;max-height:100%;display:flex;flex-direction:column;overflow:hidden}
.imgbox img{display:block;max-width:100%;max-height:100%;object-fit:contain;min-height:0}
.imgbox.plain img{border-radius:24px}
.imgbox.vec{width:100%;height:100%}.imgbox.vec img{width:100%;height:100%;border-radius:0;box-shadow:none}
.imgbox.browser{background:$termbg;border:1.5px solid $pborder;border-radius:24px}
.bbar{display:flex;align-items:center;gap:12px;background:$termbar;padding:14px 20px;flex:none}
.burl{flex:1;margin-left:14px;background:$bg;color:$muted;font-size:22px;font-weight:600;border-radius:14px;padding:8px 18px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.imgbox.browser img{max-height:none;flex:1;object-fit:cover;object-position:top}
.imgbox.phone{border:14px solid $termbar;border-radius:56px;background:$termbg;height:100%;aspect-ratio:9/19.5}
.imgbox.phone img{width:100%;height:100%;max-height:none;object-fit:cover;object-position:top;border-radius:42px}
.imgcap{color:$txt;font-size:44px;font-weight:900;text-transform:uppercase;text-align:center;flex:none}
.kw,.big,.st1,.vt1,.lt,.vslabel,.vs,.snum,.imgcap,.unit{font-family:"$disp","$font",sans-serif;font-weight:$dispw}
.kw{font-size:${kws}px}.big{font-size:${bigs}px}
.ttitle,.burl{font-family:"$mono",ui-monospace,"SF Mono",Menlo,monospace}
.tline{font-family:"$termf",ui-monospace,"SF Mono",Menlo,monospace}
.eyebrow,.sub,.st2,.vt2,.wbub,.waname,.vlabel,.bval,.tline,.burl{-webkit-font-smoothing:$smooth}
#bgtex{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:$bgop}
#vig{position:absolute;inset:0;background:radial-gradient(ellipse at 50% 45%,transparent 45%,rgba(0,0,0,0.7) 100%)}
""")

# "flow" look: moving aurora background, film grain, glass panels, pill eyebrows. Big type.
FLOW = Template("""
#aur{position:absolute;inset:0;opacity:0.8}
.blob{position:absolute;border-radius:50%;filter:blur(60px)}
#bl0{width:820px;height:820px;left:-260px;top:20px;background:radial-gradient(circle,$a1,transparent 62%)}
#bl1{width:700px;height:700px;left:560px;top:250px;background:radial-gradient(circle,$a2,transparent 62%)}
#bl2{width:560px;height:560px;left:260px;top:-200px;background:radial-gradient(circle,$a3,transparent 65%)}
#dots{position:absolute;inset:0;background-image:radial-gradient($dotc 1.6px,transparent 1.9px);background-size:40px 40px;
  -webkit-mask-image:radial-gradient(ellipse 70% 60% at 50% 46%,#000 10%,transparent 78%);mask-image:radial-gradient(ellipse 70% 60% at 50% 46%,#000 10%,transparent 78%)}
#grain{position:absolute;inset:0;width:100%;height:100%;opacity:$grain;mix-blend-mode:soft-light}
#fadeb{position:absolute;left:0;right:0;bottom:0;height:230px;background:linear-gradient(to bottom,$bg0,$bg)}
.lrow,.step,.vbox,.calg,.term,.wbub,.imgbox.browser,.inner.cta{background:$glass;border:1.5px solid $gline;
  box-shadow:inset 0 1.5px 0 $ghi,0 26px 60px rgba(0,0,0,0.42);-webkit-backdrop-filter:blur(18px);backdrop-filter:blur(18px)}
.wahead{background:$glass2;border:1.5px solid $gline;border-bottom:none}
.wabody{background:$glass;border:1.5px solid $gline;border-top:none}
.term .tbar{background:$glass2;border-bottom:1.5px solid $gline}
.inner.cta{border-color:$accd;box-shadow:inset 0 1.5px 0 $ghi,0 0 80px $gl,0 26px 60px rgba(0,0,0,0.42)}
.eyebrow{font-family:"$bodyf",sans-serif;font-size:26px;font-weight:700;letter-spacing:4px;padding:12px 24px 12px 18px;border-radius:999px;
  background:$accs;border:1.5px solid $accd;-webkit-font-smoothing:antialiased}
.eyebrow.negative{background:$negs;border-color:$negd}
.ebdot{width:12px;height:12px}
.sub,.st2,.vt2,.vlabel,.bval,.waname,.wbub,.ttitle{font-family:"$bodyf",sans-serif;-webkit-font-smoothing:antialiased}
.lt{font-size:62px}.st1{font-size:54px}.vt1{font-size:52px}.snum{font-size:46px}
.kw{letter-spacing:0;line-height:0.9}
.imgbox.plain img{box-shadow:0 26px 60px rgba(0,0,0,0.45)}
""")

CHROME = Template("""
.lrow,.step,.vbox,.calg,.term,.wbub,.imgbox.browser,.inner.cta,.wahead+.wabody{background:$panel;border:${bw}px solid $bcol;border-radius:${rad}px;box-shadow:${osh}px ${osh}px 0 $acc}
.imgbox.plain img{border:${bw}px solid $bcol;border-radius:${rad}px;box-shadow:${osh}px ${osh}px 0 $acc}
.wahead{border:${bw}px solid $bcol;border-bottom:none;border-radius:${rad}px ${rad}px 0 0}
.wahead+.wabody{border-radius:0 0 ${rad}px ${rad}px}
.bar{background:$termbg;border:2px solid $line;border-radius:6px}.bar span.fill{border-radius:0}
""")

RETRO = Template("""
.td{border-radius:2px;background:transparent!important;border:3px solid $txt;width:20px;height:20px}
.td.r{background:$acc!important;border-color:$acc}
.ttitle{text-transform:lowercase;font-size:32px;color:$txt}
.tbar{background:$termbar;border-bottom:${bw}px solid $bcol}
.bbar{border-bottom:${bw}px solid $bcol}
""")

GRAIN_SVG = ('<svg id="grain" xmlns="http://www.w3.org/2000/svg"><filter id="gf"><feTurbulence type="fractalNoise" '
             'baseFrequency="0.85" numOctaves="3" stitchTiles="stitch"/><feColorMatrix type="saturate" values="0"/></filter>'
             '<rect width="100%" height="100%" filter="url(#gf)"/></svg>')


# ---------- motion ----------
# One motion language for every card: things arrive from below out of a blur, words rise out of
# a mask, the card breathes slowly while it is on screen, and leaves upward into a blur.
# Everything is a tween on the paused GSAP timeline, so any frame can be seeked (no CSS animation).
M = {"in": 0.55, "item": 0.5, "word": 0.7, "stagger": 0.06, "ease": "expo.out", "out": 0.24}


def set_tone(tone: str) -> None:
    if tone == "calme":  # slower, softer: same shapes, more time
        M.update({"in": 0.8, "item": 0.75, "word": 0.95, "stagger": 0.08})


def eyebrow(text, tone="accent", eid=None):
    if not text:
        return ""
    idattr = f' id="{eid}"' if eid else ""
    return f'<div class="eyebrow {"negative" if tone == "negative" else ""}"{idattr}><span class="ebdot"></span>{esc(text)}</div>'


def eyebrow_in(eid, at):
    return (f'tl.fromTo("#{eid}",{{opacity:0,x:-24,clipPath:"inset(0% 100% 0% 0% round 999px)"}},'
            f'{{opacity:1,x:0,clipPath:"inset(0% 0% 0% 0% round 999px)",duration:{M["in"] + 0.1:.2f},ease:"expo.out"}},{at:.2f});')


def words(text) -> str:
    """Title text -> one masked span per word. *a b* marks accent words (escaped first)."""
    text = re.sub(r"\*([^*]+)\*", lambda m: " ".join(f"*{w}*" for w in m.group(1).split()), str(text))
    return " ".join(f'<span class="w"><span class="wi">{rich(w)}</span></span>' for w in text.split())


def words_in(sel, at, n_words, underline=True):
    """Rise every word out of its mask, then draw the underline under the accent word."""
    j = [f'tl.fromTo({js(sel + " .wi")},{{yPercent:112,rotation:4,opacity:0}},{{yPercent:0,rotation:0,opacity:1,'
         f'duration:{M["word"]:.2f},ease:"expo.out",stagger:{M["stagger"]}}},{at:.2f});']
    if underline:
        j.append(f'tl.fromTo({js(sel + " .acc")},{{"--u":0}},{{"--u":1,duration:0.55,ease:"power3.inOut"}},'
                 f'{at + M["stagger"] * n_words + 0.25:.2f});')
    return j


def smooth(direction):
    line = "M20,320 C170,305 230,250 360,236 S560,196 650,150 S840,66 920,48"
    if direction != "up":
        line = "M20,48 C170,63 230,118 360,132 S560,172 650,218 S840,302 920,320"
    return line, line + " L920,380 L20,380 Z"


HITS: list = []  # (time, kind) of every animation landing, written to hits.json for sfx_cues.py
MARKS: dict = {}  # beat index -> {role: time}, the resolved sub-element times written to timing.json


def enter(sel, at, dx=0, dy=28, kind="item"):
    HITS.append((round(float(at), 2), kind))
    return (f'tl.fromTo({js(sel)},{{opacity:0,x:{dx},y:{dy},filter:"blur(10px)"}},'
            f'{{opacity:1,x:0,y:0,filter:"blur(0px)",duration:{M["item"]:.2f},ease:"expo.out"}},{at:.2f});')


def focus(rows, k, at, base, acc):
    """Item k takes the accent border; earlier items step back so the eye follows the voice."""
    j = [f'tl.to({js(rows[k])},{{borderColor:{js(acc)},duration:0.3,ease:"power2.out"}},{at:.2f});']
    for r in rows[:k]:
        j.append(f'tl.to({js(r)},{{opacity:0.5,borderColor:{js(base)},duration:0.35,ease:"power2.out"}},{at:.2f});')
    return j


CHECK = ('<span class="lck"><svg viewBox="0 0 40 40"><circle class="ckc" cx="20" cy="20" r="19"/>'
         '<path class="ckp" pathLength="1" d="M11.5 20.5l5.8 5.8L29 14"/></svg></span>')


class Gen:
    def __init__(self, words_: Words, style: dict):
        self.W = words_
        self.st = style
        self.colors = style["colors"]
        self.base_border = style["colors"]["panel_border"]
        if style["cards"].get("look") == "flow":
            self.base_border = rgba(style["colors"]["text"], 0.11) if luminance(style["colors"]["bg"]) < 0.5 \
                else rgba("#000000", 0.10)

    def when(self, spec, after, default):
        """Resolve an item time: number = seconds, string = phrase searched after `after`."""
        if spec is None:
            return default
        if isinstance(spec, (int, float)):
            return float(spec)
        t = self.W.find(spec, after)
        if t is None:
            sys.exit(f"'on' phrase not found after {after:.2f}s: {spec!r}")
        return t

    def mark(self, i, role, t):
        """Remember when a sub-element lands, for timing.json (the review tool's timeline)."""
        MARKS.setdefault(i, {})[role] = round(float(t), 3)
        return t

    def head(self, i, s, p, tone="accent"):
        """Eyebrow chip, wiping open at the card start."""
        if not p.get("eyebrow"):
            return "", []
        self.mark(i, "eyebrow", s + 0.04)
        return eyebrow(p["eyebrow"], tone, f"eb{i}"), [eyebrow_in(f"eb{i}", s + 0.04)]

    # each renderer returns (inner_html, [js lines]); i = beat index, s/e = beat start/end, p = beat dict
    def card_title(self, i, s, e, p):
        on = self.mark(i, "text", self.when(p.get("on"), s, s + 0.08))
        h, j = self.head(i, s, p)
        h += f'<div class="kw" id="kw{i}">{words(p["text"])}</div>'
        HITS.append((round(on, 2), "title"))
        j += words_in(f"#kw{i}", on, len(str(p["text"]).split()))
        if p.get("sub"):
            h += f'<div class="sub" id="sb{i}">{esc(p["sub"])}</div>'
            j.append(enter(f"#sb{i}", on + 0.35, dy=20, kind="item"))
        return h, j

    def card_stat(self, i, s, e, p):
        on = self.mark(i, "stat", self.when(p.get("on"), s, s + 0.12))
        count = float(p.get("count", 0))
        suffix = str(p.get("suffix", ""))
        h, j = self.head(i, s, p)
        unit = esc(p.get("unit", ""))
        h += (f'<div class="statrow"><div class="big" id="bg{i}"><span id="big{i}">0</span>{esc(suffix)}</div>'
              f'<div class="unitcol"><div class="unit" id="un{i}">{unit}</div><div class="ubar"><span id="ub{i}"></span></div></div></div>')
        HITS.append((round(on, 2), "title"))
        j.append(f'tl.fromTo("#bg{i}",{{opacity:0,scale:0.82,filter:"blur(12px)"}},{{opacity:1,scale:1,filter:"blur(0px)",'
                 f'duration:0.7,ease:"expo.out"}},{on:.2f});')
        final = str(int(count)) if count == int(count) else str(count)
        if e - s >= 1.2 and count >= 2:  # count-up, decelerating onto the final number
            j.append(f'tl.fromTo("#big{i}",{{innerText:0}},{{innerText:{count},snap:{{innerText:1}},duration:1.0,ease:"power3.out"}},{on:.2f});')
        else:
            j.append(f'document.getElementById("big{i}").textContent={js(final)};')
        j.append(enter(f"#un{i}", on + 0.3, dx=-20, dy=0))
        j.append(f'tl.fromTo("#ub{i}",{{scaleX:0}},{{scaleX:1,duration:0.9,ease:"expo.out"}},{on + 0.4:.2f});')
        if p.get("dir") in ("up", "down"):
            color = self.colors["negative"] if p["dir"] == "down" else self.colors["accent"]
            line, _ = smooth(p["dir"])
            h += (f'<svg class="spark" viewBox="0 0 940 380" preserveAspectRatio="none"><defs><clipPath id="sc{i}">'
                  f'<rect id="sr{i}" x="0" y="0" width="0" height="380"/></clipPath></defs>'
                  f'<path clip-path="url(#sc{i})" class="gline" d="{line}" style="stroke:{color};stroke-dasharray:none"/></svg>')
            j.append(f'tl.fromTo("#sr{i}",{{attr:{{width:0}}}},{{attr:{{width:960}},duration:1.1,ease:"power2.inOut"}},{on + 0.1:.2f});')
        return h, j

    def card_graph(self, i, s, e, p):
        on = self.mark(i, "chart", self.when(p.get("on"), s, s + 0.12))
        tone = p.get("tone", "negative" if p.get("dir") == "down" else "accent")
        color = self.colors["negative"] if tone == "negative" else self.colors["accent"]
        line, area = smooth(p.get("dir", "up"))
        h, j = self.head(i, s, p, tone)
        grid = "".join(f'<line class="ggrid" x1="20" x2="920" y1="{y}" y2="{y}"/>' for y in (60, 150, 240, 330))
        h += (f'<svg class="chart" viewBox="0 0 940 380" preserveAspectRatio="xMidYMid meet"><defs>'
              f'<linearGradient id="ga{i}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{color}" stop-opacity="0.38"/>'
              f'<stop offset="1" stop-color="{color}" stop-opacity="0"/></linearGradient>'
              f'<clipPath id="gc{i}"><rect id="gr{i}" x="0" y="0" width="0" height="380"/></clipPath></defs>'
              f'<g id="gg{i}">{grid}</g>'
              f'<path d="{area}" fill="url(#ga{i})" clip-path="url(#gc{i})"/>'
              f'<g clip-path="url(#gc{i})"><path id="gp{i}" class="gline" d="{line}" style="stroke:{color};stroke-dasharray:none;'
              f'filter:drop-shadow(0 0 14px {color})"/></g>'
              f'<g id="gd{i}"><circle r="26" fill="{color}" opacity="0.22"/><circle r="12" fill="{color}"/>'
              f'<circle r="5" fill="#ffffff"/></g></svg>')
        D = 1.3
        HITS.append((round(on, 2), "title"))
        j += [f'tl.fromTo("#gg{i}",{{opacity:0}},{{opacity:1,duration:0.4}},{s:.2f});',
              f'tl.fromTo("#gr{i}",{{attr:{{width:20}}}},{{attr:{{width:960}},duration:{D},ease:"power2.inOut"}},{on:.2f});',
              f'tl.fromTo("#gd{i}",{{opacity:0}},{{opacity:1,duration:0.2}},{on:.2f});',
              f'tl.to("#gd{i}",{{motionPath:{{path:"#gp{i}",align:"#gp{i}",alignOrigin:[0.5,0.5]}},duration:{D},ease:"power2.inOut",immediateRender:true}},{on:.2f});']
        return h, j

    def card_list(self, i, s, e, p):
        h, j = self.head(i, s, p)
        rows, sels = [], []
        for k, it in enumerate(p.get("items", [])):
            rows.append(f'<div class="lrow" id="b{i}l{k}">{CHECK}<span class="lt">{esc(it["text"])}</span></div>')
            sels.append(f"#b{i}l{k}")
        for k, it in enumerate(p.get("items", [])):
            at = self.mark(i, f"items.{k}", self.when(it.get("on"), s, s + 0.15 + k * 0.32))
            j.append(enter(sels[k], at, dx=-46, dy=0))
            j.append(f'tl.fromTo("{sels[k]} .ckc",{{scale:0,transformOrigin:"50% 50%"}},{{scale:1,duration:0.4,ease:"back.out(2.2)"}},{at + 0.08:.2f});')
            j.append(f'tl.fromTo("{sels[k]} .ckp",{{strokeDashoffset:1}},{{strokeDashoffset:0,duration:0.32,ease:"power2.out"}},{at + 0.22:.2f});')
            j += focus(sels, k, at, self.base_border, self.colors["accent"])
        return h + f'<div class="rows">{"".join(rows)}</div>', j

    def card_steps(self, i, s, e, p):
        h, j = self.head(i, s, p)
        rows, sels = [], []
        for k, it in enumerate(p.get("items", [])):
            sub = f'<span class="st2">{esc(it["sub"])}</span>' if it.get("sub") else ""
            rows.append(f'<div class="step" id="b{i}s{k}"><span class="snum" id="b{i}n{k}">{k + 1}</span>'
                        f'<span class="stx"><span class="st1">{esc(it["title"])}</span>{sub}</span></div>')
            sels.append(f"#b{i}s{k}")
        for k, it in enumerate(p.get("items", [])):
            at = self.mark(i, f"items.{k}", self.when(it.get("on"), s, s + 0.15 + k * 0.35))
            j.append(enter(sels[k], at, dx=-56, dy=0))
            j.append(f'tl.fromTo("#b{i}n{k}",{{scale:0,rotation:-90}},{{scale:1,rotation:0,duration:0.5,ease:"back.out(2)"}},{at + 0.06:.2f});')
            j += focus(sels, k, at, self.base_border, self.colors["accent"])
        return h + f'<div class="rows">{"".join(rows)}</div>', j

    def card_terminal(self, i, s, e, p):
        lines, j = [], []
        t = s + 0.25
        spans = []
        for k, ln in enumerate(p.get("lines", [])):
            tone = ln.get("tone", "") if ln.get("tone") in ("muted", "accent", "negative") else ""
            text = str(ln.get("text", ""))
            chars = "".join(f'<span class="ch">{esc(ch)}</span>' for ch in text)
            lines.append(f'<div class="tline {tone}" id="tl{i}_{k}"><span id="tx{i}_{k}">{chars}</span>'
                         f'<span class="curw" id="cw{i}_{k}"><span class="cur">&#9611;</span></span></div>')
            at = self.mark(i, f"lines.{k}", self.when(ln.get("on"), s, t))
            dur = max(0.35, min(1.6, 0.03 * len(text)))
            j.append(f'tl.to("#tl{i}_{k}",{{opacity:1,duration:0.08}},{at:.2f});')
            HITS.append((round(at, 2), "type"))
            # typewriter: every character is an escaped span revealed in turn (seek-safe)
            if text:
                j.append(f'tl.fromTo("#tx{i}_{k} .ch",{{opacity:0}},{{opacity:1,duration:0.01,ease:"none",'
                         f'stagger:{dur / max(1, len(text)):.4f}}},{at:.2f});')
            spans.append(at)
            t = at + dur + 0.15
        # the caret lives on the line being typed only, and blinks there
        for k, at in enumerate(spans):
            end = spans[k + 1] if k + 1 < len(spans) else e
            j.append(f'tl.fromTo("#cw{i}_{k}",{{opacity:0}},{{opacity:1,duration:0.01}},{at:.2f});')
            if k + 1 < len(spans):
                j.append(f'tl.to("#cw{i}_{k}",{{opacity:0,duration:0.01}},{end:.2f});')
        if spans:
            reps = max(1, int((e - spans[0]) / 0.5))
            j.append(f'tl.fromTo("#term{i} .cur",{{opacity:1}},{{opacity:0,duration:0.5,ease:"steps(1)",repeat:{reps},yoyo:true}},{spans[0]:.2f});')
        h = (f'<div class="term" id="term{i}"><div class="tbar"><span class="td r"></span><span class="td y"></span><span class="td g"></span>'
             f'<span class="ttitle">{esc(p.get("title", "terminal"))}</span></div><div class="tbody">{"".join(lines)}</div></div>')
        return h, j

    def card_versus(self, i, s, e, p):
        a, b = p.get("a", {}), p.get("b", {})

        def side(x, sid):
            if x.get("logo"):
                return f'<img class="vslogo" id="{sid}" src="{logo_src(x["logo"])}" alt=""/>'
            return f'<div class="vslabel" id="{sid}">{esc(x.get("label", ""))}</div>'
        h = (f'<div class="vshead">{side(a, f"va{i}")}<div class="vs" id="vs{i}">VS</div>{side(b, f"vb{i}")}</div>')
        j = [f'tl.fromTo("#va{i}",{{opacity:0,x:-140,filter:"blur(10px)"}},{{opacity:1,x:0,filter:"blur(0px)",duration:0.6,ease:"expo.out"}},{s + 0.05:.2f});',
             f'tl.fromTo("#vb{i}",{{opacity:0,x:140,filter:"blur(10px)"}},{{opacity:1,x:0,filter:"blur(0px)",duration:0.6,ease:"expo.out"}},{s + 0.05:.2f});',
             f'tl.fromTo("#vs{i}",{{opacity:0,scale:0}},{{opacity:1,scale:1,duration:0.4,ease:"back.out(2.4)"}},{s + 0.3:.2f});']
        HITS.append((round(s + 0.3, 2), "title"))
        rows = []
        for k, r in enumerate(p.get("rows", [])):
            va, vb = float(r.get("a", 0)), float(r.get("b", 0))
            mx = max(va, vb, 1e-9)
            tone = "negative" if r.get("tone") == "negative" else "ref"
            rows.append(f'<div class="vrow" id="b{i}r{k}"><span class="vlabel">{esc(r.get("label", ""))}</span>'
                        f'<div class="bar"><span class="fill" id="fa{i}_{k}"></span><span class="bval">{esc(r.get("a_text", va))}</span></div>'
                        f'<div class="bar {tone}"><span class="fill" id="fb{i}_{k}"></span><span class="bval">{esc(r.get("b_text", vb))}</span></div></div>')
            at = self.mark(i, f"rows.{k}", self.when(r.get("on"), s, s + 0.5 + k * 0.4))
            j.append(enter(f"#b{i}r{k}", at, dy=18))
            j.append(f'tl.to("#fa{i}_{k}",{{scaleX:{max(va / mx, 0.012):.3f},duration:0.9,ease:"expo.out"}},{at + 0.1:.2f});')
            j.append(f'tl.to("#fb{i}_{k}",{{scaleX:{max(vb / mx, 0.012):.3f},duration:0.9,ease:"expo.out"}},{at + 0.1:.2f});')
        return h + f'<div class="rows">{"".join(rows)}</div>', j

    def card_chat(self, i, s, e, p):
        bubbles, j = [], []
        for k, m in enumerate(p.get("msgs", [])):
            side = "out" if m.get("side") == "out" else "in"
            bubbles.append(f'<div class="wbub {side}" id="b{i}m{k}">{esc(m["text"])}</div>')
            j.append(enter(f"#b{i}m{k}", self.mark(i, f"msgs.{k}", self.when(m.get("on"), s, s + 0.2 + k * 0.5)), dx=-30 if side == "in" else 30, dy=20))
        h = (f'<div class="wahead"><div class="waname">{esc(p.get("name", "Chat"))}<span>{esc(p.get("status", "online"))}</span></div></div>'
             f'<div class="wabody">{"".join(bubbles)}</div>')
        return h, j

    def card_flow(self, i, s, e, p):
        parts, j = [], []
        items = p.get("items", [])
        for k, it in enumerate(items):
            icon = f'<span class="vic">{esc(it["icon"])}</span>' if it.get("icon") else ""
            sub = f'<span class="vt2">{esc(it["sub"])}</span>' if it.get("sub") else ""
            parts.append(f'<div class="vbox" id="b{i}f{k}">{icon}<span class="vtx"><span class="vt1">{esc(it["title"])}</span>{sub}</span></div>')
            at = self.mark(i, f"items.{k}", self.when(it.get("on"), s, s + 0.15 + k * 0.4))
            j.append(enter(f"#b{i}f{k}", at, dy=-36))
            if k < len(items) - 1:
                parts.append(f'<div class="varrow" id="b{i}a{k}"></div>')
                j.append(f'tl.fromTo("#b{i}a{k}",{{scaleY:0}},{{scaleY:1,duration:0.35,ease:"expo.out"}},{at + 0.2:.2f});')
        return f'<div class="vflow">{"".join(parts)}</div>', j

    def card_calendar(self, i, s, e, p):
        day = int(p.get("day", 15))
        cells = "".join(f'<span class="cal{" hot" if k + 1 == day else ""}" id="c{i}_{k}">{(k + 1) if k < 30 else ""}</span>' for k in range(35))
        on = self.mark(i, "day", self.when(p.get("on"), s, s + 0.4))
        h, j = self.head(i, s, p)
        HITS.append((round(on, 2), "title"))
        j.append(f'tl.fromTo("#c{i}_{day - 1}",{{scale:0.3}},{{scale:1,duration:0.5,ease:"back.out(2.2)"}},{on:.2f});')
        return h + f'<div class="calg">{cells}</div>', j

    def card_cta(self, i, s, e, p):
        on = self.mark(i, "text", self.when(p.get("on"), s, s + 0.25))
        h, j = self.head(i, s, p)
        h += (f'<div class="kw" id="kw{i}">{words(p["text"])}</div>'
              f'<div class="meter"><span id="mt{i}"></span><i class="shine" id="sh{i}"></i></div>')
        HITS.append((round(on, 2), "title"))
        j += words_in(f"#kw{i}", s + 0.12, len(str(p["text"]).split()), underline=False)
        j.append(f'tl.fromTo("#kw{i} .acc",{{"--u":0}},{{"--u":1,duration:0.55,ease:"power3.inOut"}},{on:.2f});')
        j.append(f'tl.fromTo("#mt{i}",{{scaleX:0}},{{scaleX:1,duration:1.1,ease:"expo.out"}},{on + 0.1:.2f});')
        reps = max(0, int((e - on - 1.2) / 1.6))
        j.append(f'tl.fromTo("#sh{i}",{{x:0}},{{x:1100,duration:0.9,ease:"power2.inOut",repeat:{reps},repeatDelay:0.7}},{on + 0.9:.2f});')
        return h, j

    def card_image(self, i, s, e, p):
        src = image_src(p["src"])
        frame = p.get("frame", "plain")
        if frame not in ("plain", "browser", "phone"):
            sys.exit(f"beat {i}: image frame must be plain | browser | phone")
        on = self.mark(i, "src", self.when(p.get("on"), s, s + 0.05))
        img = f'<img id="im{i}" src="{src}" alt=""/>'
        if frame == "browser":
            box = (f'<div class="imgbox browser" id="ib{i}"><div class="bbar"><span class="td r"></span><span class="td y"></span>'
                   f'<span class="td g"></span><span class="burl">{esc(p.get("url", ""))}</span></div>{img}</div>')
        else:
            vec = " vec" if frame == "plain" and src.lower().endswith(".svg") else ""
            box = f'<div class="imgbox {frame}{vec}" id="ib{i}">{img}</div>'
        h, j = self.head(i, s, p)
        h += f'<div class="imgwrap">{box}</div>'
        HITS.append((round(on, 2), "title"))
        j.append(f'tl.fromTo("#ib{i}",{{opacity:0,y:70,scale:0.92,filter:"blur(12px)"}},{{opacity:1,y:0,scale:1,filter:"blur(0px)",'
                 f'duration:0.7,ease:"expo.out"}},{on:.2f});')
        if p.get("zoom", True):  # slow push-in so a still never reads as a static slide
            j.append(f'tl.fromTo("#im{i}",{{scale:1}},{{scale:1.06,duration:{max(0.5, e - on):.2f},ease:"none"}},{on:.2f});')
        if p.get("caption"):
            h += f'<div class="imgcap" id="ic{i}">{esc(p["caption"])}</div>'
            j.append(enter(f"#ic{i}", self.mark(i, "caption", self.when(p.get("caption_on"), s, on + 0.3)), dy=20))
        return h, j

    def card_none(self, i, s, e, p):
        return "", []


def copy_logos(dest_dir: Path, fill: str) -> None:
    src = SHARED / "assets" / "logos"
    dest_dir.mkdir(parents=True, exist_ok=True)
    for svg in sorted(src.glob("*.svg")):
        txt = svg.read_text()
        fills = set(re.findall(r'fill="([^"]*)"', txt))
        mono = fills and fills <= {"currentColor", "#ffffff", "#fff", "#FFFFFF", "#FFF"}
        if mono:  # single-colour logos follow the style; multi-colour brand marks stay as they are
            txt = re.sub(r'fill="(currentColor|#ffffff|#fff|#FFFFFF|#FFF)"', f'fill="{fill}"', txt)
        (dest_dir / svg.name).write_text(txt)


def style_assets(st: dict):
    """(kind, path relative to shared/) for every font and texture the style needs in the page."""
    out = []
    for role, f in (st.get("fonts") or {}).items():
        if f.get("file"):
            out.append(("fonts", f["file"]))
    if st["cards"].get("bg_image"):
        out.append(("textures", st["cards"]["bg_image"]))
    return out


def copy_style_assets(dest: Path, st: dict) -> None:
    for kind, rel in style_assets(st):
        src = (SHARED / rel).resolve()
        if (SHARED / "assets").resolve() not in src.parents or not src.is_file():
            sys.exit(f"style asset must be a file inside shared/assets: {rel}")
        d = dest / "assets" / kind
        d.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, d / src.name)


def font_faces(st: dict) -> str:
    fmt = {".woff2": "woff2", ".woff": "woff", ".ttf": "truetype", ".otf": "opentype"}
    css = []
    for role, f in (st.get("fonts") or {}).items():
        if f.get("file"):
            name = Path(f["file"]).name
            css.append(f'@font-face{{font-family:"{f["family"]}";src:url("assets/fonts/{name}") '
                       f'format("{fmt.get(Path(name).suffix.lower(), "truetype")}");font-weight:{f.get("weight_range", "100 900")};font-display:block}}')
    return "\n".join(css)


# element id pattern -> review role; roles mirror beats.json fields so "<beat id>.<role>" maps to a JSON pointer
RID_ROLES = [
    (r"eb{i}", "eyebrow"), (r"kw{i}", "text"), (r"sb{i}", "sub"), (r"bg{i}", "stat"), (r"un{i}", "unit"),
    (r"b{i}l(\d+)", "items.{0}"), (r"b{i}s(\d+)", "items.{0}"), (r"b{i}f(\d+)", "items.{0}"),
    (r"term{i}", "lines"), (r"tl{i}_(\d+)", "lines.{0}"), (r"va{i}", "a"), (r"vb{i}", "b"), (r"b{i}r(\d+)", "rows.{0}"),
    (r"b{i}m(\d+)", "msgs.{0}"), (r"ib{i}", "src"), (r"ic{i}", "caption"), (r"mt{i}", "meter"),
]


def tag_rids(inner: str, i: int, bid: str) -> str:
    """Add data-rid="<beat id>.<role>" to the addressable elements of one card (review tool picking)."""
    for pat, role in RID_ROLES:
        rx = re.compile(r'id="(' + pat.replace("{i}", str(i)) + r')"')
        inner = rx.sub(lambda m: f'{m.group(0)} data-rid="{esc(bid)}.{role.format(*m.groups()[1:])}"', inner)
    inner = re.sub(r'<svg class="(chart|spark)"', lambda m: f'<svg class="{m.group(1)}" data-rid="{esc(bid)}.chart"', inner)
    inner = re.sub(r'<div class="calg">', f'<div class="calg" data-rid="{esc(bid)}.day">', inner)
    return inner


def beat_ids(beats: list) -> list:
    """Stable id per beat ("id" field, else beat<n>); the review tool keys comments on it across rounds."""
    ids = []
    for n, b in enumerate(beats):
        bid = str(b.get("id") or f"beat{n}")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", bid):
            sys.exit(f"beat {n}: id must match [A-Za-z0-9_-]+, got {bid!r}")
        if bid in ids:
            sys.exit(f"beat {n}: duplicate id {bid!r}")
        ids.append(bid)
    return ids


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("transcript", type=Path)
    ap.add_argument("beats", type=Path)
    ap.add_argument("--style", required=True)
    ap.add_argument("--accent", default=None, help="#RRGGBB or a subject from the style's accents table (claude, n8n...)")
    ap.add_argument("--tone", choices=["dynamique", "calme"], default=None, help="override the style's cards.tone")
    ap.add_argument("--out", type=Path, default=Path("index.html"))
    ap.add_argument("--copy-logos", action="store_true", help="copy skill logos next to the HTML, recoloured for the style")
    a = ap.parse_args()

    st = apply_overrides(load_style(a.style), a.accent, a.tone)
    set_tone(st["cards"].get("tone", "dynamique"))
    W = Words(json.loads(a.transcript.read_text())["words"])
    spec = json.loads(a.beats.read_text())
    for idx, want in (spec.get("expect") or {}).items():
        got = W.tok[int(idx)] if 0 <= int(idx) < len(W.tok) else None
        if got != norm(want):
            sys.exit(f"expect guard failed at word {idx}: transcript has {got!r}, beats.json expects {want!r}. "
                     "Re-check indices after any re-cut or re-transcription.")

    beats = spec.get("beats") or []
    if not beats:
        sys.exit("beats.json has no beats")

    # resolve starts
    starts = []
    prev = 0.0
    for n, b in enumerate(beats):
        if "at" in b:
            t = float(b["at"])
        elif "index" in b:
            t = W.at_index(int(b["index"]))
        elif "trigger" in b:
            after = float(b["after"]) if "after" in b else prev
            t = W.find(b["trigger"], after)
            if t is None:
                sys.exit(f"beat {n}: trigger not found after {after:.2f}s: {b['trigger']!r}")
        else:
            sys.exit(f"beat {n}: needs one of trigger | at | index")
        starts.append(t)
        prev = t
    # resolve ends (next start, or explicit end) + hold; a hold pushes the next beat
    ends = []
    for n, b in enumerate(beats):
        if "end" in b:
            end = float(b["end"]) if isinstance(b["end"], (int, float)) else W.find(b["end"], starts[n])
            if end is None:
                sys.exit(f"beat {n}: end phrase not found: {b['end']!r}")
        else:
            end = starts[n + 1] if n + 1 < len(beats) else W.total + 0.2
        end += float(b.get("hold", 0))
        if n + 1 < len(beats) and starts[n + 1] < end and "at" not in beats[n + 1]:
            starts[n + 1] = end
        ends.append(round(end, 2))
    for n in range(len(beats)):
        if ends[n] <= starts[n]:
            sys.exit(f"beat {n} has non-positive duration ({starts[n]}-{ends[n]})")
    total = max(W.total + 0.2, ends[-1])

    ids = beat_ids(beats)
    g = Gen(W, st)
    c = st["colors"]
    flow = st["cards"].get("look") == "flow"
    clips, tweens = [], []
    for n, b in enumerate(beats):
        kind = b.get("type", "title")
        fn = getattr(g, f"card_{kind}", None)
        if fn is None:
            sys.exit(f"beat {n}: unknown card type {kind!r}")
        s, e = starts[n], ends[n]
        inner, jsl = fn(n, s, e, b)
        dur = max(0.5, e - s)
        cls = "inner cta" if kind == "cta" else "inner"
        inner = tag_rids(inner, n, ids[n])
        clips.append(f'<div class="beat" id="beat{n}" data-rid="{esc(ids[n])}" data-start="{s}" data-duration="{dur:.2f}" data-track-index="{n + 2}">'
                     f'<div class="drift" id="dr{n}"><div class="{cls}" id="in{n}">{inner}</div></div></div>')
        if b.get("topic"):  # a change of subject: the only place the transition sound plays
            HITS.append((round(s, 2), "topic"))
        if kind == "none":
            continue
        HITS.append((round(s, 2), "card"))
        out = min(M["out"], dur / 3)
        lines = [f'tl.fromTo("#beat{n}",{{opacity:0}},{{opacity:1,duration:0.01}},{s:.2f});',
                 # arrive from below out of a blur
                 f'tl.fromTo("#in{n}",{{opacity:0,y:64,filter:"blur(14px)"}},{{opacity:1,y:0,filter:"blur(0px)",duration:{M["in"]:.2f},ease:"expo.out"}},{s:.2f});',
                 # breathe while on screen: a slow push-in, so a resting card is never a frozen frame
                 f'tl.fromTo("#dr{n}",{{scale:1,y:0}},{{scale:1.035,y:-14,duration:{dur:.2f},ease:"sine.inOut"}},{s:.2f});']
        if flow:  # the background answers every new card with a soft bloom
            lines.append(f'tl.fromTo("#aur",{{opacity:1}},{{opacity:0.8,duration:1.2,ease:"power2.out"}},{s:.2f});')
        lines += jsl
        # leave upward into a blur, handing over to the next card
        lines.append(f'tl.to("#in{n}",{{opacity:0,y:-56,filter:"blur(12px)",duration:{out:.2f},ease:"power2.in"}},{e - out:.2f});')
        tweens.append("\n      ".join(lines))

    # decorative layer (deterministic loops on a scrubbed timeline)
    decor_html, decor_js = "", []
    if flow:
        decor_html += ('<div id="aur"><span class="blob" id="bl0"></span><span class="blob" id="bl1"></span>'
                       '<span class="blob" id="bl2"></span></div><div id="dots"></div>' + GRAIN_SVG)
        for k, (dx, dy, sc, per) in enumerate(((190, 80, 1.18, 9.0), (-170, -90, 1.12, 11.0), (140, 110, 1.25, 13.0))):
            reps = int(total / per) + 2
            decor_js.append(f'tl.fromTo("#bl{k}",{{x:0,y:0,scale:1}},{{x:{dx},y:{dy},scale:{sc},duration:{per},yoyo:true,repeat:{reps},ease:"sine.inOut"}},0);')
        decor_js.append(f'tl.fromTo("#dots",{{backgroundPosition:"0px 0px"}},{{backgroundPosition:"0px 40px",duration:5,ease:"none",repeat:{int(total / 5) + 2}}},0);')
    if st["cards"].get("bg_image"):
        decor_html += f'<img id="bgtex" src="assets/textures/{Path(st["cards"]["bg_image"]).name}" alt=""/>'
    if st["cards"].get("vignette"):
        decor_html += '<div id="vig"></div>'
    if flow and st["layout"] == "band":
        decor_html += '<div id="fadeb"></div>'  # the band melts into the background colour above the face
    if st["cards"].get("tone") == "calme" and st["cards"].get("bg_image"):
        reps = int(total / 8) + 2  # barely perceptible breathing of the texture, no other decor
        decor_js.append(f'tl.fromTo("#bgtex",{{scale:1}},{{scale:1.015,duration:4,yoyo:true,repeat:{reps},ease:"sine.inOut"}},0);')
    if st["cards"].get("decor", True) and not flow:
        NP = 22
        decor_html += (f'<div id="grid"></div><div id="glow"></div>'
                      + "".join(f'<span class="stk" id="stk{k}" style="top:{120 + k * 230}px"></span>' for k in range(3))
                      + "".join(f'<span class="pt" id="pt{k}" style="left:{(k * 131 + 40) % 1040}px;top:{(k * 97 + 30) % 760}px;'
                                f'width:{5 + (k % 3) * 3}px;height:{5 + (k % 3) * 3}px;opacity:{0.12 + 0.2 * ((k * 7) % 5) / 5:.2f}"></span>'
                                for k in range(NP)))
        reps = int(total / 6) + 2
        decor_js = [f'tl.to("#glow",{{x:120,y:30,scale:1.15,duration:6,yoyo:true,repeat:{reps},ease:"sine.inOut"}},0);',
                    f'tl.to("#grid",{{backgroundPosition:"0px 110px",duration:6,ease:"none",repeat:{reps}}},0);']
        for k in range(NP):
            d = 4 + (k % 5)
            r = int(total / d) + 2
            decor_js.append(f'tl.to("#pt{k}",{{y:-{120 + (k % 4) * 60},duration:{d},ease:"none",repeat:{r}}},0);')
            decor_js.append(f'tl.to("#pt{k}",{{opacity:0,duration:{d},yoyo:true,repeat:{r},ease:"sine.inOut"}},0);')
        for k in range(3):
            decor_js.append(f'tl.fromTo("#stk{k}",{{x:-1200}},{{x:1200,duration:{5 + k * 2},ease:"none",repeat:{int(total / (5 + k * 2)) + 2}}},{k * 1.5});')

    dark = luminance(c["bg"]) < 0.5
    fonts = st.get("fonts") or {}
    body_f = fonts.get("body", {}).get("family", st["font"]["family"])
    disp = fonts.get("display", {})
    cd = st["cards"]
    css = font_faces(st) + CSS.substitute(
        disp=disp.get("family", body_f), dispw=disp.get("weight", 900),
        mono=fonts.get("mono", {}).get("family", "SF Mono"), termf=fonts.get("term", {}).get("family", "SF Mono"),
        smooth="none" if fonts.get("body", {}).get("pixel") else "antialiased",
        kws=cd.get("kw_size", 112), bigs=cd.get("big_size", 200), neutral=c.get("neutral", c["muted"]),
        bgop=cd.get("bg_image_opacity", 0.6), safe=cd.get("safe_top", 55),
        bg=c["bg"], txt=c["text"], muted=c["muted"], acc=c["accent"], accb=c.get("accent_bright", c["accent"]),
        neg=c["negative"], panel=c["panel"], pborder=c["panel_border"], font=st["font"]["family"],
        accd=rgba(c["accent"], 0.45), gl=rgba(c["accent"], 0.16),
        grid=rgba(c["accent"], st["cards"].get("grid_alpha", 0.05)), glow=rgba(c["accent"], st["cards"].get("glow_alpha", 0.2)),
        band_h=st["cards"]["band_h"], content_h=st["cards"]["content_h"], line=c.get("line", c["panel_border"]),
        gridc=rgba(c["text"], 0.09),
        termbg=st["cards"].get("term_bg", "#0c0f0e" if dark else "#f3f3f1"),
        termbar=st["cards"].get("term_bar", "#161b19" if dark else "#e4e4e1"),
    )
    chrome_vars = dict(panel=c["panel"], bcol=c["panel_border"], bw=cd.get("border_w", 2), rad=cd.get("radius", 20),
                       osh=cd.get("offset_shadow", 0), acc=c["accent"], line=c.get("line", c["panel_border"]),
                       termbg=cd.get("term_bg", "#0c0f0e" if dark else "#f3f3f1"),
                       termbar=cd.get("term_bar", "#161b19" if dark else "#e4e4e1"), txt=c["text"])
    if flow:
        a1, a2 = c["accent"], c.get("accent2") or shade(c["accent"])
        ink = c["text"] if dark else "#000000"
        css += FLOW.substitute(
            a1=rgba(a1, cd.get("aurora", 0.42)), a2=rgba(a2, cd.get("aurora", 0.42) * 0.8), a3=rgba(ink, 0.07),
            dotc=rgba(ink, 0.11), grain=cd.get("grain", 0.16), bg=c["bg"], bg0=rgba(c["bg"], 0),
            glass=f"linear-gradient(180deg,{rgba(ink, 0.085)},{rgba(ink, 0.03)})", glass2=rgba(ink, 0.06),
            gline=rgba(ink, 0.11), ghi=rgba(ink, 0.14), accs=rgba(c["accent"], 0.12), accd=rgba(c["accent"], 0.4),
            negs=rgba(c["negative"], 0.12), negd=rgba(c["negative"], 0.4), gl=rgba(c["accent"], 0.18),
            bodyf=fonts.get("body", {}).get("family", body_f))
    elif "border_w" in cd:
        css += CHROME.substitute(chrome_vars)
    if cd.get("window") == "retro":
        css += RETRO.substitute(chrome_vars)
    if cd.get("tone") == "calme":  # smooth curves only: no overshoot anywhere
        tweens = [re.sub(r'back\.out\([0-9.]*\)', "expo.out", x) for x in tweens]
    page = f'''<!doctype html><html lang="en"><head><meta charset="UTF-8"/>
<meta name="viewport" content="width=1080, height=1920"/>
<script src="{GSAP}"></script>
<script src="{GSAP_MP}"></script>
<style>{css}</style></head><body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{total:.2f}" data-width="1080" data-height="1920">
  <div id="bgz" data-start="0" data-duration="{total:.2f}" data-track-index="0">{decor_html}</div>
  {"".join(clips)}
</div>
<script>gsap.registerPlugin(MotionPathPlugin);window.__timelines=window.__timelines||{{}};const tl=gsap.timeline({{paused:true}});
      {chr(10).join(decor_js)}
      {chr(10).join(tweens)}
window.__timelines["main"]=tl;</script></body></html>'''

    a.out.parent.mkdir(parents=True, exist_ok=True)
    if a.copy_logos:
        copy_logos(a.out.parent / "assets" / "logos", st["cards"].get("logo_fill", c["text"]))
    copy_style_assets(a.out.parent, st)
    hits = sorted({h for h in HITS if 0 <= h[0] <= total})
    (a.out.parent / "hits.json").write_text(json.dumps({"hits": [{"t": t0, "kind": k} for t0, k in hits]}, indent=1))
    timing = {"total": round(total, 3), "beats": [
        {"n": n, "id": ids[n], "type": b.get("type", "title"), "start": round(starts[n], 3), "end": round(ends[n], 3),
         "topic": bool(b.get("topic")), "marks": MARKS.get(n, {})} for n, b in enumerate(beats)]}
    (a.out.parent / "timing.json").write_text(json.dumps(timing, indent=1, ensure_ascii=False))
    check_assets(a.out.parent)
    a.out.write_text(page)
    print(f"{len(beats)} beats, {total:.2f}s, style {st['name']}, accent {c['accent']}, tone {st['cards'].get('tone', 'dynamique')} -> {a.out}")
    for n, b in enumerate(beats):
        print(f"  {starts[n]:6.2f}-{ends[n]:6.2f}  {ids[n]:14s} {b.get('type', 'title'):9s} {b.get('trigger', b.get('at', b.get('index')))}")


if __name__ == "__main__":
    main()
