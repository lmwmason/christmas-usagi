# /// script
# requires-python = ">=3.11"
# dependencies = ["onnxruntime>=1.20", "numpy>=2", "scipy>=1.14", "soundfile>=0.13"]
# ///
"""Extract the matching instrumental with UVR MDX, then mix a static preview.

Model: https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/UVR-MDX-NET-Inst_HQ_3.onnx
Model parameters: https://github.com/Anjok07/ultimatevocalremovergui/blob/master/models/MDX_Net_Models/model_data/model_data.json
The model is an external development dependency, never part of the website.
"""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import tempfile
import os

import numpy as np
import onnxruntime as ort
from scipy import signal
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
SR = 44100
HOP = 1024


def run(*args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL)


def read_audio(path, output, start=0, duration=None):
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(start), "-i", str(path)]
    if duration is not None:
        args += ["-t", str(duration)]
    run(*args, "-ac", "2", "-ar", str(SR), str(output))
    audio, _ = sf.read(output, dtype="float32", always_2d=True)
    return audio


def separate(audio, model, config, notify=None):
    with model.open("rb") as stream:
        stream.seek(-10000 * 1024, 2)
        fingerprint = hashlib.md5(stream.read()).hexdigest()
    parameters = json.loads(config.read_text()).get(fingerprint)
    if not parameters or parameters.get("primary_stem") != "Instrumental":
        raise ValueError(f"Model not recognized as an instrumental model: {fingerprint}")
    n_fft = parameters["mdx_n_fft_scale_set"]
    dim_f = parameters["mdx_dim_f_set"]
    dim_t = 2 ** parameters["mdx_dim_t_set"]
    options = ort.SessionOptions()
    options.intra_op_num_threads = min(4,max(1,int(os.environ.get('USAGI_CPU_THREADS','4'))))
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(model), sess_options=options, providers=["CPUExecutionProvider"])
    name = session.get_inputs()[0].name
    chunk_size = HOP * (dim_t - 1)
    trim = n_fft // 2
    valid = chunk_size - 2 * trim
    padded_length = int(np.ceil(len(audio) / valid)) * valid
    wave = np.pad(audio.T, ((0, 0), (trim, padded_length - len(audio) + trim)))
    window = signal.windows.hann(n_fft, sym=False)
    scale = float(window.sum())
    chunks = []
    for start in range(0, padded_length, valid):
        chunk = wave[:, start:start + chunk_size]
        _, _, spec = signal.stft(chunk, fs=SR, window=window, nperseg=n_fft, noverlap=n_fft-HOP, boundary="zeros", padded=False, axis=-1)
        spec *= scale
        tensor = np.stack([spec[0].real, spec[0].imag, spec[1].real, spec[1].imag])[None, :, :dim_f].astype(np.float32)
        tensor[:, :, :3] = 0
        prediction = session.run(None, {name: tensor})[0][0]
        complex_spec = np.stack([prediction[0] + 1j * prediction[1], prediction[2] + 1j * prediction[3]])
        complex_spec = np.pad(complex_spec, ((0, 0), (0, n_fft // 2 + 1 - dim_f), (0, 0))) / scale
        _, result = signal.istft(complex_spec, fs=SR, window=window, nperseg=n_fft, noverlap=n_fft-HOP, boundary=True, time_axis=-1, freq_axis=-2)
        chunks.append(result[:, trim:trim + valid].T)
        if notify: notify(min(1, (start + valid) / len(audio)), "원곡에서 반주와 보컬을 분리하고 있어요")
        print(f"Instrumental separation {min(start + valid, len(audio)) / SR:.1f}/{len(audio) / SR:.1f}s", flush=True)
    backing = np.concatenate(chunks)[:len(audio)] * parameters.get("compensate", 1)
    if backing.shape != audio.shape or not np.isfinite(backing).all():
        raise ValueError("Invalid stem output")
    return backing.astype(np.float32), fingerprint


def rms(audio):
    return float(np.sqrt(np.mean(audio ** 2)))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--song", required=True, type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--model-config", type=Path)
    parser.add_argument("--backing", type=Path, help="Already separated, aligned instrumental WAV")
    parser.add_argument("--output", type=Path, default=ROOT / "assets")
    args = parser.parse_args(argv)
    if not args.backing and (not args.model or not args.model_config):
        parser.error("Provide a model and its parameter config, or an already separated backing")
    metadata_path = args.output / "preview.json"
    meta = json.loads(metadata_path.read_text())
    assets = args.output
    with tempfile.TemporaryDirectory(prefix="usagi-backing-") as temp_name:
        temp = Path(temp_name)
        vocals = read_audio(assets / "usagi-vocals.mp3", temp / "voice.wav")
        # Include context at both edges for the separation network.
        if args.backing:
            instrumental = read_audio(args.backing, temp / "instrumental.wav")[:len(vocals)]
            fingerprint = meta.get("separation", {}).get("modelFingerprint", "provided-instrumental")
        else:
            context_start = max(0, meta["songStart"] - 1)
            lead = round((meta["songStart"] - context_start) * SR)
            original = read_audio(args.song, temp / "original.wav", context_start, meta["duration"] + (meta["songStart"] - context_start) + 1)
            instrumental, fingerprint = separate(original, args.model, args.model_config)
            instrumental = instrumental[lead:lead + len(vocals)]
        if len(instrumental) < len(vocals):
            missing=len(vocals)-len(instrumental)
            if missing<=round(.03*SR):
                instrumental=np.pad(instrumental,((0,missing),(0,0)))
            else:
                raise ValueError("Instrumental is shorter than the vocal preview")
        # Balance average levels with headroom, preserving the stereo backing.
        if rms(instrumental) < .001 or rms(vocals) < .001:
            raise ValueError("One of the stems is silent")
        voice_gain = .135 / rms(vocals)
        music_gain = .145 / rms(instrumental)
        voice = vocals * voice_gain
        music = instrumental * music_gain
        mix = voice + music
        master = min(1, .9 / max(float(np.max(np.abs(wave))) for wave in (mix,voice,music)))
        mix *= master
        voice *= master
        music *= master
        master_boost = min(3.0,.16/max(.001,rms(mix)))
        fade_samples = min(int(SR * .025), len(mix) // 2)
        for wave in (mix, voice, music):
            wave[:fade_samples] *= np.linspace(0, 1, fade_samples)[:, None]
            wave[-fade_samples:] *= np.linspace(1, 0, fade_samples)[:, None]
        for name, wave in (("usagi-christmas-preview", mix), ("christmas-backing", music), ("usagi-vocals-playback", voice)):
            sf.write(temp / f"{name}.wav", wave, SR)
            filters=f"volume={master_boost:.8f},alimiter=limit=0.891:attack=5:release=70:level=false:latency=true,apad=whole_len={len(wave)},atrim=end_sample={len(wave)}"
            run("ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(temp / f"{name}.wav"), "-af", filters, "-codec:a", "libmp3lame", "-b:a", "192k", str(assets / f"{name}.mp3"))
        meta["backing"] = {
            "enabled": True, "title": meta.get("title", "All I Want for Christmas Is You"), "artist": meta.get("artist", "Mariah Carey"),
            "method": "UVR MDX instrumental separation", "model": args.model.name if args.model else "UVR-MDX-NET-Inst_HQ_3.onnx", "modelFingerprint": fingerprint,
            "source": meta["songSource"], "start": meta["songStart"],
            "file": "assets/christmas-backing.mp3", "mixFile": "assets/usagi-christmas-preview.mp3", "voiceFile": "assets/usagi-vocals-playback.mp3",
            "musicGain": music_gain * master, "voiceGain": voice_gain * master,
            "voiceRms": rms(voice), "musicRms": rms(music), "mixPeak": float(np.max(np.abs(mix))),
            "mastering": {"targetRms":.16,"peakLimit":.891,"boostDb":float(20*np.log10(master_boost)),"latencyCompensated":True},
        }
        meta["duration"] = len(mix) / SR
        metadata_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
        performance = {key: meta[key] for key in ("duration", "notes", "phrases", "bankSize", "backing", "songStart", "songSource")}
        if "rhythm" in meta: performance["rhythm"] = meta["rhythm"]
        for optional in ('arrangement','vocalCoverage','pitchAnalysis','sourcePolicyVersion'):
            if optional in meta:performance[optional]=meta[optional]
        (assets / "performance.js").write_text("window.USAGI_PERFORMANCE = " + json.dumps(performance, ensure_ascii=False) + ";\n")
        print(f"Mixed {len(mix)/SR:.2f}s: original-song instrumental + Usagi vocals. Peak {np.max(np.abs(mix)):.3f}.")


if __name__ == "__main__":
    main()
