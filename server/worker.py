"""One CPU worker: validate/download a song, separate, resynthesize and mix."""
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from urllib.request import Request, urlopen
import hashlib
import json
import os
import re
import subprocess
import time

import soundfile as sf

from tools.rap_singing import render_preview
from tools.prepare_backing import read_audio, separate, main as mix_stems, SR
from tools.rhythm import measure_beats
from tools.neural_pitch import ensure_pitch_model

ROOT = Path(__file__).resolve().parents[1]
MODEL_URL = "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/UVR-MDX-NET-Inst_HQ_3.onnx"
CONFIG_URL = "https://raw.githubusercontent.com/Anjok07/ultimatevocalremovergui/master/models/MDX_Net_Models/model_data/model_data.json"
EXPECTED_FINGERPRINT = "55657dd70583b0fedfba5f67df11d711"


class Cancelled(Exception):
    pass


def youtube_id(value):
    try:
        url = urlsplit(value.strip())
        if url.scheme not in ("http", "https") or url.username or url.password or url.port:
            raise ValueError()
        host = (url.hostname or "").lower()
        parts = [part for part in url.path.split("/") if part]
        if host == "youtu.be":
            video = parts[0] if len(parts) == 1 else ""
        elif host in ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"):
            video = parse_qs(url.query).get("v", [""])[0] if url.path == "/watch" else parts[1] if len(parts) == 2 and parts[0] in ("shorts", "embed", "live") else ""
        else:
            raise ValueError()
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video):
            raise ValueError()
        return video
    except (ValueError, TypeError, AttributeError):
        raise ValueError("올바른 YouTube 영상 링크를 넣어주세요.") from None


def run_process(command, job, timeout=240):
    log_path = job.directory / "process.log"
    with log_path.open("w") as stream:
        process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        deadline = time.monotonic() + timeout
        while process.poll() is None:
            try:
                job.check_cancelled()
                if time.monotonic() > deadline:
                    raise TimeoutError("원본을 가져오는 시간이 너무 오래 걸려요. 잠시 후 다시 시도해 주세요.")
                if sum(p.stat().st_size for p in job.directory.glob("source*")) > 100 * 1024 * 1024:
                    raise ValueError("음원이 너무 커요. 10분 이하의 짧은 영상을 골라주세요.")
                time.sleep(.2)
            except BaseException:
                import signal
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                raise
    if process.returncode:
        # Do not return extractor logs or temporary signed URLs to visitors.
        raise ValueError("YouTube에서 음원을 가져오지 못했어요. 공개 영상인지 확인해 주세요. 서버의 YouTube 접근 제한일 수도 있어요.")


def ensure_models(data_dir, update):
    models = data_dir / "models"
    models.mkdir(parents=True, exist_ok=True)
    model = models / "UVR-MDX-NET-Inst_HQ_3.onnx"
    config = models / "model_data.json"
    for path, url, minimum in ((model, MODEL_URL, 60_000_000), (config, CONFIG_URL, 1000)):
        if path.exists() and path.stat().st_size >= minimum:
            continue
        update(.03, "처음 실행에 필요한 반주 분리 모델을 준비하고 있어요")
        temporary = path.with_suffix(path.suffix + ".partial")
        try:
            with urlopen(Request(url, headers={"User-Agent": "UsagiChristmas/1.0"}), timeout=45) as response, temporary.open("wb") as stream:
                while chunk := response.read(256 * 1024):
                    update(.04, "반주 분리 모델을 내려받고 있어요")
                    stream.write(chunk)
            if temporary.stat().st_size < minimum:
                raise ValueError("반주 분리 모델을 받지 못했어요.")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    with model.open("rb") as stream:
        stream.seek(-10000 * 1024, 2)
        actual = hashlib.md5(stream.read()).hexdigest()
    if actual != EXPECTED_FINGERPRINT:
        raise ValueError("반주 분리 모델 파일 검증에 실패했어요.")
    return model, config


