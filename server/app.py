from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from threading import RLock, Event
import json
import logging
import os
import re
import shutil
import time
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from server.worker import ROOT, Cancelled, convert, youtube_id
from server.resources import CPU_THREADS,TARGET_MEMORY
from server.sharing import ShareStore

logger = logging.getLogger("usagi")
DATA = Path(os.environ.get("USAGI_DATA_DIR", ROOT / ".cache/runtime"))
MEDIA = {"mix": "usagi-christmas-preview.mp3", "voice": "usagi-vocals-playback.mp3", "backing": "christmas-backing.mp3"}


class ConversionRequest(BaseModel):
    youtube_url: str = Field(min_length=10, max_length=2048)
    start: float = Field(default=0, ge=0, le=595, allow_inf_nan=False)
    duration: float | None = Field(default=None, ge=5, le=600, allow_inf_nan=False)
    client_token: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")

    @field_validator("youtube_url")
    @classmethod
    def valid_video(cls, value):
        return "https://www.youtube.com/watch?v=" + youtube_id(value)


class Job:
    def __init__(self, identifier, directory, request):
        self.id, self.directory, self.request = identifier, directory, request
        self.lock = RLock()
        self.cancel = Event()
        self.future = None
        self.data = {"id": identifier, "status": "queued", "progress": 0, "message": "앞선 공연이 끝나면 시작해요", "created_at": time.time(), "title": "나의 우사기 공연", "artist": "", "result": None}

    def update(self, **values):
        with self.lock:
            if "progress" in values:
                values["progress"] = max(self.data["progress"], min(1, values["progress"]))
            self.data.update(values)
            self.directory.mkdir(parents=True, exist_ok=True)
            temporary = self.directory / "job.json.tmp"
            temporary.write_text(json.dumps(self.data, ensure_ascii=False))
            temporary.replace(self.directory / "job.json")

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.data))

    def check_cancelled(self):
        if self.cancel.is_set():
            raise Cancelled()


class JobManager:
    def __init__(self, data_dir=DATA, processor=convert):
        self.directory = Path(data_dir)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.jobs = {}
        self.lock = RLock()
        self.processor = processor
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="usagi-audio")
        self.closed = False
        for path in (self.directory / "jobs").glob("*/job.json"):
            try:
                data = json.loads(path.read_text())
                if not re.fullmatch(r"[a-f0-9]{32}", data["id"]):
                    continue
                job = Job(data["id"], path.parent, {})
                job.data = data
                if data["status"] in ("queued", "running"):
                    job.update(status="failed", message="서버가 재시작되어 공연 준비가 멈췄어요. 다시 시도해 주세요.")
                self.jobs[job.id] = job
            except (ValueError, KeyError, OSError):
                logger.warning("Skipped an incomplete job record")
        self.cleanup()

    def cleanup(self):
        with self.lock:
            complete = sorted((job for job in self.jobs.values() if job.snapshot()["status"] not in ("running", "queued")), key=lambda job: job.data["created_at"], reverse=True)
            for index, job in enumerate(complete):
                if index >= 10 or time.time() - job.data["created_at"] > 24 * 3600:
                    self.jobs.pop(job.id, None)
                    shutil.rmtree(job.directory, ignore_errors=True)

    def submit(self, request):
        with self.lock:
            self.cleanup()
            if request.get("client_token"):
                for existing in self.jobs.values():
                    if existing.request.get("client_token") == request["client_token"]:
                        if existing.request != request:
                            raise HTTPException(409, "다른 곡의 요청이 섞였어요. 페이지를 새로 열어주세요.")
                        return existing
            if self.closed:
                raise HTTPException(503, "서버가 종료 중이에요. 잠시 후 다시 시도해 주세요.")
            if sum(job.snapshot()["status"] in ("queued", "running") for job in self.jobs.values()) >= 3:
                raise HTTPException(429, "지금 준비 중인 공연이 많아요. 잠시 뒤 다시 시도해 주세요.")
            identifier = uuid.uuid4().hex
            job = Job(identifier, self.directory / "jobs" / identifier, request)
            self.jobs[identifier] = job
            job.update()
            job.future = self.pool.submit(self.work, job)
            return job

    def work(self, job):
        try:
            job.check_cancelled()
            job.update(status="running", message="공연 준비를 시작해요")
            result = self.processor(job, self.directory)
            job.check_cancelled()
            result["backing"].update(file=f"/api/jobs/{job.id}/audio/backing", mixFile=f"/api/jobs/{job.id}/audio/mix", voiceFile=f"/api/jobs/{job.id}/audio/voice")
            result["jobId"] = job.id
            job.update(status="completed", progress=1, message="공연 준비가 끝났어요!", result=result)
        except Cancelled:
            job.update(status="cancelled", message="공연 준비를 취소했어요")
        except Exception as error:
            logger.exception("Conversion failed for job %s", job.id)
            message = str(error) if isinstance(error, (ValueError, TimeoutError)) and re.search(r"[가-힣]", str(error)) else "공연을 만드는 중 문제가 생겼어요. 잠시 뒤 다시 시도해 주세요."
            job.update(status="failed", message=message[:250])
        finally:
            # Failed and cancelled jobs should not retain large working audio.
            if job.snapshot()["status"] != "completed":
                for path in job.directory.glob("*"):
                    if path.name != "job.json" and path.is_file():
                        path.unlink(missing_ok=True)

    def get(self, identifier):
        if not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise HTTPException(404, "공연을 찾을 수 없어요.")
        self.cleanup()
        with self.lock:
            job = self.jobs.get(identifier)
        if not job:
            raise HTTPException(404, "공연이 만료되었거나 존재하지 않아요. 새로 만들어 주세요.")
        return job

    def close(self):
        with self.lock:
            self.closed = True
            for job in self.jobs.values():
                if job.snapshot()["status"] in ("queued", "running"):
                    job.cancel.set()
            self.pool.shutdown(wait=True)


