"""Main FastAPI entrypoint for the Laika operational management system."""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from setrem_estagio_canis.api import auth, web
from setrem_estagio_canis.api.web import calculate_metrics
from setrem_estagio_canis.core.config import SEED_DEMO_DATA
from setrem_estagio_canis.database.models import Base
from setrem_estagio_canis.database.repository import seed_initial_data
from setrem_estagio_canis.database.session import SessionLocal, engine

_LOGGER = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
STATIC_DIR = BASE_DIR / "static"


def init_database() -> None:
    """Apply Alembic migrations (or create_all in tests) and seed if enabled."""
    ini_path = PROJECT_ROOT / "alembic.ini"
    if not os.getenv("TESTING") and ini_path.exists():
        try:
            alembic_cfg = Config(str(ini_path))
            alembic_cfg.set_main_option(
                "script_location", str(PROJECT_ROOT / "alembic")
            )
            command.upgrade(alembic_cfg, "head")
        except Exception as exc:
            _LOGGER.error("Falha ao rodar migracoes Alembic: %s", exc)
            Base.metadata.create_all(bind=engine)
    else:
        Base.metadata.create_all(bind=engine)

    if SEED_DEMO_DATA:
        with SessionLocal() as db:
            seed_initial_data(db)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Ensure database schema and seed data exist on startup."""
    init_database()
    yield


app = FastAPI(
    title="Laika — Gestao Operacional",
    description=(
        "Sistema de gestao de resgates, prontuarios, insumos e financeiro "
        "da ONG Patas e Pelos"
    ),
    version="0.2.0",
    lifespan=lifespan,
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(auth.router)
app.include_router(web.router)

__all__ = ["app", "calculate_metrics", "init_database"]


if __name__ == "__main__":
    import uvicorn

    _LOGGER.info("Iniciando Laika na porta 8000...")
    uvicorn.run(
        "setrem_estagio_canis.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )
