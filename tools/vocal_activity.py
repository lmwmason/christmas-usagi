"""Detect singing activity independently from successful pitch tracking.

Energy is measured on the separated vocal, compared with the original mix.
Coverage is an acoustic check against this estimate, not a human transcription.
"""
import numpy as np
import librosa
from scipy.ndimage import binary_closing, binary_opening, binary_dilation

HOP = 256
FRAME = 1024


def regions_from_mask(mask, sr):
    edges = np.diff(np.r_[False, mask, False].astype(np.int8))
    return [(int(a)*HOP/sr, int(b)*HOP/sr) for a,b in zip(np.flatnonzero(edges==1),np.flatnonzero(edges==-1))]


def envelope(wave):
    return librosa.feature.rms(y=wave, frame_length=FRAME, hop_length=HOP)[0]


def detect_vocals(lead, original, sr):
    voice = envelope(lead)
    music = envelope(original)
    n = min(len(voice),len(music))
    voice, music = voice[:n], music[:n]
    floor = float(np.clip(np.percentile(voice,15)*2.8,.009,.03))
    active = (voice > floor) & (voice / np.maximum(music,.005) > .12)
    active = binary_opening(active,structure=np.ones(max(1,round(.035*sr/HOP))))
    active = binary_closing(active,structure=np.ones(max(1,round(.12*sr/HOP))))
    active = binary_dilation(active,structure=np.ones(max(1,round(.05*sr/HOP))))
    regions = [(a,min(b,len(lead)/sr)) for a,b in regions_from_mask(active,sr) if b-a>=.10]
    # Return the exact mask corresponding to the kept regions.
    kept = np.zeros(n,dtype=bool)
    for a,b in regions:kept[round(a*sr/HOP):round(b*sr/HOP)]=True
    return kept,regions,dict(method='separated-vocal RMS and vocal/mix ratio',rmsThreshold=floor,relativeThreshold=.12,frameSeconds=HOP/sr)


def coverage(wave, reference, sr):
    energy = envelope(wave)
    generated = energy > .004
    generated = binary_closing(generated,structure=np.ones(max(1,round(.045*sr/HOP))))
    # Small consonant closures and edit crossfades are normal articulation.
    generated = binary_dilation(generated,structure=np.ones(max(1,round(.05*sr/HOP))))
    n=min(len(reference),len(generated))
    missing=reference[:n]&~generated[:n]
    total=int(np.sum(reference[:n]));covered=total-int(np.sum(missing))
    gaps=regions_from_mask(missing,sr)
    return dict(referenceSeconds=total*HOP/sr,coveredSeconds=covered*HOP/sr,ratio=covered/max(1,total),maxGapSeconds=max((b-a for a,b in gaps),default=0),articulationToleranceMs=50),gaps
