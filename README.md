# aisance-reel

A [Claude Code](https://claude.com/claude-code) skill that turns one raw talking-head clip (plus an optional screen recording) into a finished **9:16 reel or short**: animated cards synced to the spoken words, word-by-word karaoke captions, screen-share windows, sound effects and optional music.

*FR — Un skill Claude Code qui transforme une vidéo face caméra brute en reel 9:16 fini : cartes animées calées sur la voix, sous-titres mot à mot, fenêtres de partage d'écran, bruitages et musique en option.*

| Path | What |
|---|---|
| `.claude/skills/aisance-reel/` | the skill: `SKILL.md`, scripts, styles, references, examples |
| `shared/` | the engine: transcription, take cutting, silences, splice audit, sound effects, fonts, logos, sound bank |
| `reels/<name>/` | one folder per project (footage, cuts, renders), git-ignored |

Looks are style files (`styles/*.json`): `aisance-band`, `aisance-popout`, `aisance-dark-band`, `aisance-light-popout`. Add your own by copying one (`styles/README.md`).

Work is reviewed in [aisance-video-editing](https://github.com/JulienSnsnCode/aisance-video-editing), a local review app: a storyboard gate before the full render, then a frame-precise review of the final video.

## Setup
See `SETUP.md` (ffmpeg, node, one Python virtual environment, the review tool). No API key needed: transcription can run locally with faster-whisper.

## Usage
Open Claude Code at the repo root and say "make a reel from <clip>". To use it from any folder, symlink `.claude/skills/aisance-reel` into `~/.claude/skills/` (the skill finds `shared/` three levels above itself, so keep it inside this repo and link, do not copy).

## Notes
- No music is bundled. Only use tracks you have the right to use.
- Fonts are SIL OFL (`shared/assets/fonts/README.md`). Brand logos in `shared/assets/logos/` belong to their owners.
- Licence: MIT.
