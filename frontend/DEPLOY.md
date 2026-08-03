> This is the **full project**: backend, frontend, and deploy config.
> Upload the contents of this folder to your repository root, so that
> `backend/`, `frontend/` and `render.yaml` sit at the top.

# OMNICRAFT API — deploying on Render

## Uploading to GitHub — read this first

The **`app` folder must be in your repository**. GitHub's "choose your files"
picker cannot select folders, so clicking it silently uploads only the loose
files and skips `app/` entirely. The build then succeeds and the service dies
at startup with `ModuleNotFoundError: No module named 'app'`.

**Drag the `app` folder** from your file manager onto the GitHub upload area
instead. It should expand into ~46 files (`app/main.py`, `app/routes/auth.py`,
and so on).

Your repository root must end up looking exactly like this:

```
backend/
├── app/             <- the folder people miss
├── Dockerfile
├── requirements.txt
└── .env.example
frontend/
render.yaml
```

If `app/` is missing, the build now stops with a clear message rather than
failing after deploy.


## Settings

| Field | Value |
|---|---|
| Language | **Docker** (not Python 3 — the media tools need system packages) |
| Branch | `main` |
| **Root Directory** | `backend` |
| Dockerfile Path | `./backend/Dockerfile` |
| Health Check Path | `/api/health` |

## Environment variables

Required:

| Key | Value |
|---|---|
| `SECRET_KEY` | click **Generate** |
| `ENVIRONMENT` | `production` |
| `CORS_ORIGINS` | your frontend origin, e.g. `https://omnicraft-866j.vercel.app` |
| `FRONTEND_BASE_URL` | same as above |
| `PUBLIC_BASE_URL` | this service's URL, e.g. `https://omnicraft.onrender.com` |

Everything else is optional. Provider keys (`OPENAI_API_KEY`, `ELEVENLABS_API_KEY`,
`STRIPE_SECRET_KEY`, and so on) can be added later — modules without a key report
themselves as unavailable rather than failing the boot.

## Checking it worked

Open `https://<your-service>.onrender.com/api/health`. A healthy service returns:

```json
{"status": "ok", "database": true, "ffmpeg": true}
```

Then `/api/capabilities` lists every module and what each one still needs.

## Free tier caveats

- **No persistent disk.** Uploads and the SQLite database are wiped on every
  deploy and restart. Add a Postgres instance and a disk for anything real.
- **Sleeps after inactivity.** The first request after idling takes ~50 seconds.
- **Renders are slow.** Long video jobs on a free instance may hit the request
  timeout. A paid instance plus a Redis-backed worker is the real path.

## Connecting the frontend

Add this to `frontend/index.html` inside `<head>`, then redeploy the frontend:

```html
<meta name="omnicraft-api" content="https://your-service.onrender.com">
```

Without it the frontend calls its own origin and every request 404s.
