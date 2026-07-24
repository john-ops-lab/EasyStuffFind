FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    EASYSTUFFFIND_DATA_DIR=/data \
    EASYSTUFFFIND_HOST=0.0.0.0 \
    EASYSTUFFFIND_PORT=8733 \
    EASYSTUFFFIND_LOG_LEVEL=INFO

WORKDIR /app

COPY requirements.lock ./
RUN python -m pip install --no-cache-dir -r requirements.lock

COPY easystufffind ./easystufffind
COPY pyproject.toml LICENSE ./

RUN useradd --system --uid 10001 --create-home --home-dir /home/easystufffind easystufffind \
    && mkdir -p /data \
    && chown -R easystufffind:easystufffind /data /app

USER easystufffind

EXPOSE 8733
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "from urllib.request import urlopen; r=urlopen('http://127.0.0.1:8733/health', timeout=3); raise SystemExit(0 if r.status == 200 else 1)"]

CMD ["python", "-m", "easystufffind"]
