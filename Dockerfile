FROM node:22-bookworm-slim AS node
FROM python:3.11-slim-bookworm
COPY --from=node /usr/local/bin/node /usr/local/bin/node
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY server/requirements.txt /app/server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt
COPY server /app/server
COPY tools /app/tools
COPY THIRD_PARTY_NOTICES.md LICENSE NOTICE /app/
COPY assets /app/assets
COPY index.html style.css script.js config.js /app/
RUN useradd --create-home usagi && mkdir -p /data && chown -R usagi:usagi /data /app
USER usagi
ENV USAGI_DATA_DIR=/data
ENV PORT=8000
ENV USAGI_CPU_THREADS=4 OMP_NUM_THREADS=4 NUMBA_NUM_THREADS=4 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/api/health',timeout=3)"
CMD ["sh", "-c", "exec uvicorn server.app:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