def create_app(data_dir=DATA, processor=convert):
    @asynccontextmanager
    async def lifespan(app):
        app.state.manager = JobManager(data_dir, processor)
        app.state.shares = ShareStore(data_dir)
        yield
        app.state.manager.close()

    app = FastAPI(title="우사기의 크리스마스 무대", lifespan=lifespan)
    origins = [value.strip() for value in os.environ.get("USAGI_ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000,http://localhost:4173").split(",") if value.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST", "DELETE", "OPTIONS"], allow_headers=["Content-Type", "Range"], expose_headers=["Accept-Ranges", "Content-Range"])

    @app.get("/api/health")
    def health():
        bank = json.loads((ROOT / "assets/sources/manifest.json").read_text())
        return {"status": "ok", "soundCount": len(bank), "maxVideoSeconds": 600, "modelReady": (Path(data_dir) / "models/UVR-MDX-NET-Inst_HQ_3.onnx").exists(), "pitchModelReady": (Path(data_dir) / 'models/rmvpe.onnx').exists(), "pitchAnalysis": 'RMVPE ONNX CPU', "sourcePolicyVersion": 1,"processing":{"cpuThreads":CPU_THREADS,"conversionWorkers":1,"deploymentMemoryTarget":TARGET_MEMORY}}

    @app.post("/api/jobs", status_code=202)
    def submit(request: ConversionRequest):
        return app.state.manager.submit(request.model_dump()).snapshot()

    @app.get("/api/jobs/{identifier}")
    def read_job(identifier: str):
        return app.state.manager.get(identifier).snapshot()

    @app.delete("/api/jobs/{identifier}")
    def cancel_job(identifier: str):
        job = app.state.manager.get(identifier)
        if job.snapshot()["status"] in ("queued", "running"):
            job.cancel.set()
            if job.future and job.future.cancel():
                job.update(status="cancelled", message="공연 준비를 취소했어요")
        return job.snapshot()

    @app.get("/api/jobs/{identifier}/audio/{kind}")
    def job_audio(identifier: str, kind: str, download: bool = False):
        job = app.state.manager.get(identifier)
        if kind not in MEDIA or job.snapshot()["status"] != "completed":
            raise HTTPException(404, "공연 음원을 찾을 수 없어요.")
        path = job.directory / MEDIA[kind]
        if not path.is_file():
            raise HTTPException(404, "공연 음원이 만료되었어요.")
        return FileResponse(path, media_type="audio/mpeg", filename="usagi-performance.mp3" if download else None, headers={"Cache-Control": "private, max-age=3600"})

    @app.get("/")
    def home():
        return FileResponse(ROOT / "index.html")

    @app.post('/api/jobs/{identifier}/share')
    def share_job(identifier: str):
        return app.state.shares.create(app.state.manager.get(identifier))

    @app.get('/api/shares/{identifier}')
    def read_share(identifier: str):
        return app.state.shares.get(identifier)

    @app.get('/api/shares/{identifier}/audio/{kind}')
    def share_audio(identifier: str, kind: str, download: bool = False):
        app.state.shares.get(identifier)
        if kind not in MEDIA:
            raise HTTPException(404, '공유 음원을 찾을 수 없어요.')
        path = app.state.shares.directory / identifier / MEDIA[kind]
        if not path.is_file():
            raise HTTPException(404, '공유 음원을 찾을 수 없어요.')
        return FileResponse(path, media_type='audio/mpeg', filename='usagi-performance.mp3' if download else None, headers={'Cache-Control':'public, max-age=3600'})

    for name in ("style.css", "script.js", "config.js"):
        # Static routes do not accept a filename query parameter.
        app.add_api_route("/" + name, (lambda filename: lambda: FileResponse(ROOT / filename))(name), methods=["GET"], include_in_schema=False)
    app.mount("/assets", StaticFiles(directory=ROOT / "assets"), name="assets")
    return app


app = create_app()
