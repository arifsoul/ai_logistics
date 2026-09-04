# Supabase + Netlify setup for this monorepo

Follow these steps to connect the backend to Supabase Postgres and deploy the frontend to Netlify.

## 1) Create Supabase project

1. Open https://supabase.com and create a new project.
2. Copy the project URL and the anon/service role values from the dashboard.
3. In the SQL editor, run the project migration or manually create the required extension:

```sql
create extension if not exists vector;
```

4. Make sure the database user has permission to create tables and write to the public schema.

## 2) Prepare the backend env

Use the values from your Supabase project in the root `.env` file:

```env
API_KEY=your_google_ai_key
AI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
AI_MODEL=gemini-flash-latest
EMBEDDING_MODEL=gemini-embedding-001
EMBEDDING_DIM=3072

DATABASE_URL=postgresql+psycopg://postgres:YOUR_SUPABASE_DB_PASSWORD@db.YOUR_PROJECT_REF.supabase.co:5432/postgres
SQL_TIMEOUT_MS=5000
MAX_UNIQUE_VALUES=50

CORS_ORIGINS=https://your-netlify-site.netlify.app

SECRET_KEY=replace_with_long_random_secret
SUPER_USERNAME=admin
SUPER_PASSWORD=admin
```

Important:
- Use the Supabase connection string, not the anon key.
- Keep the driver as `psycopg` v3.
- Use the actual database password from the Supabase project.

## 3) Seed the database

From the project root:

```powershell
python -m backend.seed
```

This loads the CSV into `orders` and embeds the schema metadata into `schema_docs`.

## 4) Run backend locally

```powershell
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Verify:
- http://127.0.0.1:8000/docs

## 5) Configure the frontend

In `frontend/.env.local`:

```env
NEXT_PUBLIC_API_URL=https://your-api-domain.example.com
```

For local development:

```env
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
```

## 6) Deploy backend

The repository includes an API-only backend, so deploy it to any host that can run FastAPI + Postgres.

Examples:
- Render
- Railway
- Fly.io
- Azure App Service
- VPS with uvicorn + systemd

For a typical uvicorn deployment:

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Then set `CORS_ORIGINS` to include your Netlify frontend domain.

## 7) Deploy frontend to Netlify

1. Push the repo to GitHub.
2. In Netlify, create a new site from the repo.
3. Configure the site:
   - Base directory: `frontend`
   - Build command: `npm run build`
   - Publish directory: `frontend/.next`
4. Add environment variable:
   - `NEXT_PUBLIC_API_URL=https://your-api-domain.example.com`
5. Deploy.

## 8) Netlify project config

The repo already contains:

```toml
[build]
  base = "frontend"
  command = "npm run build"
  publish = ".next"

[build.environment]
  NEXT_PUBLIC_API_URL = "https://your-api-domain.example.com"

[[plugins]]
  package = "@netlify/plugin-nextjs"
```

This is the correct pattern for a monorepo where the frontend lives under `frontend/` and the backend lives at the repo root.

## 9) Important notes

- The frontend and backend are separate origins, so the backend must allow the Netlify origin in `CORS_ORIGINS`.
- The `orders` table and `schema_docs` table are created automatically by the app startup and seed step.
- The database user should be treated as a read-only application user in production for the SQL execution path, even though the app writes auth/chat tables and seed data.