def convert(job, data_dir):
    def update(value, message):
        job.check_cancelled()
        job.update(progress=value, message=message)

    job.check_cancelled()
    video = youtube_id(job.request["youtube_url"])
    canonical = f"https://www.youtube.com/watch?v={video}"
    update(.01, "YouTube 곡 정보를 확인하고 있어요")
    run_process(["yt-dlp", "--no-playlist", "--skip-download", "--no-warnings", "--write-info-json", "--no-clean-info-json", "--js-runtimes", "node", "-o", str(job.directory / "source.%(ext)s"), canonical], job)
    info_path = job.directory / "source.info.json"
    if not info_path.exists():
        raise ValueError("영상 정보를 읽을 수 없어요.")
    info = json.loads(info_path.read_text())
    total = info.get("duration") or 0
    if info.get("is_live") or not 0 < total <= 600:
        raise ValueError("라이브가 아닌 10분 이하의 영상을 골라주세요.")
    start = job.request["start"]
    duration = min(job.request["duration"] or total, total - start)
    if duration < 5:
        raise ValueError("선택한 구간이 너무 짧아요. 5초 이상 남는 시작 시각을 골라주세요.")
    title = str(info.get("track") or info.get("title") or "나의 우사기 공연")[:180]
    artist = str(info.get("artist") or info.get("uploader") or "YouTube")[:100]
    job.update(title=title, artist=artist)
    update(.07, "공연에 쓸 음원을 가져오고 있어요")
    run_process(["yt-dlp", "--no-playlist", "--no-warnings", "--no-progress", "--js-runtimes", "node", "-f", "bestaudio", "--max-filesize", "100M", "-o", str(job.directory / "source.%(ext)s"), canonical], job)
    sources = [p for p in job.directory.glob("source.*") if p.suffix.lower() in (".webm", ".m4a", ".mp3", ".ogg", ".opus", ".mp4", ".wav")]
    if not sources:
        raise ValueError("재생할 수 있는 오디오를 찾지 못했어요.")
    model, config = ensure_models(data_dir, update)
    update(.12, "반주와 원곡 보컬을 분리하고 있어요")
    original = read_audio(sources[0], job.directory / "original.wav", start, duration)
    backing, fingerprint = separate(original, model, config, notify=lambda value, message: update(.12 + .4 * value, message))
    sf.write(job.directory / "instrumental.wav", backing, SR)
    sf.write(job.directory / "melody.wav", original - backing, SR)
    update(.53, "우사기가 춤출 노래 박자를 확인하고 있어요")
    rhythm = measure_beats(backing, SR)
    update(.54, "원곡 보컬의 멜로디에 우사기 발성을 맞추고 있어요")
    pitch_model = ensure_pitch_model(data_dir / 'models', notify=lambda message:update(.54,message))
    meta = render_preview(song=job.directory / "original.wav", output=job.directory, start=0, duration=len(original) / SR, melody=job.directory / "melody.wav", keep_duration=True, source_url=canonical, rhythm=rhythm, pitch_model=pitch_model, notify=lambda value, message: update(.54 + value * .39, message))
    meta.update(title=title, artist=artist, songStart=start, rhythm=rhythm, separation={"modelFingerprint": fingerprint})
    (job.directory / "preview.json").write_text(json.dumps(meta, ensure_ascii=False))
    update(.95, "반주와 우사기 보컬의 음량을 맞추고 있어요")
    mix_stems(["--song", str(sources[0]), "--output", str(job.directory), "--backing", str(job.directory / "instrumental.wav"), "--model", str(model)])
    final = json.loads((job.directory / "preview.json").read_text())
    # Working copies include extractor details; keep only the usable results.
    for path in job.directory.iterdir():
        if path.suffix in (".wav", ".webm", ".m4a", ".opus", ".ogg", ".mp4") or path.name.startswith("source.") or path.name == "process.log":
            path.unlink(missing_ok=True)
    return {key: final[key] for key in ("title", "artist", "duration", "notes", "phrases", "bankSize", "backing", "songStart", "songSource", "rhythm", "vocalCoverage", "arrangement", "pitchAnalysis", "sourcePolicyVersion")}
