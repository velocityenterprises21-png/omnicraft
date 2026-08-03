#!/usr/bin/env bash
# OMNICRAFT first-run setup. Safe to run more than once.
set -euo pipefail

cd "$(dirname "$0")"
ENV_FILE="backend/.env"

echo "OMNICRAFT setup"
echo "==============="

if [ -f "$ENV_FILE" ]; then
  echo "· $ENV_FILE already exists, leaving it alone."
else
  cp backend/.env.example "$ENV_FILE"
  echo "· Created $ENV_FILE from the example."

  if command -v python3 >/dev/null 2>&1; then
    KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
  elif command -v openssl >/dev/null 2>&1; then
    KEY=$(openssl rand -base64 48 | tr -d '\n/+=' | cut -c1-64)
  else
    KEY=""
    echo "! No python3 or openssl found. Set SECRET_KEY in $ENV_FILE by hand."
  fi

  if [ -n "$KEY" ]; then
    # BSD sed (macOS) needs an argument to -i; GNU sed does not.
    if sed --version >/dev/null 2>&1; then
      sed -i "s|^SECRET_KEY=.*|SECRET_KEY=${KEY}|" "$ENV_FILE"
    else
      sed -i '' "s|^SECRET_KEY=.*|SECRET_KEY=${KEY}|" "$ENV_FILE"
    fi
    echo "· Generated a random SECRET_KEY."
  fi
fi

echo
echo "Checking the tools the media modules need:"
for bin in ffmpeg ffprobe fpcalc espeak-ng; do
  if command -v "$bin" >/dev/null 2>&1; then
    echo "  ok      $bin"
  else
    echo "  missing $bin"
  fi
done

cat <<'NOTE'

Missing tools only disable the modules that need them - the API still boots and
reports what is unavailable at /api/capabilities.

  macOS         brew install ffmpeg chromaprint espeak-ng
  Debian/Ubuntu sudo apt install ffmpeg libchromaprint-tools espeak-ng

Next:
  docker compose up --build     # everything, including Postgres and Redis
  open http://localhost:3000

Optional: add provider keys to backend/.env (OpenAI, ElevenLabs, Stripe, ...).
Nothing is required to start.
NOTE
