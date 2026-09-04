# frontend — Logistics AI frontend

Next.js (App Router) UI for the FastAPI backend in the repository root. See the
root `README.md` for the full stack and the backend setup.

```powershell
npm install
Copy-Item .env.example .env.local   # NEXT_PUBLIC_API_URL
npm run dev
```

The backend must be running on `NEXT_PUBLIC_API_URL` (default
`http://127.0.0.1:8000`) and must list this origin in `CORS_ORIGINS`.

## Routes

| Route | Notes |
| --- | --- |
| `/` | Redirects to `/chat`. |
| `/login` | Login and register, toggled in place. |
| `/chat` | The only question input. Streams narrative + table + chart, keeps history. |
| `/dashboard` | KPI cards and charts only. |
| `/admin` | User list, create user, change role. Admin and superadmin only. |

Everything under `app/(app)/` is behind the auth gate in `components/NavBar.tsx`:
no token means a redirect to `/login`.

## Structure

- `lib/api.ts` — API base URL, token/role in `localStorage`, `apiFetch`/`api`, `login`/`register`/`me`.
- `lib/frames.ts` — NDJSON frame types and the `readFrames` async generator.
- `components/ChartCanvas.tsx` — Chart.js wrapper. Destroys the chart on cleanup so a re-render cannot hit "Canvas is already in use".
- `components/DataTable.tsx` — table for query results.
- `components/NavBar.tsx` — nav, session check, log out.

## Scripts

```powershell
npm run dev     # Turbopack dev server
npm run lint    # eslint
npm run build   # production build
npx tsc --noEmit
```

Tailwind 4 is configured inside `app/globals.css` (`@import "tailwindcss"` plus
`@theme inline`); there is no `tailwind.config.*`.

## Deploy (Netlify)

`netlify.toml` sets base `frontend`, `npm run build`, and `@netlify/plugin-nextjs`.
Set `NEXT_PUBLIC_API_URL` in the Netlify environment to the deployed API origin,
and add the Netlify URL to the backend's `CORS_ORIGINS`.
