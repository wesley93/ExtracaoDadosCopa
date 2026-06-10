"""Fábrica de engine/sessões SQLAlchemy.

A string de conexão vem de ``DATABASE_URL``; trocar de SQLite para
SQL Server é apenas trocar a URL (``mssql+pyodbc://...``) — nenhum
código desta camada precisa mudar.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from core.exceptions import StorageError
from core.logging import get_logger
from storage.models import Base

logger = get_logger(__name__)


class Database:
    """Encapsula engine, criação de schema e escopo transacional."""

    def __init__(self, database_url: str, echo: bool = False) -> None:
        self._url = database_url
        if database_url.startswith("sqlite:///"):
            # Garante que o diretório do arquivo .db exista.
            db_path = Path(database_url.removeprefix("sqlite:///"))
            db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._engine = create_engine(database_url, echo=echo, future=True)
        except SQLAlchemyError as exc:
            raise StorageError("Falha ao criar engine de banco", url=self._safe_url()) from exc
        self._session_factory = sessionmaker(
            bind=self._engine, expire_on_commit=False, future=True
        )

    def create_schema(self) -> None:
        """Cria as tabelas que ainda não existem (idempotente)."""
        try:
            Base.metadata.create_all(self._engine)
        except SQLAlchemyError as exc:
            raise StorageError("Falha ao criar schema", url=self._safe_url()) from exc
        logger.info("schema_verificado", extra={"context": {"url": self._safe_url()}})

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Escopo transacional: commit no sucesso, rollback em exceção."""
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError("Transação revertida por erro de banco") from exc
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        self._engine.dispose()

    def _safe_url(self) -> str:
        """URL sem credenciais, para uso seguro em logs."""
        return self._engine.url.render_as_string(hide_password=True) \
            if hasattr(self, "_engine") else "<engine não inicializada>"
