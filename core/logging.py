"""Logging estruturado em JSON (uma linha por evento).

Uso::

    from core.logging import get_logger

    logger = get_logger(__name__)
    logger.info("pagina_extraida", extra={"context": {"url": url, "status": 200}})

O campo ``context`` (dict) é mesclado no payload JSON final, permitindo
consultas estruturadas em agregadores de log (Loki, CloudWatch, ELK...).
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any


class JsonFormatter(logging.Formatter):
    """Serializa cada registro de log como um objeto JSON de linha única."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
        }
        context = getattr(record, "context", None)
        if isinstance(context, dict):
            payload.update(context)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(level: str = "INFO") -> None:
    """Configura o logger raiz com saída JSON em stdout (idempotente)."""
    root = logging.getLogger()
    root.setLevel(level.upper())

    # Evita handlers duplicados quando chamado mais de uma vez (ex.: testes).
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)

    # Bibliotecas de terceiros tendem a ser verbosas em DEBUG.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Retorna um logger nomeado já integrado à configuração global."""
    return logging.getLogger(name)
