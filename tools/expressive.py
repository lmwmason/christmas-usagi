"""Constrained, pitch-synchronous singing that preserves complete source calls.

Unlike the first sampler, this has no fixed octave transposition and no extreme
time stretching. The original glottal pulses and consonants are resynthesized
with Praat's overlap-add manipulation; unvoiced calls remain natural ad-libs.
"""
from pathlib import Path
import hashlib
import json
import re

import librosa
import numpy as np
import parselmouth
from parselmouth.praat import call

from tools.build_preview import ROOT, SR, decode, fade
from tools.source_policy import allowed_source


def load_units(manifest, temp):
    units = []
    for item in json.loads(Path(manifest).read_text()):
        if not allowed_source(item) or not item.get('useInMelody', True) or re.search(r'hachiware|momonga', item.get('description', ''), re.I):
            continue
        path = ROOT / item['file']
        if hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('원본 효과음 파일을 확인하지 못했어요.')
        wave = decode(path, temp / 'source.wav')
        intervals = librosa.effects.split(wave, top_db=27, frame_length=512, hop_length=128)
        if not len(intervals):
            continue
        ranges = []
        # Silence boundaries retain consonants; no arbitrary 1.8-second cut.
        for i, (left, right) in enumerate(intervals):
            if (right-left) / SR >= .16:
                ranges.append((left, right))
            for j in range(i+1, min(len(intervals), i+5)):
                if (intervals[j, 0]-intervals[j-1, 1]) / SR > .3:
                    break
                if .25 < (intervals[j, 1]-left) / SR < 3.3:
                    ranges.append((left, intervals[j, 1]))
        if (intervals[-1, 1]-intervals[0, 0]) / SR < 3.4:
            ranges.append((intervals[0, 0], intervals[-1, 1]))
        seen = set()
        for left, right in ranges:
            left = max(0, int(left)-int(.018*SR))
            right = min(len(wave), int(right)+int(.025*SR))
            key = (round(left/SR, 2), round(right/SR, 2))
            if key in seen:
                continue
            seen.add(key)
            raw = wave[left:right].copy()
            sound = parselmouth.Sound(raw, sampling_frequency=SR)
            pitch = sound.to_pitch_ac(time_step=.01, pitch_floor=100, pitch_ceiling=1400)
            values = pitch.selected_array['frequency']
            voiced = values[values > 0]
            if not len(voiced):
                continue
            midi = librosa.hz_to_midi(voiced)
            units.append(dict(id=item['id'], name=item['name'], group=item['group'], page=item['page'], file=item['file'], sourceStart=left/SR, sourceEnd=right/SR, raw=raw, sound=sound, pitch=pitch, duration=len(raw)/SR, midi=float(np.median(midi)), voiced=float(len(voiced)/max(1,len(values))), spread=float(np.percentile(midi,90)-np.percentile(midi,10)), key=f"{item['id']}:{left}:{right}"))
    if len(units) < 10:
        raise ValueError('노래에 쓸 수 있는 우사기 발성이 부족해요.')
    return units


def synthesize(unit, group, wanted_duration, begin=None):
    factor = float(np.clip(wanted_duration/unit['duration'], .82, 1.22))
    manipulation = call(unit['sound'], 'To Manipulation', .01, 100, 1400)
    tier = call(manipulation, 'Extract pitch tier')
    call(tier, 'Remove points between', 0, unit['duration'])
    voiced = unit['pitch'].selected_array['frequency']
    times = unit['pitch'].xs()
    valid = voiced > 0
    base = unit['midi']
    begin = group[0]['time'] if begin is None else begin
    maximum_shift = 0
    for at in np.arange(.005, unit['duration'], .01):
        output_time = begin + at * factor
        note = min(group, key=lambda n: max(n['time']-output_time, 0, output_time-(n['time']+n['duration'])))
        source_f0 = float(np.interp(at, times[valid], voiced[valid]))
        source_midi = float(librosa.hz_to_midi(source_f0))
        # Keep a little source inflection without adding an octave or allowing
        # a shout to drag the entire musical note around with its original F0.
        target = float(note['midi']) + float(np.clip((source_midi-base)*.15, -.6, .6))
        shift = float(np.clip(target-source_midi, -6, 6))
        maximum_shift = max(maximum_shift, abs(shift))
        call(tier, 'Add point', float(at), float(librosa.midi_to_hz(source_midi+shift)))
    call([tier, manipulation], 'Replace pitch tier')
    duration_tier = call('Create DurationTier', 'length', 0, unit['duration'])
    call(duration_tier, 'Add point', 0, factor)
    call(duration_tier, 'Add point', unit['duration'], factor)
    call([duration_tier, manipulation], 'Replace duration tier')
    rendered = call(manipulation, 'Get resynthesis (overlap-add)').values[0].astype(np.float32)
    return fade(rendered, .006), factor, maximum_shift


