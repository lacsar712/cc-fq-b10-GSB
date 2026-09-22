from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import router
from app.database import Base, engine


def _ensure_columns() -> None:
    """Idempotent lightweight migration for pre-existing dev databases (no Alembic)."""
    with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            conn.execute(
                text(
                    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS "
                    "remark VARCHAR(512) NOT NULL DEFAULT ''"
                )
            )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    _ensure_columns()
    yield


app = FastAPI(title="FASTQ QC Pipeline Console", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
