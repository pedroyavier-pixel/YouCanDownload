import asyncio
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from functools import partial

from fastapi.testclient import TestClient
import pytest

import server as main
import worker

VIDEO_ID = "YE7VzlLtp-4"
URL = "https://www.youtube.com/watch?v=" + VIDEO_ID


@pytest.mark.parametrize("url", [URL, "https://youtu.be/" + VIDEO_ID + "?si=test", "youtube.com/shorts/" + VIDEO_ID, "https://m.youtube.com/watch?v=" + VIDEO_ID + "&list=ignored", "https://www.youtube.com/live/" + VIDEO_ID])
def test_normalize_video_links(url):
    assert main.canonical_url(url) == URL


@pytest.mark.parametrize("url", ["http://127.0.0.1/a", "https://youtube.com.evil.test/watch?v=" + VIDEO_ID, "https://youtube.com@evil.test/watch?v=" + VIDEO_ID, "https://youtube.com:444/watch?v=" + VIDEO_ID, "https://youtube.com/playlist?list=123", "https://youtube.com/watch?v=x", "https://youtu.be/" + VIDEO_ID + "/extra"])
def test_reject_untrusted_urls(url):
    with pytest.raises(ValueError):
        main.canonical_url(url)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DATA", tmp_path)
    monkeypatch.setattr(main, "ACCESS_CODE", "")
    main.jobs.clear()
    main.attempts.clear()
    with TestClient(main.app) as client:
        yield client


def test_file_is_scoped_to_session_and_supports_range(client, monkeypatch):
    async def fake_job(job):
        path = main.DATA / (job.id + ".mp4")
        path.write_bytes(b"video-and-audio-test")
        job.file = str(path)
        job.metadata = {"title": "Mi video"}
        job.status = "ready"
    monkeypatch.setattr(main, "run_job", fake_job)
    client.get("/api/health")
    response = client.post("/api/jobs", json={"url": URL})
    assert response.status_code == 202
    job_id = response.json()["id"]
    data = client.get("/api/jobs/" + job_id).json()
    assert data["status"] == "ready"
    response = client.get(data["download_url"], headers={"Range": "bytes=0-4"})
    assert response.status_code == 206
    assert response.content == b"video"
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "no-store"
    client.cookies.clear()
    assert client.get("/api/jobs/" + job_id).status_code == 404
    assert client.get(data["download_url"]).status_code == 404


def test_cancel_releases_active_slot(client, monkeypatch):
    async def fake_job(job):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            job.status = "cancelled"
    monkeypatch.setattr(main, "run_job", fake_job)
    first = client.post("/api/jobs", json={"url": URL}).json()
    assert client.post("/api/jobs", json={"url": URL}).status_code == 409
    assert client.delete("/api/jobs/" + first["id"]).status_code == 200
    assert client.get("/api/jobs/" + first["id"]).json()["status"] == "cancelled"
    assert client.post("/api/jobs", json={"url": URL}).status_code == 202


def test_origin_and_input_validation(client):
    assert client.post("/api/jobs", json={"url": URL}, headers={"origin":"https://evil.test"}).status_code == 403
    assert client.post("/api/jobs", json={"url":"https://127.0.0.1"}).status_code == 422


def test_local_mode_serves_no_remote_redirect(monkeypatch):
    monkeypatch.setattr(main, "LOCAL_MODE", True)
    monkeypatch.setattr(main, "LOCAL_HOSTS", {"localhost", "127.0.0.1"})
    with TestClient(main.app, base_url="http://localhost", client=("127.0.0.1", 12345)) as local:
        response = local.get("/config.js")
        assert response.status_code == 200
        assert 'window.YCD_ENGINE_URL = "";' in response.text
        assert "onrender.com" not in response.text
        assert local.get("/api/health").json()["local"] is True
        assert local.get("/", headers={"Host":"attacker.example"}).status_code == 403


@pytest.mark.parametrize("client_address,host,allowed", [
    ("192.168.1.25", "192.168.1.20", True),
    ("203.0.113.25", "192.168.1.20", False),
    ("192.168.1.25", "attacker.example", False),
])
def test_local_mode_private_network_boundary(monkeypatch, client_address, host, allowed):
    monkeypatch.setattr(main, "LOCAL_MODE", True)
    monkeypatch.setattr(main, "LOCAL_HOSTS", {"localhost", "127.0.0.1", "192.168.1.20"})
    with TestClient(main.app, base_url="http://" + host, client=(client_address, 12345)) as local:
        assert local.get("/").status_code == (200 if allowed else 403)


def test_optional_access_code(client, monkeypatch):
    monkeypatch.setattr(main, "ACCESS_CODE", "test-private-code")
    assert client.get("/api/health").json()["locked"] is True
    assert client.post("/api/jobs", json={"url":URL}).status_code == 401
    assert client.post("/api/unlock", json={"code":"wrong"}).status_code == 401
    assert client.post("/api/unlock", json={"code":"test-private-code"}).status_code == 200
    assert client.get("/api/health").json()["locked"] is False


def test_real_download_merge_and_probe(tmp_path, monkeypatch, capsys):
    """Actual HTTP transfer, yt-dlp format choice, FFmpeg merge, ffprobe streams.

    Only YouTube extraction is replaced with a local synthetic fixture. No
    external service or copyrighted media is used by this integration test.
    """
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg unavailable")
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=purple:s=1920x1080:r=5:d=0.4", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source/"video.mp4")], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.4", "-vn", "-c:a", "aac", str(source/"audio.m4a")], check=True)
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(source)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    def extract(self, url, download=True, **kwargs):
        raw = {"id":VIDEO_ID, "title":"Prueba de 1080p", "uploader":"YouCanDownload", "duration":0.4, "extractor":"Youtube", "webpage_url":URL,
            "formats":[
                {"format_id":"low", "url":f"http://127.0.0.1:{port}/video.mp4", "ext":"mp4", "vcodec":"h264", "acodec":"none", "height":720, "fps":5},
                {"format_id":"high", "url":f"http://127.0.0.1:{port}/video.mp4", "ext":"mp4", "vcodec":"h264", "acodec":"none", "height":1080, "fps":5},
                {"format_id":"audio", "url":f"http://127.0.0.1:{port}/audio.m4a", "ext":"m4a", "vcodec":"none", "acodec":"aac", "abr":128},
            ]}
        return self.process_ie_result(raw, download=download)
    monkeypatch.setattr(worker.yt_dlp.YoutubeDL, "extract_info", extract)
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.setattr(sys, "argv", ["worker", URL, str(output)])
    try:
        worker.main()
        events = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith('{')]
        assert events[0]["type"] == "metadata"
        assert events[0]["data"]["height"] == 1080
        assert events[-1]["type"] == "ready"
        assert events[-1]["data"]["height"] == 1080
        media = Path(events[-1]["path"])
        result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "json", str(media)],capture_output=True,text=True,check=True)
        assert {s["codec_type"] for s in json.loads(result.stdout)["streams"]} == {"video", "audio"}
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
