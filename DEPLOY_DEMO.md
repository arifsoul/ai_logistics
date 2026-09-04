# Demo deployment checklist

This repo is best deployed as:

- Netlify: frontend
- Render: backend
- Supabase or Render Postgres: database

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
SUPER_USERNAME=admin
SUPER_PASSWORD=admin
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

Default demo admin credentials:

```text
username: admin
password: admin
```

This is from `SUPER_USERNAME` and `SUPER_PASSWORD`.
