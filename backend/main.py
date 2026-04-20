"""DIAN Downloader Web — FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.db.migrate import run_migrations
from backend.db.pool import close_pool, open_pool, pool
from backend.routes import auth as auth_routes
from backend.routes import health as health_routes
from backend.routes import jobs as jobs_routes

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    open_pool()
    run_migrations(pool)
    yield
    close_pool()


app = FastAPI(title="DIAN Downloader Batuta — Web", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_routes.router)
app.include_router(auth_routes.router)
app.include_router(jobs_routes.router)


@app.get("/")
def root():
    return RedirectResponse(url="/login.html")


@app.get("/login.html", include_in_schema=False)
def login_page():
    return FileResponse(FRONTEND_DIR / "login.html")


@app.get("/register.html", include_in_schema=False)
def register_page():
    return FileResponse(FRONTEND_DIR / "register.html")


@app.get("/app.html", include_in_schema=False)
def app_page():
    return FileResponse(FRONTEND_DIR / "app.html")
