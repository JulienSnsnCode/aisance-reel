# Setup

One-time, macOS (Linux notes at the end), for the `aisance-reel` skill (9:16 reels and shorts). The skill uses the
engine in `shared/` and one Python environment.
Nothing here needs an API key.

## 1. System tools
```
brew install ffmpeg node python gh
```
ffmpeg/ffprobe run the whole pipeline; node provides `npx` for the card renderer; python 3.10+.

## 2. Python packages (virtual environment)
Homebrew Python refuses global pip installs, so the repo has its own environment (the name is historical):
```
python3 -m venv ~/.venvs/aisance-reel
~/.venvs/aisance-reel/bin/pip install -r shared/requirements.txt
```
Run every script with `~/.venvs/aisance-reel/bin/python`. Pillow bakes captions and masks, requests is
used only by the API transcription backends, faster-whisper is the free local transcriber.

## 3. Transcription, pick one
- Local, free, offline: already in the environment → `--backend local` (first run downloads the model).
- Groq API, near free, fast: export `GROQ_API_KEY` in your shell → `--backend groq`.
- ElevenLabs Scribe, paid, tightest word timing: export `ELEVENLABS_API_KEY` → `--backend elevenlabs`.

Keys live in your shell profile (`~/.zshrc`), never in a file inside a project or this skill.

## 4. Card renderer
`npx --yes hyperframes@0.8.91 render` downloads the pinned package on first use. Bump the version
deliberately after checking its changelog. Cards load GSAP from a pinned CDN URL at render time.
hyperframes sends anonymous usage telemetry by default; the pipeline sets `HYPERFRAMES_NO_TELEMETRY=1`,
`DO_NOT_TRACK=1` and `HYPERFRAMES_NO_UPDATE_CHECK=1` on every render to switch that off.

## 5. Popout layout only (reels)
```
~/.venvs/aisance-reel/bin/pip install -r shared/requirements-popout.txt
```
Same environment as above. The u2net model (about 170 MB) downloads once to `~/.u2net`; frames never leave the machine.

## 6. Optional
- `brew install yt-dlp` to study a reference reel from a link, only when the user asks for it.
- Sound effects: bring your own files; `sfx_mix.py` mixes them.
- Music: bring a licensed track; nothing is bundled.

## 7. Review tool (storyboard and final review)
The review app is its own repo, [aisance-video-editing](https://github.com/JulienSnsnCode/aisance-video-editing).
Node 22 or later. Clone it anywhere, the skill only calls the `aisance-video-editing` command:
```
git clone https://github.com/JulienSnsnCode/aisance-video-editing ~/aisance-video-editing
cd ~/aisance-video-editing && npm ci && npm run build && npm link
```
That puts `aisance-video-editing` on the PATH. It serves the project folder on 127.0.0.1 only, and loads GSAP for the
cards preview from the same pinned CDN as the render.

## Check
```
ffmpeg -version | head -1; node -v; ~/.venvs/aisance-reel/bin/python -c "import PIL, requests, faster_whisper; print('python ok')"; aisance-video-editing --help | head -1
```

## Linux
`sudo apt install ffmpeg nodejs npm python3 python3-pip`; everything else is identical.
