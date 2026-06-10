"""Hierarquia de exceções do domínio.

Toda exceção da aplicação herda de :class:`CopaPredictorError` e carrega
um dicionário ``context`` com metadados estruturados (URL, tabela, seleção,
etc.) que são serializados nos logs JSON — facilitando o diagnóstico em
produção sem depender de mensagens de texto livre.
"""

from __future__ import annotations

from typing import Any


class CopaPredictorError(Exception):
    """Exceção base de toda a aplicação."""

    def __init__(self, message: str, **context: Any) -> None:
        super().__init__(message)
        self.message = message
        self.context: dict[str, Any] = context

    def __str__(self) -> str:
        if not self.context:
            return self.message
        details = ", ".join(f"{key}={value!r}" for key, value in self.context.items())
        return f"{self.message} ({details})"


# --- Extração ---------------------------------------------------------------


class ScraperError(CopaPredictorError):
    """Falha genérica na camada de extração (rede, HTTP, etc.)."""


class RateLimitError(ScraperError):
    """O servidor respondeu HTTP 429 e o limite de tentativas foi esgotado."""

    def __init__(self, message: str, retry_after: float | None = None, **context: Any) -> None:
        super().__init__(message, retry_after=retry_after, **context)
        self.retry_after = retry_after


class ParsingError(ScraperError):
    """O HTML foi obtido, mas a estrutura esperada (tabela/coluna) não existe."""


class CacheError(ScraperError):
    """Falha ao ler ou gravar o cache local de HTML."""


# --- Persistência -----------------------------------------------------------


class StorageError(CopaPredictorError):
    """Falha na camada de persistência (conexão, integridade, transação)."""


# --- Previsão ---------------------------------------------------------------


class PredictionError(CopaPredictorError):
    """Falha genérica no pipeline de previsão."""


class FeatureEngineeringError(PredictionError):
    """Dados brutos não puderam ser transformados em features válidas."""


class InsufficientDataError(PredictionError):
    """Não há histórico suficiente para treinar ou prever com confiança."""
