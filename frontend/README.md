# OMNICRAFT

**One System. All Media. Infinite Possibilities.**

A FastAPI backend and a dependency-free single-page frontend for downloading,
narrating, subtitling, rewriting, clearing and generating video — with credits,
subscriptions and a live job queue.

---

## What's in the box

| # | Module | What it does | Needs |
|---|--------|--------------|-------|
| 01 | Downloader | Pulls source media from ~10 platforms at the best available quality | `yt-dlp` |
| 02 | Text to speech | Script in, finished voice track out | ElevenLabs or OpenAI (or offline espeak-ng) |
| 03 | Narration | Lays a voice over a video: replace, blend or duck the original | ffmpeg |
| 04 | Subtitles | Transcribes speech to timed lines; translates into 70+ languages | Whisper + a language model |
| 05 | Storyline | Turns a transcript into a summary, bullets, clean copy, script or chapters | Language model (works offline, extractively) |
| 06 | Music rights | Screens audio for commercial recordings and clears what you don't own | AcoustID + `fpcalc` |
| 07 | Autopilot | Reads a plain-language instruction and routes it across the modules | Language model (falls back to keyword planning) |
| 08 | Research | Searches the open web, reads results, writes a sourced briefing | Serper (falls back to DuckDuckGo) |
| 09 | Security | JWT with refresh rotation, TOTP two-factor, roles, rate limiting, API keys | — |
| 10 | Storage | Uploads, quotas, expiring share links, automatic temp-file sweeps | Optional S3 |
| 11 | Billing | Six tiers monthly or yearly, seven credit packs, Stripe checkout and webhooks | Stripe |
| 12 | AI video | Brief, script or link → narrated, captioned, graded video | ffmpeg + a visual provider |

Nothing here hard-fails when a key is missing. Every module reports its own
readiness through `GET /api/capabilities`, and the interface shows an amber
status light with the exact environment variable to set.

---

## Quick start

### Docker (everything, including Postgres and Redis)

```bash
git clone <your-repo> omnicraft && cd omnicraft
./setup.sh              # writes backend/.env with a generated SECRET_KEY
docker compose up --build
```

- Interface: <http://localhost:3000>
- API: <http://localhost:8000>
- API docs: <http://localhost:8000/api/docs>

### Local, without Docker

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(48))" >> .env
uvicorn app.main:app --reload --port 8000

# Frontend (any static server — it has no build step)
cd ../frontend
python -m http.server 3000
```

The database schema and the plan catalog are created on first boot. SQLite is
the default so you can run with zero infrastructure.

**ffmpeg is required** for anything that touches media:

```bash
# macOS
brew install ffmpeg chromaprint espeak-ng
# Debian / Ubuntu
sudo apt install ffmpeg libchromaprint-tools espeak-ng
# Windows
winget install Gyan.FFmpeg
```

### A bootstrap admin account

Set these before the first boot and an admin is created once:

```
ADMIN_EMAIL=you@example.com
ADMIN_USERNAME=admin
ADMIN_PASSWORD=a-long-password-you-will-remember
```

---

## Getting the API keys

Every one of these is optional. Start with none, add them as you need modules.

| Key | Where to get it | Unlocks | Rough cost |
|-----|-----------------|---------|-----------|
| `OPENAI_API_KEY` | <https://platform.openai.com/api-keys> | Rewriting, translation, transcription, autopilot planning, research synthesis, backup voices | Pay as you go |
| `ANTHROPIC_API_KEY` | <https://console.anthropic.com/settings/keys> | Same language-model roles as above | Pay as you go |
| `ELEVENLABS_API_KEY` | <https://elevenlabs.io/app/settings/api-keys> | Production narration voices, 29 languages | Free tier available |
| `REPLICATE_API_KEY` | <https://replicate.com/account/api-tokens> | Generated visuals for AI video | Per second of compute |
| `RUNWAY_API_KEY` | <https://dev.runwayml.com> | Generative video clips | Credit based |
| `PEXELS_API_KEY` | <https://www.pexels.com/api/new/> | Free stock imagery for AI video | Free |
| `SERPER_API_KEY` | <https://serper.dev/api-key> | Better research coverage than the fallback | 2,500 free searches |
| `ACOUSTID_API_KEY` | <https://acoustid.org/new-application> | Automatic recording identification | Free |
| `STRIPE_SECRET_KEY` | <https://dashboard.stripe.com/apikeys> | Subscriptions and credit packs | Per transaction |

### Transcription without an API key

```bash
pip install faster-whisper
```

The subtitle module prefers a local model when one is installed, so
transcription costs nothing and nothing leaves your server.

### Stripe setup

1. Add `STRIPE_SECRET_KEY` and `STRIPE_PUBLISHABLE_KEY`.
2. Forward webhooks in development:
   ```bash
   stripe listen --forward-to localhost:8000/api/payments/webhook
   ```
   Copy the `whsec_…` value into `STRIPE_WEBHOOK_SECRET`.
3. In production, add the endpoint at
   `https://your-api-domain/api/payments/webhook` and subscribe to
   `checkout.session.completed`, `customer.subscription.created`,
   `customer.subscription.updated`, `customer.subscription.deleted`,
   and `invoice.paid`.

