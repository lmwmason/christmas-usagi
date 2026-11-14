"""API contracts: input boundaries, queue/cancel/retry, and playable audio ranges."""
from pathlib import Path
import json
import shutil
import tempfile
import time
import unittest

from fastapi.testclient import TestClient
from pydantic import ValidationError

from server.app import create_app, ConversionRequest, MEDIA
from server.worker import ROOT, youtube_id
from unittest.mock import patch


def preview_processor(job, _):
    job.check_cancelled()
    meta = json.loads((ROOT / "assets/preview.json").read_text())
    for name in MEDIA.values():
        shutil.copy2(ROOT / "assets" / name, job.directory / name)
    result = {key: meta[key] for key in ("duration", "notes", "phrases", "bankSize", "backing", "songStart", "songSource")}
    result["rhythm"] = meta.get("rhythm", {"bpm": 120, "beats": []})
    return dict(result, title="테스트 공연", artist="원곡 가수")


def waiting_processor(job, _):
    while True:
        job.check_cancelled()
        time.sleep(.01)


class InputTests(unittest.TestCase):
    def test_supported_youtube_links_share_an_id(self):
        for url in ("https://youtu.be/yXQViqx6GMY?si=example", "https://www.youtube.com/watch?v=yXQViqx6GMY&t=46", "https://music.youtube.com/watch?v=yXQViqx6GMY", "https://youtube.com/shorts/yXQViqx6GMY"):
            self.assertEqual(youtube_id(url), "yXQViqx6GMY")

    def test_urls_cannot_redirect_the_worker_to_arbitrary_hosts(self):
        for url in ("file:///etc/passwd", "https://youtube.com.evil.test/watch?v=yXQViqx6GMY", "https://youtube.com@127.0.0.1/watch?v=yXQViqx6GMY", "http://127.0.0.1/video", "https://youtu.be/../../secret", "https://youtube.com/watch?v=too-short", "https://youtu.be:443/yXQViqx6GMY"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                youtube_id(url)

    def test_invalid_time_ranges_are_rejected(self):
        for extra in ({"start": -1}, {"duration": 601}, {"duration": 0}, {"start": float("nan")}, {"duration": float("inf")}):
            with self.subTest(extra=extra), self.assertRaises(ValidationError):
                ConversionRequest(youtube_url="https://youtu.be/yXQViqx6GMY", **extra)


class APITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.temp.name), preview_processor)
        self.client = TestClient(self.app).__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def submit(self, **extra):
        return self.client.post("/api/jobs", json={"youtube_url": "https://youtu.be/yXQViqx6GMY", "duration": 15, **extra})

    def finish(self, identifier):
        for _ in range(100):
            result = self.client.get("/api/jobs/" + identifier).json()
            if result["status"] in ("completed", "failed", "cancelled"):
                return result
            time.sleep(.01)
        self.fail("Job did not reach a terminal status")

    def test_preview_and_health_are_served_without_exposing_tools(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertGreaterEqual(self.client.get("/api/health").json()["soundCount"], 10)
        self.assertEqual(self.client.get("/server/worker.py").status_code, 404)
        self.assertTrue(self.client.get("/script.js?filename=/etc/passwd").text.startswith("'use strict'"))

    def test_completed_job_streams_seekable_audio_and_download(self):
        response = self.submit()
        self.assertEqual(response.status_code, 202)
        identifier = response.json()["id"]
        completed = self.finish(identifier)
        self.assertEqual(completed["status"], "completed")
        path = completed["result"]["backing"]["mixFile"]
        self.assertEqual(path, f"/api/jobs/{identifier}/audio/mix")
        audio = self.client.get(path, headers={"Range": "bytes=0-99"})
        self.assertEqual(audio.status_code, 206)
        self.assertEqual(len(audio.content), 100)
        self.assertIn("bytes 0-99/", audio.headers["content-range"])
        self.assertIn("attachment", self.client.get(path + "?download=true").headers["content-disposition"])
        self.assertEqual(self.client.get(f"/api/jobs/{identifier}/audio/job.json").status_code, 404)

    def test_retried_submission_does_not_duplicate_expensive_work(self):
        token = "a" * 32
        first = self.submit(client_token=token)
        second = self.submit(client_token=token)
        self.assertEqual(first.json()["id"], second.json()["id"])
        conflict = self.submit(client_token=token, start=10)
        self.assertEqual(conflict.status_code, 409)

    def test_bad_links_and_unknown_jobs_fail_cleanly(self):
        self.assertEqual(self.submit(youtube_url="https://example.com/a.mp3").status_code, 422)
        self.assertEqual(self.client.get("/api/jobs/" + "0" * 32).status_code, 404)

    def test_expired_results_are_removed(self):
        identifier = self.submit().json()["id"]
        self.finish(identifier)
        job = self.app.state.manager.get(identifier)
        job.update(created_at=time.time() - 25 * 3600)
        self.assertEqual(self.client.get("/api/jobs/" + identifier).status_code, 404)
        self.assertFalse(job.directory.exists())

    def test_shared_audio_survives_original_cleanup_and_server_restart(self):
        identifier = self.submit().json()['id']
        self.assertEqual(self.finish(identifier)['status'], 'completed')
        first = self.client.post(f'/api/jobs/{identifier}/share')
        self.assertEqual(first.status_code, 200)
        shared = first.json()
        self.assertNotIn('sourceJobId', shared)
        self.assertNotIn('jobId', shared['result'])
        self.assertEqual(self.client.post(f'/api/jobs/{identifier}/share').json()['id'], shared['id'])
        job = self.app.state.manager.get(identifier)
        job.update(created_at=time.time()-25*3600)
        self.app.state.manager.cleanup()
        self.assertFalse(job.directory.exists())
        # A new app instance must recover the public copy without its source job.
        with TestClient(create_app(Path(self.temp.name), preview_processor)) as visitor:
            result = visitor.get('/api/shares/'+shared['id'])
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()['result']['title'], '테스트 공연')
            path = result.json()['result']['backing']['mixFile']
            streamed = visitor.get(path, headers={'Range':'bytes=10-109'})
            self.assertEqual(streamed.status_code, 206)
            self.assertEqual(len(streamed.content), 100)
            self.assertIn('attachment', visitor.get(path+'?download=true').headers['content-disposition'])
            self.assertEqual(visitor.get(f"/api/shares/{shared['id']}/audio/share.json").status_code, 404)

    def test_expired_shares_and_full_storage_fail_clearly(self):
        identifier = self.submit().json()['id']
        self.finish(identifier)
        with patch('server.sharing.SHARE_BUDGET', 1):
            self.assertEqual(self.client.post(f'/api/jobs/{identifier}/share').status_code, 507)
        shared = self.client.post(f'/api/jobs/{identifier}/share').json()
        path = self.app.state.shares.directory / shared['id'] / 'share.json'
        saved = json.loads(path.read_text());saved['expires_at'] = time.time()-1
        path.write_text(json.dumps(saved))
        self.assertEqual(self.client.get('/api/shares/'+shared['id']).status_code, 410)
        self.assertFalse(path.parent.exists())
        self.assertEqual(self.client.get('/api/shares/not-a-valid-id').status_code, 404)


class QueueTests(unittest.TestCase):
    def test_cancellation_and_queue_limit(self):
        with tempfile.TemporaryDirectory() as directory, TestClient(create_app(Path(directory), waiting_processor)) as client:
            payload = {"youtube_url": "https://youtu.be/yXQViqx6GMY"}
            jobs = [client.post("/api/jobs", json=payload).json()["id"] for _ in range(3)]
            self.assertEqual(client.post("/api/jobs", json=payload).status_code, 429)
            self.assertEqual(client.post(f'/api/jobs/{jobs[0]}/share').status_code, 409)
            for identifier in jobs:
                self.assertEqual(client.delete("/api/jobs/" + identifier).status_code, 200)
            for _ in range(100):
                states = [client.get("/api/jobs/" + identifier).json()["status"] for identifier in jobs]
                if all(state == "cancelled" for state in states):
                    break
                time.sleep(.01)
            self.assertEqual(states, ["cancelled"] * 3)


if __name__ == "__main__":
    unittest.main()
