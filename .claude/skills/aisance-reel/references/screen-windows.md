# Screen windows: split-screen tutorial reels

The screen recording (often the same file that carries the mic audio) is also the demo footage.
It appears in the screen slot exactly while the creator narrates an on-screen action; cards
show when they only talk.

## 1. Decide the windows from the FINAL transcript
A window is a sentence where the creator references the screen ("just find the...", "paste that
into...", "Claude is now going to..."). Hook, concept and CTA sentences stay cards. A window runs
from the first word's start minus 0.05 s to the next non-demo word's start. Back-to-back windows
merge visually, the zoom resets per window. Author `none` beats for these stretches.

## 2. windows.json
```json
{
  "screen_src": "raw/screen.mov", "offset": 1.585,
  "src_crop": "1664:936:128:40",
  "edl": "edit/edl.json", "edl_sil": "edit/edl_sil.json", "extra_edls": ["edit/edl_fix.json"],
  "windows": [
    {"start": 5.7, "end": 9.5, "hold": 0.5, "punch": 0.35,
     "stages": [{"at": 0.5, "zoom": 1.6, "fx": 0.0, "fy": 0.1},
                {"at": 2.7, "zoom": 1.9, "fx": 1.0, "fy": 0.0}]}
  ]
}
```
- `offset`: screen time minus master time (from `align_sources.py` when the screen file carries the audio).
- `src_crop`: run `ffmpeg -i screen.mov -vf cropdetect -t 5 -f null -` and trim the menubar and dock so the result is exactly 16:9. Mac screens are about 16:10, never ship the bars.
- `extra_edls`: every micro-fix EDL applied after the silence pass, in the order applied.
- Per-window overrides: `screen_src`, `offset`, `src_crop`, `src_t` (absolute source time, for footage from a different moment, like a receipt shown under the hook claim).
- `stages`: the punch moves from focus to focus on trigger words (`at` is seconds from the window start).

## 3. Zoom rules
- Punch-in, not ken-burns: about 0.5 s full view, a 0.35 s cosine punch onto the focus, then hold.
- Zoom 1.6 to 1.9 for small UI (inputs, popups, buttons), 1.3 to 1.5 for text blocks, 2.2 to 2.6 for a proof number in a hook.
- The focus is what the viewer must read. Pick it by LOOKING at a frame of each window.
- Left-aligned content needs fx = 0 (address bars, queries, code, sidebars); headers need fy near 0.
- App focus map: terminal → the welcome banner or the latest response block, never an empty panel center; browser → the repo header or button, then the address bar when the narration says copy the URL; dictation tool → its popup for the whole time they speak; editor → the active file region.

## 4. Render and review
```
python <skill>/scripts/screen_windows.py edit/windows.json seg/screens
python <skill>/scripts/zoom_review.py edit/windows.json seg/screens
```
Never compose with a flagged stage. Suggestions are starting points: pick the semantically right
target, not the busiest region. Re-run until every stage passes, then set `windows` and
`screens_dir` in `reel.json`.

## 5. Silent demo stretches
Usually cut: the voice EDL drives the reel. If one must stay, keep it as its own EDL range with a
window and no captions.

## 6. Multi-pair reels (hook and body recorded separately)
Pair files by matching durations, align each pair with its own offset, mux each master, concat
hook-master and body-master (concat filter, re-encode) into one master, run the pipeline on it.
Body windows use `offset_body - hook_master_duration`; use per-window `screen_src` and `offset`.