Prices are built inline from the plan catalog by default. To use Stripe Price
objects you created yourself, set `STRIPE_PRICE_PRO_MONTHLY` and friends.

---

## Pricing

### Plans

| Tier | Monthly | Yearly | Credits | Storage | Max length | Export |
|------|---------|--------|---------|---------|-----------|--------|
| Free | $0 | $0 | 5 once | 1 GB | 1 min | 480p, watermarked |
| Starter | $9.99 | $95.88 ($7.99/mo) | 100/mo | 10 GB | 10 min | 720p |
| Pro | $24.99 | $239.88 ($19.99/mo) | 350/mo | 50 GB | 30 min | 1080p, priority |
| Business | $59.99 | $575.88 ($47.99/mo) | 1,200/mo | 200 GB | 60 min | 4K, priority, API |
| Enterprise | $149.99 | $1,439.88 ($119.99/mo) | 4,000/mo | 1 TB | Unlimited | 8K, white label |
| Ultimate | $299.99 | $2,879.88 ($239.99/mo) | 12,000/mo | 5 TB | Unlimited | 8K+, dedicated pool, SLA |

Yearly billing saves 20%.

### Credit packs

50 / $4.99 · 100 / $8.99 · 250 / $19.99 · 500 / $34.99 · 1,000 / $59.99 ·
5,000 / $249.99 · 10,000 / $449.99. Packs never expire.

### What actions cost

Download 1–3 · Voiceover 2 per minute · Narration 5 · Subtitle extraction 2 ·
Translation 3 · Storyline 1 · Rights screen 2 · Rights clearance 3 ·
Research 5 (basic) or 20 (deep) · Priority +5.

AI video: 15 credits for 1 min at 720p, 50 for 5 min at 1080p, 200 for 20 min at
4K, 600 for 60 min at 4K, 900 for 60 min at 8K.

Failed jobs refund automatically. The rates live in one place —
`backend/app/config.py` — and both the API and the pricing page read from it.

---

## API

Full interactive docs at `/api/docs` outside production.

```
POST   /api/auth/register              POST   /api/auth/login
POST   /api/auth/refresh               POST   /api/auth/logout
GET    /api/auth/me                    POST   /api/auth/2fa/setup|enable|disable
POST   /api/auth/api-key

POST   /api/download                   POST   /api/download/probe
GET    /api/download/supported         GET    /api/download/{job_id}

POST   /api/tts/generate               GET    /api/tts/voices
POST   /api/narrate                    GET    /api/narrate/{job_id}
POST   /api/subtitles/extract          POST   /api/subtitles/translate
POST   /api/storyline/generate         POST   /api/storyline/rephrase
POST   /api/rights/scan                POST   /api/rights/remediate
POST   /api/autopilot/plan             POST   /api/autopilot/run
POST   /api/research                   GET    /api/research/{task_id}
POST   /api/video/create               GET    /api/video/config

POST   /api/storage/upload             GET    /api/storage/files
POST   /api/storage/share/{file_id}    GET    /api/storage/shared/{token}

GET    /api/payments/plans             POST   /api/payments/create-checkout
POST   /api/payments/webhook           POST   /api/payments/portal

GET    /api/admin/stats                GET    /api/admin/revenue
GET    /api/admin/users                GET    /api/admin/jobs

GET    /api/capabilities               GET    /api/health
WS     /ws?token=<access_token>
```

Business tier and above can authenticate with `X-API-Key` instead of a bearer
token.

### Live progress

Connect to `/ws?token=…` and you'll receive `job.created`, `job.progress`,
`job.completed`, `job.failed` and the `research.*` equivalents. The frontend
falls back to polling if the socket drops.

---

## Deployment

### Frontend on Vercel

```bash
vercel --prod
```

`vercel.json` serves `frontend/` statically with cache and security headers.
Point the interface at your API by adding this to `index.html`:

```html
<meta name="omnicraft-api" content="https://api.your-domain.com">
```

Then add that origin to `CORS_ORIGINS` on the backend.

### Backend on Render

- **Build:** `pip install -r requirements.txt`
- **Start:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Add a Postgres instance and set `DATABASE_URL`
- Add a persistent disk mounted at `/data`, then set `LOCAL_STORAGE_PATH=/data`
- ffmpeg is available on Render's native runtime; otherwise deploy the Dockerfile

