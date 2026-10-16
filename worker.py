"""Structured subprocess events; yt-dlp never handles arbitrary user options."""
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import time

import yt_dlp

MAX_BYTES = int(os.getenv("MAX_FILE_BYTES", "1073741824"))
MAX_DURATION = int(os.getenv("MAX_DURATION_SECONDS", "7200"))


def emit(kind, **values):
    print(json.dumps({"type": kind, **values}), flush=True)


class Quiet:
    def debug(self, text): pass
    def warning(self, text): pass
    def error(self, text): pass


def public_error(exc):
    text = str(exc).lower()
    if any(s in text for s in ("sign in", "bot", "429", "403", "po token")):
        return "YouTube rechazó la conexión desde este servidor. No se pudo descargar el video."
    if any(s in text for s in ("private", "unavailable", "removed", "members-only", "age-restricted")):
        return "Este video no está disponible públicamente para descargar."
    if "too large" in text or "size limit" in text:
        return "El video supera el límite de tamaño del servidor."
    if "duration limit" in text:
        return "El video supera el límite de duración del servidor."
    if "live video" in text:
        return "Espera a que termine la transmisión para descargarla."
    return "No se pudo descargar este video. Intenta de nuevo más tarde."


def main():
    url, output = sys.argv[1:]
    directory = Path(output)
    last_update = 0.0
    completed = 0

    def hook(data):
        nonlocal last_update, completed
        if data["status"] == "finished":
            completed += 1
            emit("merging")
            return
        if data["status"] != "downloading":
            return
        now = time.monotonic()
        if now - last_update < 0.6:
            return
        last_update = now
        used = sum(p.stat().st_size for p in directory.rglob("*") if p.is_file())
        if used > MAX_BYTES * 1.1:
            raise RuntimeError("size limit")
        total = data.get("total_bytes") or data.get("total_bytes_estimate")
        downloaded = data.get("downloaded_bytes", 0)
        emit("progress", data={"downloaded_bytes": downloaded, "total_bytes": total,
            "percent": round(min(downloaded / total * 100, 100), 1) if total else None,
            "speed": data.get("speed"), "eta": data.get("eta"), "track": completed + 1})

    options = {
        "quiet": True, "no_warnings": True, "logger": Quiet(), "noplaylist": True,
        "format": "bestvideo+bestaudio/best[vcodec!=none][acodec!=none]",
        "format_sort": ["res", "fps"], "merge_output_format": "mp4/mkv",
        "outtmpl": str(directory / "video.%(ext)s"), "cachedir": False,
        "socket_timeout": 25, "retries": 2, "fragment_retries": 2,
        "max_filesize": MAX_BYTES, "restrictfilenames": True,
        "js_runtimes": {"node": {"path": shutil.which("node") or "node"}},
        "progress_hooks": [hook],
        "postprocessor_hooks": [lambda d: emit("merging") if d["status"] == "started" else None],
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
            if info.get("is_live") or info.get("live_status") == "is_upcoming":
                raise RuntimeError("live video")
            if not info.get("duration") or info["duration"] > MAX_DURATION:
                raise RuntimeError("duration limit")
            selected = info.get("requested_formats") or [info]
            estimate = sum(f.get("filesize") or f.get("filesize_approx") or 0 for f in selected)
            if estimate > MAX_BYTES:
                raise RuntimeError("size limit")
            height = max((f.get("height") or 0 for f in selected), default=0)
            emit("metadata", data={"title": info.get("title", "Video de YouTube"), "channel": info.get("uploader", "YouTube"),
                "duration": info.get("duration"), "height": height, "estimated_bytes": estimate or None,
                "thumbnail": "https://i.ytimg.com/vi/" + info["id"] + "/hqdefault.jpg"})
            ydl.process_info(info)
        files = [p for p in directory.iterdir() if p.suffix in {".mp4", ".mkv", ".webm"} and ".f" not in p.stem]
        if len(files) != 1:
            raise RuntimeError("No merged output")
        media = files[0]
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(media)], capture_output=True, text=True, check=True, timeout=30)
        streams = json.loads(probe.stdout)["streams"]
        if not any(s["codec_type"] == "video" for s in streams) or not any(s["codec_type"] == "audio" for s in streams):
            raise RuntimeError("Missing video or audio")
        height = max(s.get("height", 0) for s in streams)
        emit("ready", path=str(media.resolve()), data={"height": height, "size_bytes": media.stat().st_size, "extension": media.suffix[1:]})
    except Exception as exc:
        diagnostic = re.sub(r'https?://\S+', '[URL]', str(exc))[:1200]
        emit("error", message=public_error(exc), diagnostic=diagnostic)
        sys.exit(1)


if __name__ == "__main__":
    main()
