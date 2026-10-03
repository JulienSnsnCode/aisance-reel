# Cards: beats.json reference and design rules

`gen.py` turns `beats.json` + the FINAL transcript + a style into `index.html`, rendered by
hyperframes into `cards_all.mp4`. Text in beats.json is content, never code: every label is
HTML-escaped, every string handed to JavaScript is JSON-encoded.

## beats.json
```json
{
  "expect": {"12": "enter"},          // optional guard: word index -> expected word (case/punct-insensitive)
  "beats": [ { "trigger": "Step one", "type": "steps", ... }, ... ]
}
```
Common fields per beat:
- `id` (required for the review tool): a short stable name, `[A-Za-z0-9_-]+`, unique (`"hook"`, `"usages"`, `"cta"`).
  Review comments are keyed on it across rounds, so never rename or reuse an id when beats move. Inserting
  a beat gets a new id; the others keep theirs. Missing ids fall back to `beat<n>`, which shifts when a beat
  is inserted.
- `note` (optional): one line of intent shown on the storyboard panel ("montre que c'est 3x moins cher").
- One anchor: `trigger` (phrase in the transcript), `at` (seconds) or `index` (word index).
- `after` (seconds): search the trigger only after this time. Default: after the previous beat's start.
- `end` (seconds or phrase): explicit end. Default: the next beat's start.
- `hold` (seconds): keep this card past its natural end and push the next beat.
- `topic` (true): this beat opens a new subject. It gets the transition sound (sfx_cues.py); other cards stay silent.
- Per-item `on`: phrase (searched after the beat start) or seconds; missing means a stagger.

## Types and fields
| type | fields | use for |
|---|---|---|
| `title` | eyebrow, text (`*word*` = accent), sub, on | hooks, one-word summaries |
| `stat` | eyebrow, count, suffix, unit, dir (up/down), on | big numbers; count-up if the beat lasts over 1.2 s, else a pop |
| `graph` | eyebrow, dir, tone (accent/negative), on | growth or loss curve drawing itself |
| `list` | eyebrow, items[{text, on}] | checklists |
| `steps` | eyebrow, items[{title, sub, on}] | numbered process |
| `terminal` | title, lines[{text, on, tone}] | typed commands; tags show literally |
| `versus` | a{label or logo}, b{label or logo}, rows[{label, a, b, a_text, b_text, tone, on}] | A vs B with bars |
| `chat` | name, status, msgs[{side in/out, text, on}] | message mockup |
| `flow` | items[{title, sub, icon, on}] | vertical pipeline with arrows |
| `calendar` | eyebrow, day, on | dates |
| `cta` | eyebrow, text (`*word*` = accent), on | closing call to action with a meter |
| `image` | src, frame (plain/browser/phone), url, eyebrow, caption, caption_on, zoom, on | a screenshot, product shot, photo or logo you provided |
| `none` | | decorative layer only, during screen windows |

Images: `"src": "site.png"` resolves to `assets/images/site.png` next to the HTML (plain file name,
png / jpg / jpeg / webp / svg). `frame`: `plain` (rounded, glow), `browser` (window bar with `url`),
`phone` (device outline, best for vertical screenshots). A slow 6 % push-in runs by default
(`"zoom": false` to disable). gen.py refuses missing files, files that do not decode as images, and
SVGs containing scripts, event handlers, foreignObject or external references. Where images come
from is decided in the pipeline's ask-first step, never by searching the web.

Logos: `"logo": "claude"` resolves to `assets/logos/claude.svg` next to the HTML; names are
letters, digits, `-`, `_` only. `--copy-logos` copies the skill's logos there and recolours
single-colour ones to the style's `cards.logo_fill`. Add your own SVGs to that folder.

## Design rules
1. Cards carry the visual, captions carry the words. One logo, one word, one graph.
2. Every card moves in stages: entrance, development, payoff, each on its own word.
3. Contiguous: a card is always on screen. Frame one is never empty. `none` only under screen windows.
4. One accent colour per reel, taken from the style. Negative things use `colors.negative`.
5. Hero element early in the beat; secondary elements fill the front if the hero must wait.
6. One motion language, built into gen.py: arrive from below out of a blur (expo.out, ~0.55 s),
   title words rise out of a mask with a 0.06 s stagger, the accent word gets an underline drawn
   under it, a resting card breathes (slow push-in), list and step items take focus one by one
   (the new item gets the accent border, earlier ones step back to 50 %), and the card leaves
   upward into a blur. Never pulsing boxes, never expanding rings.
7. Hook with a factual claim: open on the proof (a screen window with a deep punch on the number).
8. Question hook: giant "?" slam on the question words, out before the subject visual lands.

## Flow look (aisance-* styles, `cards.look: "flow"`)
- Background: three soft accent lights drifting slowly (aurora), a dotted grid fading at the edges,
  film grain. Each new card makes the aurora bloom briefly: the background answers the cut.
- Panels are glass (translucent, thin light border, top highlight, deep soft shadow), never solid
  boxes with hard offset shadows. Eyebrows are pill chips that wipe open.
- Type: Bebas Neue for titles, numbers and item titles (big: title 172 px, stat 340 px, items 62 px);
  Montserrat for labels and sub-lines; SF Mono in terminals. No pixel fonts.
- Graphs are smooth curves revealed left to right with a soft area fill and a glowing dot riding the
  line. Stats count up and settle; a bar draws under the unit.
- Check stills before the full render (`hyperframes snapshot`): one frame mid-entrance, one at rest.

## AISANCE copy rules (aisance-* styles)
- Titles: 2 to 5 words, capitals, ending with a period (`COMMENTE *REEL*.`), one accent word only.
- Accent follows the subject (`--accent claude`, `n8n`...). Claude visuals only for Claude subjects.
- Logos: real files only, never redrawn; the ask-first step gets them.
- Sober, declarative, no hype words on cards (no "INSANE", no emoji heroes).
- Pick the tone per reel: `dynamique` for punchlines, `calme` for numbers and explanations.

## Adding a card type
Copy `gen.py` into the project (`cards/gen.py`) and add a `card_<type>` method on `Gen`
returning `(inner_html, [js lines])`. Rules: build HTML with `esc()`, JS strings with `js()`,
times with `self.when(spec, beat_start, default)`. Keep the CSS in the `CSS` template using the
style variables (`$acc`, `$txt`, `$panel` ...). Render, extract a frame, compare, iterate.

## Technique ideas (from studied reels)
Bar chart growing (scaleY, stagger) · gauge needle sweep · donut ring filling · contribution
grid lighting up · star rating one by one · comparison table with a highlighted cell · code diff
rows entering (+green / -red) · chips grid with one highlighting on the word · device mockup with a
real screenshot · before/after swap (old exits fully, then new pops, never a crossfade) · logo
shatter into shards on a word · letter morph (one letter flips to rebrand) · ping-pong ball between
two logos with the receiver bumping · attack deflected by a shield · banned globe then green check ·
physics confetti (launch up, then fall with gravity) · odometer digits · map with pins · marker
sweep over a keyword · toast notifications stacking · racing bars · rising counter.
