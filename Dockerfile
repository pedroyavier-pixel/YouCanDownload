FROM node:22-bookworm-slim AS node
FROM python:3.12-slim-bookworm
COPY --from=node /usr/local/bin/node /usr/local/bin/node
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=app:app server.py worker.py index.html app.js style.css icon.svg config.js ./
RUN printf 'window.YCD_ENGINE_URL = "";\n' > config.js
USER app
ENV PORT=8000 PYTHONUNBUFFERED=1 DOWNLOAD_DIR=/tmp/youcandownload
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
