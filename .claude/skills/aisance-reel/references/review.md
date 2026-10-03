# Review with aisance-video-editing ("apply the review" / « applique la review »)

The review app is a separate tool (https://github.com/JulienSnsnCode/aisance-video-editing, command `aisance-video-editing`).
This skill only writes `review/manifest.json` (`scripts/review_manifest.py`) and reads `review/review.json`.
There are two gates, both in SKILL.md:
- **storyboard** (step 13b): after cards, captions and screen windows are prepared, before the full-quality render. It reviews an animatic of the whole reel;
- **final**: after QA.

## Open a review
```
$PY $S/review_manifest.py . --stage storyboard     # or --stage final
aisance-video-editing open .                               # local app, 127.0.0.1 only
```
Then stop and tell the user the review is open. Do not render, do not guess what they will say.
`aisance-video-editing status .` prints `{stage, round, status, open, panels}`. `aisance-video-editing comments .`
prints the open comments as text.

## Read the review
1. `aisance-video-editing comments .` for the overview, then `review/review.json` for the details. Take only
   the comments with `status: "open"` of the current `stage`.
2. Open every `shot` (`review/shots/<id>.png`) with Read. It shows the exact frame, the outline of the
   targeted element and the pin. Read the text WITH the image: « ça » or « ici » refer to the pin.
3. Each comment has:
   - `target`: the track, item, sub-element and its `source` (file + JSON pointer);
   - `t` (seconds) and `frame`;
   - an optional `range` [start, end] the user dragged on the ruler;
   - `point` (x, y between 0 and 1 of the frame).

## Map a target to the edit
| target | where to edit | recipe |
|---|---|---|
| storyboard `panel` = beat id (+ image or animation time `t`, point) | `cards/beats.json` at `source.pointer` (`/beats/<n>`) | copy, type, trigger or `on`, per `cards.md`; a comment on a "face only" panel can ask for a card there |
| storyboard `panel` = `win-<k>` (screen window) | `edit/windows.json` at `/windows/<k>` | `screen-windows.md`: start/end, `hold`, zoom `stages` (`at`, `zoom`, `fx`, `fy`), `src_t`; then `screen_windows.py` + `zoom_review.py` |
| `track: cards`, `item` = beat id | the beat at `source.pointer` | the whole card: type, timing, `hold`, `topic` |
| `track: cards`, `sub` = `<beat>.<role>` (`items.2`, `text`, `eyebrow`, `stat`, `lines.0`…) | the field at `source.pointer` (e.g. `/beats/3/items/2`) | text, accent `*word*`, its `on` time |
| `track: captions`, `item` = `w-<k>` | the caption copy `edit/tF/transcripts/cutF_cap.json`, the word at time `t` | text only, never times; accent words via `captions.py --accent-words` or the title `*accent*` |
| `track: cuts`, `item` = `cut-<k>` | `edit/edl.json` / `edit/edl_sil.json` around that join (`data.before` / `data.after`) | `revisions.md` (clipped word end, pause too long, choppy) |
| `track: windows`, `item` = `win-<k>` | `edit/windows.json` at `/windows/<k>` | `screen-windows.md` (zoom stages, start/end) |
| `track: sfx`, `item` = `sfx-<k>` | `edit/cues.json` at `/cues/<k>` for volume or removal. A transition sound in the wrong place → fix `"topic"` in beats.json and re-run `sfx_cues.py` | `revisions.md` "After any change" |
| `track: music` / `mix` (+ `range`) | `reel.json` `music_vol`, ducking in `sfx_mix.py` | recompose |
| `track: face` | `reel.json` `crop_y` / `punch` | compose on three test frames first |
| no target (general comment) | read the text and the shot | ask if it is ambiguous |

Always apply the house rules of the reel edit preferences: never clip a word end (splice audit), keep
pauses short, and transition sounds only on real subject changes.

## Close the loop
1. Apply all the open comments, then regenerate only what they touch (`gen.py` for cards,
   `captions.py` for captions, `cutjoin` + `retime` for cuts, then `compose` and `sfx`), per
   `revisions.md` "After any change".
2. In `review/review.json`, set every comment you handled to `"status": "resolved"` with a one-line
   `"resolution"` (what changed, where). Use `"wontfix"` with the reason when you deliberately did not
   apply a comment (for example a fact-check problem). Never delete a comment and never touch `panels`
   or `approved_round`: those belong to the user.
3. Final stage: render to a new version `renders/<name>-vN+1.mp4`, never overwrite.
4. Re-run `review_manifest.py` with the same stage. It bumps `round`, and the open app reloads by
   itself. Resolved comments show "recheck" until the user confirms them.
5. Tell the user, in French, what changed per comment (one line each) and that round N+1 is open.

The gate passes only when `aisance-video-editing status .` says `"status": "approved"`:
- storyboard: every panel validated and no open comment;
- final: the user clicked "Approve the video" for the current round.
