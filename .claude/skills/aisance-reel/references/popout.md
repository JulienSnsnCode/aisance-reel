# Popout layout: floating frame with a head cutout

Used by `aisance-light-popout` and any style with `"layout": "popout"`. Cards are a full-frame page;
the speaker sits in a rounded frame near the bottom and their head pops above the frame edge.

## Geometry (style `popout` keys)
- Frame: x `frame_x`, width `frame_w`, top `frame_top`, bottom margin `bottom_margin`, corner `radius`.
- Frame interior shows source rows starting at `frame_top - offset_speaker` (source scaled to 1080 wide).
- Popout strip: screen rows `popout_top` to `frame_top`, showing source rows
  `popout_top - offset` to `frame_top - offset`, masked by the person matte.
- `pop_target`: how many px the head top should land above the frame line. `--probe` derives the offset.
- Shadow: `shadow_alpha`, `shadow_blur`, `shadow_dy`. Mandatory on light backgrounds.
- Matte cleanup: `matte_erode` (odd px), `matte_blur`.
- Captions sit between the screen slot and the head: style `captions.y`.

## Steps
1. Final cut exists (`edit/cutF.mp4`). Everything below is redone after any re-cut.
2. `python <skill>/scripts/segment_popout.py edit/cutF.mp4 seg --style aisance-light-popout --probe`
   → suggested `offset_speaker`; put it in `reel.json`.
3. `python <skill>/scripts/segment_popout.py edit/cutF.mp4 seg --style aisance-light-popout --offset <N>`
   Runs for minutes (about one to two seconds per frame on CPU). Start it in the background right
   after the final cut, while cards render. Mattes are cached in `seg/mattes/`; a geometry change
   only rebuilds the strips.
4. `compose.py` generates `frame_mask.png`, `frame_shadow.png`, `screen_mask.png`, `screen_shadow.png`
   from the style and overlays the strips from `seg/popout/`.
5. Check a frame: hair continues across the frame edge with no duplication or shift, no halo above the hair, a visible drop shadow, the caption clears the head.

## Hook title pill (optional)
`title_png` + `title_window` in `reel.json`: one rounded block with the hook words, shown only during
the hook sentence, karaoke captions resume after. Build the PNG with PIL from the style's colours,
straight text, one soft shadow, width at most 1000 px, placed in the caption zone. Generate captions
from a copy of the transcript with the hook words removed.
