"""Shared helpers for HTML/GSAP graphics generators (hyperframes pages).

(aisance-reel's gen.py still carries its own copy of these
helpers; moving it onto this module is a separate, output-checked change.)

Safety: every label is HTML-escaped and every string handed to JavaScript is JSON-encoded.
Transcript words are used only to look up timings; they are never rendered as markup.
"""
from __future__ import annotations

import colorsys
import html
import json
import re
import shutil
import sys
from pathlib import Path

SHARED = Path(__file__).resolve().parent.parent
GSAP = "https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"

GRAIN_SVG = ('<svg id="grain" xmlns="http://www.w3.org/2000/svg"><filter id="gf"><feTurbulence type="fractalNoise" '
             'baseFrequency="0.85" numOctaves="3" stitchTiles="stitch"/><feColorMatrix type="saturate" values="0"/></filter>'
             '<rect width="100%" height="100%" filter="url(#gf)"/></svg>')


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def js(s) -> str:
    """A safe JS string literal, also safe inside an inline <script> block."""
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
    r, g, b = (x / 255 for x in hex_rgb(h))
    hh, ll, ss = colorsys.rgb_to_hls(r, g, b)
    r, g, b = colorsys.hls_to_rgb((hh + hue) % 1, ll * light, min(1, ss * 1.05))
    return "#%02X%02X%02X" % (round(r * 255), round(g * 255), round(b * 255))


class Words:
    """Timed words of a transcript, searchable by phrase."""

    def __init__(self, words):
        self.w = [x for x in words if x.get("start") is not None and x.get("end") is not None]
        if not self.w:
            sys.exit("transcript has no timed words")
        self.tok = [norm(x["text"]) for x in self.w]
        self.total = round(self.w[-1]["end"], 2)

    def find(self, phrase: str, after: float = 0.0, end=False):
        """Start (or end, with end=True) of the first occurrence of phrase starting at or after `after`."""
        tt = norm(phrase).split()
        if not tt:
            return None
        n = len(tt)
        idx = [i for i, t in enumerate(self.tok) if t]  # "%" or "-" alone normalise to nothing: skip them
        toks = [self.tok[i] for i in idx]
        for j in range(len(toks) - n + 1):
            i = idx[j]
            if toks[j:j + n] == tt and self.w[i]["start"] >= after - 0.01:
                return round(self.w[idx[j + n - 1]]["end"] if end else self.w[i]["start"], 2)
        return None

    def at_index(self, i: int) -> float:
        if not 0 <= i < len(self.w):
            sys.exit(f"word index {i} out of range (0..{len(self.w) - 1})")
        return round(self.w[i]["start"], 2)

    def check_expect(self, expect: dict) -> None:
        """{"<word index>": "<word>"} guards: fail when a re-cut moved the words."""
        for idx, want in (expect or {}).items():
            got = self.tok[int(idx)] if 0 <= int(idx) < len(self.tok) else None
            if got != norm(want):
                sys.exit(f"expect guard failed at word {idx}: transcript has {got!r}, expected {want!r}. "
                         "Re-check indices after any re-cut or re-transcription.")


# ---------- assets ----------
IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".svg"}
SVG_BAD = re.compile(r"<\s*script|\bon[a-z]+\s*=|<\s*foreignObject|javascript:|(?:xlink:)?href\s*=\s*[\"']\s*(?:https?:|//|data:text)|<!ENTITY|@import", re.I)


class Assets:
    """Logos and images a page references, checked before the page is written."""

    def __init__(self):
        self.referenced: list[str] = []

    def logo(self, name: str) -> str:
        if not re.fullmatch(r"[a-z0-9_-]+", str(name)):
            sys.exit(f"invalid logo name {name!r}: use letters, digits, - and _ only")
        rel = f"assets/logos/{name}.svg"
        self.referenced.append(rel)
        return rel

    def image(self, name: str) -> str:
        name = str(name)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name) or ".." in name or Path(name).suffix.lower() not in IMG_EXT:
            sys.exit(f"invalid image name {name!r}: a plain file name in assets/images/ ending in {sorted(IMG_EXT)}")
        rel = f"assets/images/{name}"
        self.referenced.append(rel)
        return rel

    def check(self, base: Path) -> None:
        """Every referenced file must exist under base and be a clean image."""
        for rel in sorted(set(self.referenced)):
            f = base / rel
            if not f.is_file():
                sys.exit(f"missing asset: {f}  (provide it, or remove the item that uses it)")
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


def copy_logos(dest_dir: Path, fill: str) -> None:
    """Shared logos next to the page; single-colour logos are recoloured for the style."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    for svg in sorted((SHARED / "assets" / "logos").glob("*.svg")):
        txt = svg.read_text()
        fills = set(re.findall(r'fill="([^"]*)"', txt))
        if fills and fills <= {"currentColor", "#ffffff", "#fff", "#FFFFFF", "#FFF"}:
            txt = re.sub(r'fill="(currentColor|#ffffff|#fff|#FFFFFF|#FFF)"', f'fill="{fill}"', txt)
        (dest_dir / svg.name).write_text(txt)


def style_assets(st: dict):
    """(kind, path relative to shared/) for every font and texture the style needs in the page."""
    out = [("fonts", f["file"]) for f in (st.get("fonts") or {}).values() if f.get("file")]
    if st.get("cards", {}).get("bg_image"):
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
    for f in (st.get("fonts") or {}).values():
        if f.get("file"):
            name = Path(f["file"]).name
            css.append(f'@font-face{{font-family:"{f["family"]}";src:url("assets/fonts/{name}") '
                       f'format("{fmt.get(Path(name).suffix.lower(), "truetype")}");font-weight:{f.get("weight_range", "100 900")};font-display:block}}')
    return "\n".join(css)


def load_style(arg: str, styles_dir: Path) -> dict:
    p = Path(arg)
    if p.suffix != ".json":
        p = styles_dir / f"{arg}.json"
    if not p.exists():
        sys.exit(f"style not found: {arg} (looked at {p})")
    return json.loads(p.read_text())


def apply_accent(st: dict, accent=None) -> dict:
    """accent: a hex colour or a subject name from the style's "accents" table."""
    if accent:
        table = {k.lower(): v for k, v in (st.get("accents") or {}).items()}
        val = table.get(str(accent).lower(), accent)
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(val)):
            sys.exit(f"accent must be #RRGGBB or one of {sorted(table)}")
        st["colors"]["accent"] = val
        st["colors"]["accent_bright"] = val
    return st
