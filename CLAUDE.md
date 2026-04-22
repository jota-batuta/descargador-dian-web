# Batuta AI · DIAN Downloader — Web Service (CLAUDE.md)

Fork del proyecto desktop `DESCARGADOR DIAN WINDOWS` expuesto como servicio web, desplegado en `descargasdian.batutaai.com`.

## Visual identity

Todo cambio visual (paleta, tipografía, logo, layout) debe seguir [DESIGN.md](./DESIGN.md). El sistema hereda de `batuta-flow` (Batuta AI canónico). Reglas duras:

- El baton del logo es siempre cobalto `#4D5CFF` — no recolorear.
- El logo en cada header enlaza a `https://www.batutaai.com` en nueva pestaña.
- Tokens viven en `frontend/static/brand.css`; no hardcodear hex en HTML.
- Dark-mode first — no introducir light-mode sin alinear con el sistema padre.
- Inter + JetBrains Mono vía Google Fonts; no añadir familias sin actualizar `DESIGN.md`.

## Stack

| Capa | Tecnología |
|---|---|
| Backend | FastAPI 0.115 + uvicorn |
| Auth | PyJWT (HS256, 24h) + bcrypt |
| SSE | sse-starlette |
| DB | PostgreSQL (psycopg3) — misma BD que registration_api |
| Download engine | dian_core/ + dian_processes/ (no modificar) |
| Frontend | HTML5 + vanilla JS (sin framework) |

## Estructura

```
backend/
  main.py          ← FastAPI app entry point
  auth.py          ← bcrypt + JWT helpers
  job_manager.py   ← JobStore in-memory
  worker.py        ← semáforo + run_unattended bridge
  zip_packager.py  ← agrupa .zip + Excel en un ZIP final
  db/
    pool.py        ← psycopg3 ConnectionPool
    migrate.py     ← CREATE TABLE web_users IF NOT EXISTS
    users.py       ← create_user, get_user_by_email, is_trial_active
  routes/
    auth.py        ← /auth/register, /auth/login, /auth/logout, /auth/me
    jobs.py        ← POST /api/jobs, GET /stream, GET /download
    health.py      ← GET /health
frontend/
  login.html
  register.html
  app.html
dian_core/         ← copiado del desktop, NO modificar
dian_processes/    ← copiado del desktop, NO modificar
```

## Dev setup

```bash
cd "E:/BATUTA PROJECTS/DESCARGADOR DIAN WEB"
python -m venv .venv && .venv/Scripts/activate
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env  # editar DATABASE_URL y JWT_SECRET
uvicorn backend.main:app --reload
```

## Feature folder convention

Características nuevas van en `backend/` o `frontend/` según corresponda.
No crear SPEC.md ni CLAUDE.md en la raíz para features individuales.

## Reglas de negocio

- Trial: 120 días desde el registro → columna `trial_expires` en `web_users`
- Auth DIAN: el usuario copia su token URL manualmente (~60 min de vida)
- Jobs: aislados por usuario (`job.user_email`); un usuario no puede ver jobs de otro
- Cleanup: temp dirs se borran automáticamente 2h después de completar
- `dian_core/` y `dian_processes/`: NO modificar — son el núcleo probado del desktop

## Mandatory Skills (Batuta ecosystem)

Este repo hereda las reglas del ecosistema Batuta AI. Invocar cuando aplique:

- **`research-first-dev`** — antes de escribir código que importe cualquier librería/API externa no verificada esta sesión. Añadir comentario `# Source: <url> (verified YYYY-MM-DD, <lib>@<version>)` en el import site.
- **`notion-kb-workflow`** — `--read` al inicio de sesión, `--append` al cierre de sesión productiva.
- **`batuta-project-hygiene`** — `mode=feature-init <nombre>` cuando el operador describa una nueva feature. No crear `CLAUDE.md`/`SPEC.md` nuevos manualmente.

## Commits & PRs

- Commits atómicos, mensaje en inglés explicando el *por qué*. Sin `Co-Authored-By: Claude`.
- Ramas: `feature/<name>` para features, `fix/<name>` para bugs.
- PRs abiertos vía `gh pr create`. Merge manual por jota-batuta salvo autorización explícita.
- Nunca `git add -A`. Añadir archivos por nombre.
