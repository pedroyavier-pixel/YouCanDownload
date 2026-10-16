"""YouCanDownload: one-process web service; media work runs in isolated children."""
import asyncio
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import sys
import time
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).parent
DATA = Path(os.getenv("DOWNLOAD_DIR", "/tmp/youcandownload"))
MAX_ACTIVE = int(os.getenv("MAX_ACTIVE_JOBS", "1"))
TIMEOUT = int(os.getenv("JOB_TIMEOUT_SECONDS", "1800"))
TTL = int(os.getenv("FILE_TTL_SECONDS", "3600"))
MAX_BYTES = int(os.getenv("MAX_FILE_BYTES", "1073741824"))
ACCESS_CODE = os.getenv("APP_ACCESS_CODE", "")
COOKIE = "ycd_session"
HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "www.youtube-nocookie.com"}


def canonical_url(value: str) -> str:
    value = value.strip()
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    parsed = urlparse(value)
    try:
        bad_port = parsed.port not in (None, 443, 80)
    except ValueError:
        bad_port = True
    if parsed.scheme not in {"https", "http"} or parsed.hostname not in HOSTS or parsed.username or parsed.password or bad_port:
        raise ValueError("Pega un enlace válido de YouTube.")
    parts = parsed.path.strip("/").split("/")
    video_id = None
    if parsed.hostname == "youtu.be" and len(parts) == 1:
        video_id = parts[0]
    elif parsed.path == "/watch":
        video_id = parse_qs(parsed.query).get("v", [None])[0]
    elif len(parts) == 2 and parts[0] in {"shorts", "embed", "live"}:
        video_id = parts[1]
    if not video_id or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("El enlace debe apuntar a un video de YouTube, no a un canal o una lista.")
    return "https://www.youtube.com/watch?v=" + video_id


@dataclass
class Job:
    id: str
    owner: str
    url: str
    status: str = "recognizing"
    metadata: dict = field(default_factory=dict)
    progress: dict = field(default_factory=dict)
    error: str | None = None
    file: str | None = None
    updated: float = field(default_factory=time.monotonic)
    process: asyncio.subprocess.Process | None = None
    task: asyncio.Task | None = None


jobs: dict[str, Job] = {}
attempts: dict[str, list[float]] = {}
TERMINAL = {"ready", "error", "cancelled"}


async def stop_process(job):
    process = job.process
    if process and process.returncode is None:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        try:
            await asyncio.wait_for(process.wait(), 5)
        except asyncio.TimeoutError:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            await process.wait()


async def run_job(job):
    directory = DATA / job.id
    directory.mkdir(parents=True)
    try:
        # No shell, no arbitrary URL, and no shared download directory.
        job.process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "worker", job.url, str(directory),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        async with asyncio.timeout(TIMEOUT):
            async for raw in job.process.stdout:
                event = json.loads(raw)
                kind = event.get("type")
                if kind == "metadata":
                    job.metadata = event["data"]
                    job.status = "downloading"
                elif kind == "progress":
                    job.status = "downloading"
                    job.progress = event["data"]
                elif kind == "merging":
                    job.status = "merging"
                elif kind == "error":
                    job.error = event["message"]
                    job.status = "error"
                elif kind == "ready":
                    path = Path(event["path"]).resolve()
                    if path.parent != directory.resolve() or not path.is_file() or path.stat().st_size > MAX_BYTES:
                        raise RuntimeError("Invalid output")
                    job.file = str(path)
                    job.metadata.update(event["data"])
                    job.status = "ready"
                job.updated = time.monotonic()
            code = await job.process.wait()
            if code != 0 or job.status not in {"ready", "error"}:
                job.status = "error"
                job.error = job.error or "No se pudo preparar este video. Intenta de nuevo más tarde."
    except asyncio.CancelledError:
        job.status = "cancelled"
    except TimeoutError:
        job.status = "error"
        job.error = "Este video tardó demasiado en procesarse. Prueba con uno más corto."
    except Exception:
        job.status = "error"
        job.error = "Ocurrió un problema al procesar el video. Intenta de nuevo."
    finally:
        await stop_process(job)
        job.updated = time.monotonic()
        if job.status != "ready":
            shutil.rmtree(directory, ignore_errors=True)


async def cleanup():
    while True:
        await asyncio.sleep(60)
        now = time.monotonic()
        for key, job in list(jobs.items()):
            if job.status in TERMINAL and now - job.updated > TTL:
                shutil.rmtree(DATA / key, ignore_errors=True)
                jobs.pop(key, None)
        for key in list(attempts):
            attempts[key] = [t for t in attempts[key] if now - t < 60]
            if not attempts[key]:
                del attempts[key]


@asynccontextmanager
async def lifespan(app):
    DATA.mkdir(parents=True, exist_ok=True)
    # Jobs are ephemeral and scoped to this single service instance.
    for entry in DATA.iterdir():
        if entry.is_dir() and re.fullmatch(r"[a-f0-9]{48}", entry.name):
            shutil.rmtree(entry, ignore_errors=True)
    sweeper = asyncio.create_task(cleanup())
    yield
    sweeper.cancel()
    with suppress(asyncio.CancelledError):
        await sweeper
    pending = [job.task for job in jobs.values() if job.task and not job.task.done()]
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


