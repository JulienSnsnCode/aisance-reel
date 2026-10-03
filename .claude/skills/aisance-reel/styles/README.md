# Styles

A style is a JSON file in this folder. Scripts take `--style <name>` (file name without `.json`)
or `--style <path>`; `reel.json` has a `"style"` key. Styles hold colours, geometry and caption
settings only, never commands or code.

Built in: `aisance-band` and `aisance-popout` (the AISANCE art direction:
motion section), plus the simpler `aisance-dark-band` and `aisance-light-popout`. Add a style by copying the
closest one and editing the values.

## Schema
| key | meaning |
|---|---|
| `name` | display name |
| `layout` | `band` (speaker fills the lower part, cards on the top band) or `popout` (cards full-frame, speaker in a floating frame with a head cutout) |
| `colors.bg` | page / band background |
| `colors.text`, `colors.muted` | primary and secondary text |
| `colors.accent`, `colors.accent_bright` | THE one accent of the reel and its highlight |
| `colors.negative`, `colors.neutral` | loss / no / expensive, and the neutral competitor |
| `colors.panel`, `colors.panel_border` | card surfaces (rgba allowed) |
| `accents` | optional table subject → hex; `--accent <subject>` (gen.py) and `"accent"` (reel.json) pick one |
| `font.family`, `font.file`, `font.weight` | fallback card font; `font.file` is the caption font (ttf/otf/woff2, relative to `<repo>/shared/`, e.g. `assets/fonts/x.ttf`) |
| `fonts.display/body/term/mono` | optional per-role fonts: `family`, `file` (copied next to the cards page), `weight`, `pixel: true` (no antialiasing, for pixel fonts). display = titles and numbers, body = labels and chat, term = terminal lines, mono = window title bars |
| `cards.band_h` | height of the decorated area (864 for band, 1920 for popout) |
| `cards.content_h` | height available to card content (keep it above the captions) |
| `cards.safe_top` | Instagram top zone: card content and the screen slot start below this y (170) |
| `cards.decor` | grid, glow, particles and streaks on or off |
| `cards.grid_alpha`, `cards.glow_alpha` | decor intensity |
| `cards.logo_fill` | colour applied to single-colour logos by `gen.py --copy-logos` |
| `cards.bg_image`, `cards.bg_image_opacity`, `cards.vignette` | background texture file (inside `<repo>/shared/assets/`), its opacity, radial vignette |
| `cards.tone` | `dynamique` (overshoot) or `calme` (smooth, no overshoot, texture breathes) |
| `cards.look` | `"flow"`: aurora background (`cards.aurora` light strength, 0.42), film grain (`cards.grain`, 0.16), dotted grid, glass panels, pill eyebrows, a bottom fade into `colors.bg`. `colors.accent2` sets the second aurora light (default: a deeper shade of the accent). Without it: the classic look below |
| `cards.border_w`, `cards.radius`, `cards.offset_shadow` | card chrome: border width in `colors.panel_border`, corner radius, solid offset shadow in the accent (0 = none) |
| `cards.window` | `retro` for pixel-square title bars (one filled in the accent) |
| `cards.kw_size`, `cards.big_size` | title and big-number font sizes |
| `colors.line` | secondary borders (bar tracks) |
| `cards.term_bg`, `cards.term_bar` | optional terminal / chat surfaces (defaults derive from bg) |
| `captions.size`, `captions.y`, `captions.max_width` | karaoke word size, absolute y, max width before shrinking |
| `captions.fill`, `captions.halo`, `captions.blur` | word colour, halo colour (RGBA lists), halo blur |
| `captions.uppercase`, `captions.strip_punct` | text transforms |
| `band.face_y`, `band.face_h`, `band.crop_y_default` | band layout: where the face crop lands and its height |
| `popout.*` | popout layout geometry, see `references/popout.md` |
| `fonts.<role>.weight_range` | CSS weight range of a variable font file (default `"100 900"`) |
| `captions.font`, `captions.pop`, `captions.accent_words` | caption font file (else `font.file`); word pop-in (default true); accent-coloured title accent words |
| `band.seam` | band layout: height of the gradient that melts the background into the top of the face (0 = hard edge) |
| `screen.*` | screen slot rectangle, radius, soft shadow (`shadow_*`) or solid accent shadow (`offset_shadow`), `border_w`/`border_color` |
| `popout.border_w`, `popout.border_color`, `popout.offset_shadow` | speaker frame border and solid accent shadow (the head still pops over the border) |
| `music.vol`, `music.start`, `music.duck` | music level, start second in the track, dip under the voice (sidechain) |

## Checking a new style
```
cd /tmp && mkdir -p styletest && cd styletest
python <skill>/scripts/gen.py <skill>/examples/sample-transcript.json <skill>/examples/beats.example.json --style <name> --out index.html --copy-logos
python <skill>/scripts/captions.py <skill>/examples/sample-transcript.json capt --style <name>
npx --yes hyperframes@0.8.91 render . -o cards.mp4     # then extract frames and look
```
Check contrast of text on `bg`, of captions over the footage they will sit on, and that every
logo is visible on the background.
