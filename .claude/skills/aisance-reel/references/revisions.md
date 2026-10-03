# Revision recipes

For requests on a delivered reel: "retire la phrase où je dis…", "coupe ce mot", "change la musique"…
Before any change, keep the delivered file: renders are versioned (`-v4`, `-v5`…), never overwritten.
Every recipe ends with **After any change** (bottom).

## Remove a sentence or a passage
1. Find it in the final transcript, then its source range in `edit/edl.json` (the `quote` fields help).
2. Whole range: delete it. Part of a range: split the range in two around the passage. Pick both cut
   points in a micro-pause: `splice_audit.py edl` (or the 20 ms energy trace) shows where the voice is
   below the floor.
3. `splice_audit.py edl edit/edl.json --write edit/edl.json`, then `cutjoin.py` → `silence_keep.py` →
   `cutjoin.py` → transcribe the new cut ONCE.
4. Carry everything over with `retime.py` (old raw transcript → new transcript; `--files` the card
   transcript and the caption copy, `--windows`). Words of the removed passage simply disappear.
5. Remove the beat(s) of that passage from `cards/beats.json`, and its screen window if any. Word
   indices of later beats shift: rebuild `expect` from the retimed card transcript.

## Remove one word inside a take ("making on its own" → "making its own")
1. Split the range at the word: end the first part in the micro-pause before the word, start the second
   in the micro-pause after it (energy trace at 10–20 ms; protect about 30 ms of the next onset).
2. Same steps 3–5 as above. Then `splice_audit.py joins` must read the intended phrase at that join.

## Trim the start of a take ("is that they have taken" → "they have taken")
Move that range's `start` to the micro-pause before the first kept word, then steps 3–5.

## A sentence restarts or a take ends inside running speech
Find the 20–40 ms dip between the last wanted word and the next onset; end the range there.
If there is no dip (glued speech), slice-transcribe ±2 s to find the clean restart and cut there.

## Pauses feel long / the edit feels choppy
Long: re-run `silence_keep.py` (defaults are the validated fluid setting) and check `qa_gates.py` air.
Choppy: one join too tight; widen that range end by 0.05–0.10 s, then re-run the splice audit.

## A card is late, early or empty
Late/early: change its trigger word or its `on` in `beats.json`, never the voice. Empty or frozen
(`qa_gates.py` motion warning): start its hero at the beat start, add a second staged element, or
give a terminal a first line at once.

## Change the music, the style or the accent
Music: `reel.json` "music" (+ "music_vol"), recompose. Style/accent: `gen.py --style/--accent` and
the same values in `reel.json`, then re-render cards, captions (`captions.py --style`) and recompose.

## Wrong word on screen or in the captions
Fix the caption copy (text only) and re-run `captions.py`; for a card, fix `beats.json`. Never edit
the audio to match.

## After any change
1. `captions.py` → cards render → `compose.py` → `sfx_cues.py` + `sfx_mix.py` (if sound effects are on).
2. `qa_gates.py reel.json --edl edit/edl.json --sil edit/edl_sil.json --transcript <caption copy>`:
   no FAIL. Look at every motion WARN.
3. `splice_audit.py final …` and, if a join changed, `splice_audit.py joins …`.
4. Extract frames at the changed moments and look at them. Deliver as a new version number.
