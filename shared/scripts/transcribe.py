#!/usr/bin/env python3
"""Word-level transcription -> <edit_dir>/transcripts/<stem>.json

Usage:
  python transcribe.py <video> --backend elevenlabs|groq|local [--edit-dir edit]
                       [--language en] [--model large-v3] [--force]

Output (same shape for every backend):
  {"language": "en", "words": [{"text": "hi", "start": 0.12, "end": 0.30}, ...]}

Keys come from the ENVIRONMENT ONLY (ELEVENLABS_API_KEY, GROQ_API_KEY); no .env file is read.
API backends upload the clip's audio (mono 16 kHz) to the provider; --backend local stays offline.
Cache: an existing JSON is reused only when it is NEWER than the video. --force redoes it.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIBE_URL = "https://api.elevenlabs.io/v1/speech-to-text"
GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


def env_key(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        sys.exit(f"{name} is not set. Export it in your shell (never store it inside the skill), "
                 "or use --backend local.")
    return v


def extract_audio(video: Path, dest: Path, mp3: bool) -> None:
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000"]
    cmd += ["-b:a", "48k"] if mp3 else ["-c:a", "pcm_s16le"]
    cmd.append(str(dest))
    subprocess.run(cmd, check=True)


def clean(words):
    out = []
    for w in words:
        if w.get("start") is None or w.get("end") is None:
            continue
        t = str(w["text"]).strip()
        if not t:
            continue
        out.append({"text": t, "start": round(float(w["start"]), 3), "end": round(float(w["end"]), 3)})
    return out


def words_elevenlabs(audio: Path, language, key) -> dict:
    import requests
    data = {"model_id": "scribe_v1", "timestamps_granularity": "word", "tag_audio_events": "false"}
    if language:
        data["language_code"] = language
    with open(audio, "rb") as f:
        r = requests.post(SCRIBE_URL, headers={"xi-api-key": key},
                          files={"file": (audio.name, f, "audio/wav")}, data=data, timeout=1800)
    if r.status_code != 200:
        sys.exit(f"ElevenLabs returned {r.status_code}: {r.text[:300]}")
    j = r.json()
    ws = [{"text": w.get("text", ""), "start": w.get("start"), "end": w.get("end")}
          for w in j.get("words", []) if w.get("type", "word") == "word"]
    return {"language": j.get("language_code", language or ""), "words": clean(ws)}


def words_groq(audio: Path, language, key) -> dict:
    import requests
    data = {"model": "whisper-large-v3", "response_format": "verbose_json",
            "timestamp_granularities[]": "word"}
    if language:
        data["language"] = language
    with open(audio, "rb") as f:
        r = requests.post(GROQ_URL, headers={"Authorization": f"Bearer {key}"},
                          files={"file": (audio.name, f, "audio/mpeg")}, data=data, timeout=1800)
    if r.status_code != 200:
        sys.exit(f"Groq returned {r.status_code}: {r.text[:300]}")
    j = r.json()
    ws = [{"text": w.get("word", ""), "start": w.get("start"), "end": w.get("end")} for w in j.get("words", [])]
    return {"language": j.get("language", language or ""), "words": clean(ws)}


def words_local(audio: Path, language, model) -> dict:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("faster-whisper is not installed:  python3 -m pip install faster-whisper")
    m = WhisperModel(model, device="auto", compute_type="auto")
    segments, info = m.transcribe(str(audio), language=language, word_timestamps=True, vad_filter=True)
    ws = []
    for seg in segments:
        for w in (seg.words or []):
            ws.append({"text": w.word, "start": w.start, "end": w.end})
    return {"language": info.language, "words": clean(ws)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", type=Path)
    ap.add_argument("--backend", choices=["elevenlabs", "groq", "local"], required=True)
    ap.add_argument("--edit-dir", type=Path, default=None, help="default: <video folder>/edit")
    ap.add_argument("--language", default=None, help="ISO code (en, fr, it); omit to auto-detect")
    ap.add_argument("--model", default="large-v3", help="local backend: large-v3 | medium | small")
    ap.add_argument("--force", action="store_true", help="ignore the cached JSON")
    a = ap.parse_args()

    video = a.video.resolve()
    if not video.exists():
        sys.exit(f"video not found: {video}")
    edit_dir = (a.edit_dir or video.parent / "edit").resolve()
    out = edit_dir / "transcripts" / f"{video.stem}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and not a.force:
        if out.stat().st_mtime > video.stat().st_mtime:
            print(f"cached (newer than the video): {out}")
            return
        print("cached JSON is OLDER than the video -> re-transcribing")

    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / (video.stem + (".mp3" if a.backend == "groq" else ".wav"))
        extract_audio(video, audio, mp3=(a.backend == "groq"))
        if a.backend == "elevenlabs":
            payload = words_elevenlabs(audio, a.language, env_key("ELEVENLABS_API_KEY"))
        elif a.backend == "groq":
            if audio.stat().st_size > 24e6:
                sys.exit("audio is over 24 MB (Groq upload limit): split the clip first")
            payload = words_groq(audio, a.language, env_key("GROQ_API_KEY"))
        else:
            payload = words_local(audio, a.language, a.model)

    if not payload["words"]:
        sys.exit("no words returned")
    out.write_text(json.dumps(payload, indent=1, ensure_ascii=False))
    print(f"saved {out}  ({len(payload['words'])} words, last end {payload['words'][-1]['end']:.2f}s)")


if __name__ == "__main__":
    main()