app = FastAPI(title="YouCanDownload", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def protect(request: Request, call_next):
    if request.method in {"POST", "DELETE"}:
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "Origen no permitido."}, status_code=403)
    session = request.cookies.get(COOKIE, "")
    if not re.fullmatch(r"[a-f0-9]{48}", session):
        session = secrets.token_hex(24)
    request.state.session = session
    if ACCESS_CODE and request.url.path.startswith("/api/") and request.url.path not in {"/api/health", "/api/unlock"}:
        expected = hmac.digest(ACCESS_CODE.encode(), session.encode(), "sha256").hex()
        if not hmac.compare_digest(request.cookies.get("ycd_access", ""), expected):
            return JSONResponse({"detail": "Introduce tu clave de acceso."}, status_code=401)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' https://i.ytimg.com; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    if request.cookies.get(COOKIE) != session:
        response.set_cookie(COOKIE, session, httponly=True, secure=request.url.scheme == "https", samesite="strict", max_age=86400)
    return response


class Input(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class Unlock(BaseModel):
    code: str = Field(max_length=256)


@app.get("/api/health")
async def health(request: Request):
    import importlib.util
    ready = all(shutil.which(x) for x in ("ffmpeg", "ffprobe", "node")) and importlib.util.find_spec("yt_dlp") is not None
    unlocked = not ACCESS_CODE or hmac.compare_digest(request.cookies.get("ycd_access", ""), hmac.digest(ACCESS_CODE.encode(), request.state.session.encode(), "sha256").hex())
    return {"ready": ready, "locked": not unlocked}


@app.post("/api/unlock")
async def unlock(data: Unlock, request: Request):
    # Shared limit independent of cookies prevents trivial code brute force.
    key = "unlock:global"
    now = time.monotonic()
    recent = [t for t in attempts.get(key, []) if now - t < 60]
    if len(recent) >= 10:
        raise HTTPException(429, "Espera un minuto antes de volver a intentar.")
    attempts[key] = recent + [now]
    if not ACCESS_CODE or not hmac.compare_digest(data.code, ACCESS_CODE):
        raise HTTPException(401, "La clave no es correcta.")
    response = JSONResponse({"ok": True})
    response.set_cookie("ycd_access", hmac.digest(ACCESS_CODE.encode(), request.state.session.encode(), "sha256").hex(), httponly=True, secure=request.url.scheme == "https", samesite="strict", max_age=86400)
    return response


@app.post("/api/jobs", status_code=202)
async def create_job(data: Input, request: Request):
    try:
        url = canonical_url(data.url)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    owner = request.state.session
    for job in jobs.values():
        if job.owner == owner and job.status not in TERMINAL:
            raise HTTPException(409, "Ya tienes una descarga en proceso.")
    active = sum(job.status not in TERMINAL for job in jobs.values())
    if active >= MAX_ACTIVE:
        raise HTTPException(429, "El servidor está ocupado. Intenta en un momento.")
    if sum(job.file is not None for job in jobs.values()) >= 20 or shutil.disk_usage(DATA).free < 2 * MAX_BYTES * (active + 1) + 1024**3:
        raise HTTPException(503, "El servidor necesita liberar espacio. Intenta más tarde.")
    # Global start budget also covers anonymous clients changing their cookies.
    now = time.monotonic()
    recent = [t for t in attempts.get("jobs:global", []) if now - t < 60]
    if len(recent) >= 10:
        raise HTTPException(429, "Demasiadas solicitudes. Intenta en un minuto.")
    attempts["jobs:global"] = recent + [now]
    job = Job(id=secrets.token_hex(24), owner=owner, url=url)
    jobs[job.id] = job
    job.task = asyncio.create_task(run_job(job))
    return {"id": job.id}


def owned(job_id, request):
    job = jobs.get(job_id)
    if not job or job.owner != request.state.session:
        raise HTTPException(404, "La descarga no existe o ya expiró.")
    return job


@app.get("/api/jobs/{job_id}")
async def status(job_id: str, request: Request):
    job = owned(job_id, request)
    return {"id": job.id, "status": job.status, "metadata": job.metadata, "progress": job.progress, "error": job.error,
            "download_url": f"/api/jobs/{job.id}/file" if job.status == "ready" else None}


@app.delete("/api/jobs/{job_id}")
async def cancel(job_id: str, request: Request):
    job = owned(job_id, request)
    if job.task and not job.task.done():
        job.task.cancel()
        await job.task
    job.status = "cancelled"
    job.file = None
    shutil.rmtree(DATA / job.id, ignore_errors=True)
    return {"ok": True}


@app.get("/api/jobs/{job_id}/file")
async def download(job_id: str, request: Request):
    job = owned(job_id, request)
    if job.status != "ready" or not job.file or not Path(job.file).is_file():
        raise HTTPException(409, "El archivo todavía no está disponible.")
    job.updated = time.monotonic()
    suffix = Path(job.file).suffix
    title = re.sub(r'[\x00-\x1f/\\:*?"<>|]', "", job.metadata.get("title", "video"))[:150].strip() or "video"
    return FileResponse(job.file, filename=title + suffix, media_type="video/mp4" if suffix == ".mp4" else "video/x-matroska")


@app.get("/")
async def home():
    return FileResponse(ROOT / "index.html")


@app.get("/{asset}")
async def asset(asset: str):
    if asset not in {"app.js", "config.js", "style.css", "icon.svg"}:
        raise HTTPException(404, "No encontrado.")
    return FileResponse(ROOT / asset)