### Backend on Oracle Cloud (or any VM)

```bash
git clone <your-repo> && cd omnicraft
cp backend/.env.example backend/.env && $EDITOR backend/.env
docker compose up -d --build
```

Put nginx or Caddy in front for TLS. Set `ENVIRONMENT=production` to disable the
docs endpoints and switch on HSTS.

### Scaling out

Set `REDIS_URL` and the `worker` service picks jobs up instead of running them in
the API process:

```bash
celery -A app.tasks.celery_app worker --loglevel=info --concurrency=2
celery -A app.tasks.celery_app beat --loglevel=info
```

---

## Security

- bcrypt password hashing, minimum 10 characters
- Short-lived access tokens, single-use rotating refresh tokens stored hashed
- TOTP two-factor with one-time recovery codes (RFC 6238, no extra dependency)
- Per-IP rate limiting, tighter on auth endpoints
- CSP that permits no third-party origins, plus nosniff, DENY framing and
  no-referrer
- Upload validation on extension, MIME type, size and magic bytes; executables
  and archives are rejected
- Path traversal is blocked at the storage layer
- Parameterised queries throughout via SQLAlchemy
- Stripe webhook signatures verified before any balance changes
- No advertising, no analytics, no third-party scripts

For production also: terminate TLS, run behind a reverse proxy, rotate
`SECRET_KEY` out of source control, and put a real antivirus engine (ClamAV) in
front of `scan_bytes` in `app/security.py`.

---

## A note on the rights module

Module 06 identifies third-party recordings in your uploads and offers three
lawful remedies: mute the flagged range, lift the music bed off the dialogue, or
swap in a track you're licensed to use.

It deliberately does not implement detection-evasion transforms — pitch or tempo
shifts applied to keep a protected recording in place while dodging a content
match. That's a different tool with a different purpose, and building it into a
product would expose both you and your users to infringement liability rather
than resolving it. If you hold a licence, keep the paperwork with the project and
publish as is; the module will tell you when a match is found and leave the
decision to you.

The same principle applies to module 01. Downloading is a normal part of media
work — your own uploads, licensed footage, Creative Commons material, content you
have permission to use — and each job is recorded against the requesting account
so operators can respond to takedown requests. Platform terms of service still
apply to your users, and it's worth saying so in your own terms.

---

## Project layout

```
backend/
  app/
    main.py          FastAPI app, middleware, WebSocket endpoint
    config.py        Settings, plan catalog, credit rates
    database.py      Async engine and session factory
    models.py        User, File, Job, CreditTransaction, ResearchTask, Plan, AuditLog
    auth.py          Passwords, JWT, TOTP
    security.py      Rate limits, headers, upload validation
    deps.py          Shared dependencies
    websocket.py     Per-user connection hub
    seed.py          Plan catalog and bootstrap admin
    tasks.py         Optional Celery workers
    routes/          One file per module, plus system and admin
    services/        Provider integrations and ffmpeg wrappers
    utils/           Credits, files, jobs, errors
  requirements.txt  .env.example  Dockerfile

frontend/
  index.html         The whole SPA shell
  css/style.css      One stylesheet, no framework
  js/                api, ui, auth, websocket, jobs, app + one file per module
  assets/            Logo and favicon (SVG, inline)

docker-compose.yml  vercel.json  .gitignore  README.md
```

## Troubleshooting

**"ffmpeg isn't installed on the server"** — install it and restart the API.
`GET /api/health` reports whether it's on the path.

**"Can't reach the API"** — the frontend defaults to `http://localhost:8000`.
Override it with the `omnicraft-api` meta tag or
`localStorage.setItem('omnicraft.api', 'https://…')`.

**Jobs stay at 0%** — with `REDIS_URL` set but no worker running, nothing picks
them up. Either start a worker or clear `REDIS_URL` to run jobs in-process. If a
worker was running and died, the API fails those jobs and refunds them on its
next boot.

**Vercel returns FUNCTION_INVOCATION_FAILED** — Vercel is trying to build the
Python backend as a serverless function. Set the project's Root Directory to
`frontend`. The backend cannot run on serverless (it needs ffmpeg, a persistent
disk, background workers and long-lived websockets); host it separately and
point the frontend at it with the `omnicraft-api` meta tag.

**CORS errors** — add your frontend origin to `CORS_ORIGINS` and restart.

**Stripe webhook 400s** — `STRIPE_WEBHOOK_SECRET` must match the endpoint you're
actually sending from. Local `stripe listen` and the dashboard endpoint have
different secrets.

## Licence

Yours to use. The dependencies carry their own licences — check `yt-dlp`, ffmpeg
and the AI provider terms before you charge money for output.
