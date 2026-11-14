"""CPU-only RMVPE ONNX singing pitch analysis, bounded to 5-second windows.

Pre/postprocessing follows the published RVC RMVPE interface (MIT).
Network weights are downloaded separately and SHA-256 checked. No Torch/pickle.
"""
from pathlib import Path
from urllib.request import Request, urlopen
import hashlib
import math

import librosa
import numpy as np
import onnxruntime as ort
from scipy.ndimage import median_filter

# The publisher's content checksum pins the weights even if its branch changes.
MODEL_URL = 'https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/rmvpe.onnx'
MODEL_SHA256 = '5370e71ac80af8b4b7c793d27efd51fd8bf962de3a7ede0766dac0befa3660fd'


def ensure_pitch_model(cache, notify=None):
    path = Path(cache) / 'rmvpe.onnx'
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        temp = path.with_suffix('.partial')
        try:
            with urlopen(Request(MODEL_URL, headers={'User-Agent': 'UsagiChristmas/1.0'}), timeout=45) as response, temp.open('wb') as out:
                while chunk := response.read(1024*1024):
                    if notify: notify('AI 노래 음정 모델을 준비하고 있어요')
                    out.write(chunk)
                    if out.tell() > 400_000_000:
                        raise ValueError('AI 음정 모델 크기를 확인하지 못했어요.')
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)
    with path.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    if digest != MODEL_SHA256:
        path.unlink(missing_ok=True)
        raise ValueError('AI 음정 모델 검증에 실패했어요. 다시 시도해 주세요.')
    return path


def decode_salience(salience, threshold=.03):
    """Local weighted cents around the strongest of 360 20-cent bins."""
    maxima = np.argmax(salience, axis=1)
    indices = maxima[:, None] + np.arange(-4, 5)
    valid = (indices >= 0) & (indices < 360)
    safe = np.clip(indices, 0, 359)
    weights = np.take_along_axis(salience, safe, axis=1) * valid
    cents = (weights * (20*safe + 1997.3794084376191)).sum(axis=1) / np.maximum(weights.sum(axis=1), 1e-9)
    f0 = 10 * 2**(cents / 1200)
    f0[salience.max(axis=1) <= threshold] = 0
    return f0


def extract_neural_notes(wave, sr, model, notify=None, allow_empty=False):
    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.enable_mem_pattern = False
    session = ort.InferenceSession(str(model), sess_options=options, providers=['CPUExecutionProvider'])
    audio = librosa.resample(wave, orig_sr=sr, target_sr=16000)
    basis = librosa.filters.mel(sr=16000, n_fft=1024, n_mels=128, fmin=30, fmax=8000, htk=True)
    count = len(audio)//160 + 1
    f0 = np.zeros(count, np.float32)
    rms = np.zeros(count, np.float32)
    # Overlap protects CNN/GRU context at seams; only the center is retained.
    for first in range(0, count, 500):
        end = min(count, first+500)
        left, right = max(0,first-50), min(count,end+50)
        segment = audio[left*160:min(len(audio),right*160)]
        if len(segment) < 1024:
            segment = np.pad(segment, (0,1024-len(segment)))
        magnitude = np.abs(librosa.stft(segment, n_fft=1024, hop_length=160, window='hann', center=True, pad_mode='reflect'))
        mel = np.log(np.maximum(basis @ magnitude, 1e-5)).astype(np.float32)
        frames = mel.shape[1]
        mel = np.pad(mel, ((0,0),(0,(-frames)%32)))[None]
        salience = session.run(None, {session.get_inputs()[0].name:mel})[0][0,:frames]
        pitch = decode_salience(salience)
        energy = librosa.feature.rms(y=segment, frame_length=1024, hop_length=160, pad_mode='reflect')[0]
        offset = first-left
        f0[first:end] = pitch[offset:offset+end-first]
        rms[first:end] = energy[offset:offset+end-first]
        if notify: notify(end/count, 'AI로 노래의 음정과 길이를 분석하고 있어요')
    voiced = (f0 > 0) & (rms > .009)
    midi = median_filter(np.round(librosa.hz_to_midi(np.maximum(f0, 1))).astype(int), size=5)
    notes=[]
    index=0
    while index<count:
        if not voiced[index]:
            index+=1
            continue
        end=index+1
        while end<count and voiced[end] and midi[end]==midi[index]:end+=1
        duration=(end-index)*.01
        if duration>=.06:
            parts=max(1,math.ceil(duration/.7))
            for part in range(parts):
                time=index*.01+part*duration/parts
                length=min(duration/parts,len(wave)/sr-time)
                if length>0:notes.append(dict(time=time,duration=length,midi=int(midi[index])))
        index=end
    if not notes and not allow_empty:
        raise ValueError('AI가 부를 멜로디를 찾지 못했어요. 다른 구간을 골라주세요.')
    return notes
