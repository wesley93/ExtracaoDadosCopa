"""Configuração centralizada da aplicação.

Todos os parâmetros operacionais são lidos de variáveis de ambiente
(com defaults seguros para desenvolvimento), permitindo que o mesmo
código rode em dev (SQLite + cache local) e produção (SQL Server)
sem alteração de fonte.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw else default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


@dataclass(frozen=True, slots=True)
class ScraperSettings:
    """Parâmetros de resiliência da camada de extração."""

    pacing_seconds: float = field(
        default_factory=lambda: _env_float("SCRAPER_PACING_SECONDS", 4.0)
    )
    max_retries: int = field(default_factory=lambda: _env_int("SCRAPER_MAX_RETRIES", 5))
    backoff_base_seconds: float = field(
        default_factory=lambda: _env_float("SCRAPER_BACKOFF_BASE_SECONDS", 8.0)
    )
    timeout_seconds: float = field(
        default_factory=lambda: _env_float("SCRAPER_TIMEOUT_SECONDS", 30.0)
    )
    cache_enabled: bool = field(default_factory=lambda: _env_bool("CACHE_ENABLED", True))
    cache_dir: Path = field(
        default_factory=lambda: Path(os.getenv("CACHE_DIR", "data/cache"))
    )


@dataclass(frozen=True, slots=True)
class PredictorSettings:
    """Parâmetros do motor de features e do modelo preditivo."""

    max_goals: int = field(default_factory=lambda: _env_int("PREDICTOR_MAX_GOALS", 10))
    rolling_window: int = field(
        default_factory=lambda: _env_int("PREDICTOR_ROLLING_WINDOW", 5)
    )


@dataclass(frozen=True, slots=True)
class Settings:
    """Agregado raiz de configuração da aplicação."""

    database_url: str = field(
        default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///data/copa2026.db")
    )
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    scraper: ScraperSettings = field(default_factory=ScraperSettings)
    predictor: PredictorSettings = field(default_factory=PredictorSettings)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Retorna a configuração da aplicação (singleton por processo)."""
    return Settings()
