"""Beat timestamps shared by the generated audio and the browser dancer."""
import numpy as np
import librosa


def measure_beats(audio, sample_rate):
    mono = np.mean(audio, axis=1) if audio.ndim == 2 else audio
    if sample_rate != 22050:
        mono = librosa.resample(mono, orig_sr=sample_rate, target_sr=22050)
    tempo, frames = librosa.beat.beat_track(y=mono, sr=22050, hop_length=512, trim=False)
    bpm = float(np.ravel(tempo)[0])
    beats = librosa.frames_to_time(frames, sr=22050, hop_length=512)
    return {"bpm": round(bpm, 3), "beats": [round(float(at), 5) for at in beats if at < len(mono) / 22050]}
