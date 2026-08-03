FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libchromaprint-tools \
        espeak-ng \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

# Fail loudly at build time if the application package is missing. Uploading
# via a file picker silently drops folders, which otherwise only shows up as
# "ModuleNotFoundError: No module named 'app'" after a successful deploy.
RUN test -f app/main.py || ( \
      echo "" && \
      echo "BUILD STOPPED: app/main.py is missing from this repository." && \
      echo "The 'app' folder did not get uploaded." && \
      echo "On GitHub, DRAG the app folder onto the upload area - the" && \
      echo "'choose your files' picker cannot select folders." && \
      echo "" && \
      exit 1 )

RUN useradd --create-home --uid 10001 omnicraft \
    && mkdir -p /app/storage \
    && chown -R omnicraft:omnicraft /app
USER omnicraft

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:${PORT:-8000}/api/health || exit 1

# Render, Fly and Heroku inject $PORT. Falls back to 8000 for local/compose.
ENV PORT=8000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips '*'"]
