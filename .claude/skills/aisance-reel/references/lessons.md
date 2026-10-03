# Lessons: rules distilled from real reels

Every row cost at least one re-render once. Grouped by pipeline stage. Project names and
personal anecdotes were removed; the technical rule is what matters.

## Source and takes
| Symptom | Rule |
|---|---|
| Director's notes end up in the voiceover | Raws are multi-take with spoken notes ("put a clip here", "ok so"). Hand-pick the clean take of every sentence in a keep-EDL. |
| One very long "word" (2-4 s) in the raw transcript | It hides a retake or a false start. Inspect the window with `silencedetect`; if there is no pause, slice-transcribe ±2 s around it and split on the clean restart. Assume it may hide MORE than one take. After re-cutting, slice-transcribe around every splice of the FINAL cut to prove the dupe is gone. |
| Same sentence spoken three times | Keep ONE, the cleanest. Content triads that are lists stay. |
| Doubled openers across kept takes ("Well, ... Well, ...") | Scan consecutive sentences for identical connectors or intro clauses; keep the connector once, micro-cut the second. |
| Redundant confirmation clauses ("... to make sure you got them") | Cut them; the visual already says it. |
| ffprobe reports 1920x1080 but the clip is vertical | Rotation metadata. Extract a frame and LOOK before pre-cropping. |
| Two recordings, camera video plus a separate mic | Align by transcript word matching (`align_sources.py`), mux camera video with the good audio, then run the pipeline on that master. |

## Cutting and sync
| Symptom | Rule |
|---|---|
| Word endings clipped at splices even with padding | Transcribers end words 0.1 to 0.3 s early, and soft French endings ("cas", "tâche", "GDPval") fade slowly. Never trust transcript ends for boundaries: run `splice_audit.py edl` on the keep-EDL before cutting, and `splice_audit.py final` after. |
| A splice starts with a fragment of the previous word ("-nant" before "je vous conseille") | The transcriber placed the next word late. `splice_audit.py edl` flags starts with loud audio just before them and moves the start into the micro-pause. |
| Cuts feel choppy or pauses feel long | Validated setting: `silence_keep` defaults (-40 dB, min 0.28, pad 0.14 after, 0.07 before). Longer pads read as dead air, as long as tails are protected by the splice audit. |
| Audio drifts from video after about 40 s | Never concat-copy AAC segments. `cutjoin.py` re-encodes segments and joins with the concat FILTER. Verify video stream duration ≈ audio duration, under one frame apart. |
| Long pauses left after the cut | Word-gap trimming is not enough. Run `silence_keep.py`, which detects real silences in the audio. |
| Words clipped: "output" becomes "out" | Threshold too aggressive. Keep -40 dB, or -35 in a noisy room, never -30/-32. Extend EDL ends by 0.2 to 0.4 s. Verify the AUDIO of the cut, not the transcript: transcribers auto-complete cut words. |
| `silence_keep` finds zero silences | Noise floor above the threshold. Try `--db -35`; if still nothing, hand-write a tight keep-EDL from `silencedetect` output. |
| Pauses of 0.35 to 0.5 s survive | Defaults are `--min 0.35 --pad-after 0.12`. For a punchier short use `--min 0.30`. After the cut, print word gaps; over 0.30 s between sentences means tighten. |
| New pauses appear AFTER the silence pass | Splice pads at EDL boundaries add up. Print per-word gaps of the FINAL transcript and micro-cut splice-point gaps over 0.30 s. |
| Stale transcript after a re-cut | `transcribe.py` reuses a JSON only if it is newer than the video. Still read its "cached" line; a word ending later than the file duration means stale, use `--force`. |
| Re-cut done, render misaligned | After ANY re-cut, rebuild everything derived from it: transcript, captions, cards, windows, popout strips, and point `reel.json` "cut" at the new file. |

