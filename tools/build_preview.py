# /// script
# requires-python = ">=3.11"
# dependencies = ["librosa>=0.11", "soundfile>=0.13", "numpy>=2", "scipy>=1.14", "praat-parselmouth>=0.4.7"]
# ///
"""Melody utilities and expressive singing CLI. Run: uv run tools/build_preview.py --help.

This is sample-based resynthesis, NOT a trained Usagi model. It estimates a
melody from a mixed recording, so notes can be wrong. No original song vocals
are copied into the resulting performance. FFmpeg is required for decoding; Praat handles pitch and duration.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf
from scipy.ndimage import median_filter

SR = 22050
ROOT = Path(__file__).resolve().parents[1]


def run(*args: str) -> None:
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL)


def decode(source: Path, destination: Path, start: float = 0, duration: float | None = None) -> np.ndarray:
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(start), "-i", str(source)]
    if duration is not None:
        args.extend(["-t", str(duration)])
    run(*args, "-ac", "1", "-ar", str(SR), str(destination))
    y, _ = sf.read(destination, dtype="float32")
    if len(y) < SR // 5:
        raise ValueError("Audio is too short to analyze")
    return y


def fade(y: np.ndarray, seconds: float = 0.008) -> np.ndarray:
    y = y.copy()
    n = min(int(seconds * SR), len(y) // 3)
    if n:
        ramp = np.linspace(0, 1, n)
        y[:n] *= ramp
        y[-n:] *= ramp[::-1]
    return y


def extract_notes(y: np.ndarray, notify=None, allow_empty=False, _segment=False) -> list[dict]:
    if len(y) < 2048:
        if allow_empty: return []
        raise ValueError("보컬을 분석할 수 있는 길이가 부족해요.")
    if len(y) > 30 * SR and not _segment:
        notes = []
        for start in range(0, len(y), 30 * SR):
            left = max(0, start - int(.2 * SR))
            segment = extract_notes(y[left:start + 30 * SR], allow_empty=True, _segment=True)
            for note in segment:
                begin=max(note['time']+left/SR,start/SR)
                end=min(note['time']+note['duration']+left/SR,(start+30*SR)/SR,len(y)/SR)
                if end>begin:
                    notes.append(dict(note,time=begin,duration=end-begin))
            if notify: notify(min(1, (start + 30 * SR) / len(y)), "멜로디를 분석하고 있어요")
        if not notes and not allow_empty:
            raise ValueError("보컬 멜로디를 충분히 찾지 못했어요. 다른 구간을 골라주세요.")
        return notes
    hop = 256
    print("Estimating the song melody (CPU)…", flush=True)
    # pYIN's voicing probabilities help avoid resynthesizing accompaniment.
    f0, voiced, confidence = librosa.pyin(y, sr=SR, fmin=librosa.note_to_hz("G3"), fmax=librosa.note_to_hz("C6"), frame_length=2048, hop_length=hop)
    midi = np.round(librosa.hz_to_midi(np.nan_to_num(f0, nan=440.0))).astype(int)
    midi = median_filter(midi, size=5)
    # Mixed recordings often produce half-frequency errors under the singer.
    # Keep this small prototype's melody in one consistent vocal register.
    midi = np.where(midi < 60, midi + 12, midi)
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=hop)[0]
    valid = voiced & (confidence > 0.04) & (rms[:len(midi)] > 0.012)
    notes = []
    index = 0
    while index < len(midi):
        if not valid[index]:
            index += 1
            continue
        end = index + 1
        while end < len(midi) and valid[end] and midi[end] == midi[index]:
            end += 1
        duration = (end - index) * hop / SR
        if duration >= 0.07:
            # Long held tones get a second syllable rather than stretched noise.
            parts = max(1, math.ceil(duration / 0.7))
            for part in range(parts):
                notes.append({"time": index * hop / SR + part * duration / parts, "duration": duration / parts, "midi": int(midi[index])})
        index = end
    if not notes and not allow_empty:
        raise ValueError("Too little confident melody detected; choose another song section")
    return notes


def main() -> None:
    from tools.rap_singing import render_preview
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-manifest", type=Path, default=ROOT / "assets/sources/manifest.json")
    parser.add_argument("--song", required=True, type=Path)
    parser.add_argument("--start", type=float, default=46)
    parser.add_argument("--duration", type=float, default=24)
    parser.add_argument("--output", type=Path, default=ROOT / "assets")
    parser.add_argument("--melody", type=Path, help="An isolated vocal excerpt aligned to the requested performance")
    parser.add_argument("--keep-duration", action="store_true")
    args = parser.parse_args()
    if not 0 < args.duration <= 600 or args.start < 0:
        parser.error("Choose a positive excerpt of up to 600 seconds")
    render_preview(song=args.song, output=args.output, start=args.start, duration=args.duration, sample_manifest=args.sample_manifest, melody=args.melody, keep_duration=args.keep_duration)


if __name__ == "__main__":
    main()
