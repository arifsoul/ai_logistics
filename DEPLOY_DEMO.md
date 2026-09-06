# Demo deployment checklist

This repo is best deployed as:

- Netlify: frontend
- **Hugging Face Spaces (Docker)** or Render: backend
- Supabase or Render Postgres: database

> **Hugging Face Spaces — backend Docker (recommended alternative to Render):**
> 1. Buat Space: https://huggingface.co/new-space → SDK `Docker` → Blank.
> 2. Push repo ini ke Space remote (`git remote add space https://huggingface.co/spaces/<user>/<space>` lalu `git push space main`). HF build `Dockerfile` otomatis (port `7860`).
> 3. In the Space **Settings → Variables and secrets**, set `DATABASE_URL` (Supabase pooler `postgresql+psycopg://...`), `API_KEY`, `AI_BASE_URL`, `AI_MODEL`, `EMBEDDING_MODEL`, `EMBEDDING_DIM`, `SECRET_KEY`, and `CORS_ORIGINS` (the Netlify URL plus `https://<user>-<space>.hf.space`).
> 4. Seed once from a trusted machine: `DATABASE_URL=<supabase> python -m backend.seed --superadmin-password "<strong-password>"`.
> 5. Set `NEXT_PUBLIC_API_URL=https://<user>-<space>.hf.space` di Netlify. Cek `GET /` dan `/docs` di Space URL.
> Frontmatter `sdk: docker` + `app_port: 7860` sudah di `README.md`; `Dockerfile` jalankan `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`.

## 1) Deploy database

### Option A: Supabase (recommended for demo)
1. Create a new Supabase project.
2. In SQL editor, run:

```sql
create extension if not exists vector;
```

3. Copy the Postgres connection string.
4. Put it into the backend environment as `DATABASE_URL`.

### Option B: Render Postgres
1. Add a PostgreSQL database in Render.
2. Render will provide a `DATABASE_URL` connection string.
3. In the database SQL console, run:

```sql
create extension if not exists vector;
```

## 2) Deploy backend on Render

1. Connect this repository to Render.
2. Use `render.yaml` at the repo root.
3. Fill these env vars in the Render dashboard:

```env
API_KEY=your_google_ai_key
AI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
AI_MODEL=gemini-flash-latest
EMBEDDING_MODEL=gemini-embedding-001
EMBEDDING_DIM=3072
DATABASE_URL=postgresql+psycopg://...your_db...
SQL_TIMEOUT_MS=5000
MAX_UNIQUE_VALUES=50
CORS_ORIGINS=https://your-netlify-site.netlify.app
SECRET_KEY=replace_with_long_random_secret
```

4. Deploy the service.
5. Verify the app is up on `/docs`.

## 3) Seed the database

After the backend is live, run once:

```bash
python -m backend.seed
```

This creates the `orders` table and vector metadata.

## 4) Deploy frontend to Netlify

1. Use the repo root as the GitHub repo.
2. In Netlify, set site root to `frontend`.
3. Build command: `npm run build`
4. Publish directory: `frontend/.next`
5. Set env var:

```env
NEXT_PUBLIC_API_URL=https://your-render-backend-url.onrender.com
```

6. Deploy.

## 5) Final CORS and auth

Update backend `CORS_ORIGINS` to include your Netlify frontend URL, for example:

```env
CORS_ORIGINS=https://your-app.netlify.app
```

## 6) Login credentials

Canonical superadmin credentials:

```text
username: super@admin.com
password: the password supplied to `backend.seed`
```

The password is stored as an Argon2 hash in PostgreSQL, not in environment
variables.