## Transcription and captions
| Symptom | Rule |
|---|---|
| A whole phrase missing from the transcript | Whisper can drop a phrase entirely ("mais il est vraiment assez proche malgré tout" vanished from the full pass). Compare `silencedetect` voice regions with the transcript and slice-transcribe any voiced region that has too few words. |
| Invented restarts, words or sentence breaks | Whisper also hallucinates ("qui permet de vérifier. Un modèle qui permet de vérifier", "à ne pas hésiter. On peut l'utiliser", "je vais le déterminer"). Before cutting a "restart", slice-transcribe it: if the slice has no restart, the take is clean. For captions, when passes disagree keep the focused slice, then the majority of passes. |
| Hand-patched captions lost after a re-cut | Do not re-transcribe and re-patch: transcribe the new cut once and run `retime.py` to carry the patched captions, the card transcript and the windows onto the new timing (anchor error was under 0.1 s). |
| Wrong claim in the speech ("travaille 30 % moins" when the page says costs up to 30 % less) | Check every fact against the screen or source. Cut the wrong half-sentence and tell the user; never show a wrong number on a card. |
| Brand names mangled ("Claude" as "Cloud") | Patch the caption COPY of the transcript, text only. Card triggers keep the original. |
| Word indices change between runs | "$300" versus "three hundred dollars", "card," versus "card.". Rebuild `expect` guards from the fresh transcript; gen.py compares without case or punctuation. Merge money words in the caption copy. |
| A word with start equal to end | Caption flashes for zero frames. Repair the time in the caption copy from its neighbours. |
| One hyphenated mega-word | Overflows the frame. `captions.py` splits it evenly across its window. |
| Caption unreadable over bright footage | The halo from the style helps; with bright B-roll prefer full-bleed so the caption sits on a dark edge, or darken the footage. |
| Captions too big | 66 px reads right on phones; above about 88 long words fall off-frame. |

## Cards
| Symptom | Rule |
|---|---|
| A card shows only its eyebrow, a "0" or an empty terminal for seconds | Nothing may wait on a late word when the beat starts earlier: graphs and counters start with the beat, a terminal gets a first line at once, a title with a late `on` loses it. Check a frame 0.5 s into every card. |
| Typewriter or counter blank in some renders | Callback-based animation (onUpdate) does not run when a renderer seeks. gen.py uses per-character spans and a snapped innerText tween, both seek-safe. |
| Card is text in a box | Captions carry the words; cards carry the VISUAL: a logo, one word, a graph, an icon. If a card needs a sentence to make sense, redesign it. |
| Boxes that pulse on every word | Never per-word pop-scale. Movement is snappy entrances, self-drawing graphs and the decorative layer. |
| Static composition reads like a slide | Every card is a SEQUENCE of two to four staged movements anchored to different words: entrance, development, payoff. |
| Sparse cards | Cards are contiguous: one always present, each on the word that triggers it. An empty band is the worst second of the reel, especially the first 1.3 s. |
| Key visual enters on the LAST word | Anchor the hero early. If it must come late, fill the front of the beat with secondary visuals, then dim them when the hero pops. |
| Trigger anchors to the wrong occurrence | Triggers search after the previous beat's start; pass `after` in seconds to push it further. |
| Count-up in a beat shorter than 1.2 s | Unreadable. gen.py pops the final number instead. |
| Multi-stage sequence in a short beat | Anchor stages to different words and finish before the beat exits. |
| Angle-bracket tags vanish in a typewriter | Never write typed text into innerHTML. gen.py types into textContent. |
| Logo invisible on the background | Single-colour logos are recoloured to `cards.logo_fill` by `--copy-logos`; check every logo on the background before rendering. |
| Emoji hero icon renders badly | Headless Chrome swaps some emoji. Draw hero icons as inline SVG; small emoji in pills are fine. |
| Bare number stat feels sterile | Make it a curve that draws itself with the number popping at the peak. |
| npx hyperframes "No matching version" | Registry flake. Reuse the cached package: `find ~/.npm/_npx -name hyperframes -type d`. |

## Screen windows
| Symptom | Rule |
|---|---|
| A window shows footage from a minute earlier | Its start sat a few hundredths before a splice (transcriber word starts are early) and mapped to the previous range. screen_windows snaps starts within 0.12 s of a splice to the next range. Still look at one frame per window: the detail score cannot tell your OBS window from the page. |
| Zoomed on empty space | Run `zoom_review.py`; never compose with a flagged stage. The focus is what the viewer must READ: the input with text, the popup, the button, the banner. Never dead center of an empty panel. |
| Left-aligned text cropped at high zoom | Western UI text starts at the left. For address bars, queries, code and sidebars use fx at 0 to 0.06; for headers and URL bars fy near 0. |
| Black bars inside the screen card | Mac screens are about 16:10. Run `cropdetect` on the recording and set `src_crop`, trimming menubar and dock to exactly 16:9. |
| Late windows drift | Never build a companion cut of the screen. Map each window back through the EDL chain, which `screen_windows.py` does. |
| Slow ken-burns zoom | Punch-in model: about 0.5 s full view, a 0.35 s cosine punch, then hold. |

## Popout layout
| Symptom | Rule |
|---|---|
| Halo above the hair | Erode and blur the matte: style keys `matte_erode`, `matte_blur`. |
| Hair duplicated or shifted at the frame edge | Strips were segmented from a previous cut. Always segment the FINAL cut file. |
| Frame edge invisible on white | The drop shadow is mandatory: style `shadow_alpha` above 0. |
| Head barely pops | A pronounced pop reads better, most of the head above the line. Tune `offset_speaker` with `--probe` and `pop_target` in the style. |

## Fluidity
| Symptom | Rule |
|---|---|
| Face video judders slightly, motion feels cheap | The pipeline ran at 25 fps on a 30 fps phone camera: one frame in six was dropped. Everything runs at the camera rate (30 by default, `--fps` / reel.json `fps`). |
| A cut built at 30 fps is a few frames longer than planned | `-t` on a start between two source frames can add a frame. cutjoin forces `-frames:v`; the takes gate catches drift. |
| Takes gate fails at ~0.75 on pieces that sound right | Re-encoded audio sits a fraction of a millisecond off; the gate refines its lag sample by sample. Pieces under 0.4 s are skipped. |
| An SVG line or check never draws | A CSS `stroke-dashoffset` beats the attribute GSAP tweens. Tween the CSS property (`strokeDashoffset`) or reveal with a clip rect, as gen.py does for graphs. |
| Graphics "frozen" warnings on resting cards | Every card breathes (slow push-in) and screen windows creep in during holds, so a resting frame still moves. |
| Hard line between the band and the face | `band.seam` gradient melts the background into the face top. |
| Jump cuts visible on the face | `cut_edl` in reel.json: the face alternates x1.0 / x1.1 at the cuts (one switch per 2 s at most). |

## Look (AISANCE flow art direction)
| Symptom | Rule |
|---|---|
| The reel looks cheap | Causes found on a first real reel: dated hexagon texture, cards too small and lost in empty space, four fonts including pixel fonts, white borders with a solid offset shadow, frozen holds. Use the flow look: aurora + grain, glass panels, Bebas + Montserrat only, big type that fills the band. |
| Captions feel static or choppy | They were drawn at 12 fps with no animation. Draw them at the reel rate with the pop-in (captions.pop) and the title accent words in the accent colour (`--beats`). |
| Cards pop in and out like slides | Every card arrives from a blur and leaves into one, words rise out of a mask, the resting card breathes. Do not add per-card hard cuts or flashes on top. |
| Unsure how a card renders | `hyperframes snapshot` at one time mid-entrance and one at rest before the full render (with GEMINI_API_KEY unset). |

## Sound
| Symptom | Rule |
|---|---|
| "The swap sound comes too often" | A pop on every card plus a whoosh on every screen window gave 16 transition sounds in 90 s. The transition sound plays only on beats marked `"topic": true`, at real subject changes (about one every 10 to 15 s); other cards stay silent. sfx_cues.py warns when two topics are under 6 s apart. |
| Small sounds pile up | Content sounds (item tick, typed line, sentence click, CTA ding) stay; cues closer than 0.12 s keep only the louder one. |

## Delivery
| Symptom | Rule |
|---|---|
| File will not open in QuickTime or Instagram | `+faststart`, which compose.py adds. |
| Music drowns the voice | Voice loudnorm -16, music at 0.06. Measure with `volumedetect`. |
| Sound effects clip | `alimiter` with `level=false`, which sfx_mix.py uses. Verify max_volume at or below -1 dB. |
| Showing a half-baked version | Self-check frames as a contact sheet against the style and the QA checklist before showing anything. |
