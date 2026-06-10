"""Cliente HTTP resiliente para scraping educado.

Implementa as três defesas exigidas pelo FBref:

1. **Pacing**: intervalo mínimo configurável (padrão 4 s) entre requisições,
   medido a partir do fim da última chamada.
2. **Exponential backoff** em HTTP 429: respeita o header ``Retry-After``
   quando presente; caso contrário usa ``base * 2 ** tentativa`` com jitter.
3. **Rotação de User-Agent**: cada requisição usa um header diferente do pool.
"""

from __future__ import annotations

import random
import time

import requests

from config.settings import ScraperSettings
from core.exceptions import RateLimitError, ScraperError
from core.logging import get_logger

logger = get_logger(__name__)

_USER_AGENTS: tuple[str, ...] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:126.0) Gecko/20100101 Firefox/126.0",
)


class ResilientHttpClient:
    """Wrapper de ``requests.Session`` com pacing, backoff e rotação de headers."""

    def __init__(self, settings: ScraperSettings) -> None:
        self._settings = settings
        self._session = requests.Session()
        self._last_request_at: float = 0.0

    # ------------------------------------------------------------------ API

    def get(self, url: str) -> str:
        """Faz GET com resiliência total e retorna o corpo como texto.

        Raises:
            RateLimitError: 429 persistente após esgotar as tentativas.
            ScraperError: erro de rede ou status HTTP != 2xx não recuperável.
        """
        last_retry_after: float | None = None

        for attempt in range(self._settings.max_retries + 1):
            self._respect_pacing()
            headers = self._build_headers()
            try:
                response = self._session.get(
                    url, headers=headers, timeout=self._settings.timeout_seconds
                )
            except requests.RequestException as exc:
                self._last_request_at = time.monotonic()
                if attempt >= self._settings.max_retries:
                    raise ScraperError("Erro de rede ao acessar URL", url=url) from exc
                wait = self._backoff_delay(attempt)
                logger.warning(
                    "erro_de_rede_retry",
                    extra={"context": {"url": url, "attempt": attempt, "wait_s": wait}},
                )
                time.sleep(wait)
                continue

            self._last_request_at = time.monotonic()

            if response.status_code == 429:
                last_retry_after = self._parse_retry_after(response)
                wait = last_retry_after or self._backoff_delay(attempt)
                logger.warning(
                    "http_429_backoff",
                    extra={"context": {"url": url, "attempt": attempt, "wait_s": wait}},
                )
                if attempt >= self._settings.max_retries:
                    break
                time.sleep(wait)
                continue

            if response.status_code >= 400:
                raise ScraperError(
                    "Resposta HTTP de erro", url=url, status=response.status_code
                )

            logger.info(
                "pagina_obtida",
                extra={
                    "context": {
                        "url": url,
                        "status": response.status_code,
                        "bytes": len(response.content),
                    }
                },
            )
            return response.text

        raise RateLimitError(
            "HTTP 429 persistente: limite de tentativas esgotado",
            retry_after=last_retry_after,
            url=url,
            attempts=self._settings.max_retries + 1,
        )

    def close(self) -> None:
        self._session.close()

    # ------------------------------------------------------------- internos

    def _respect_pacing(self) -> None:
        """Garante o intervalo mínimo entre requisições consecutivas."""
        elapsed = time.monotonic() - self._last_request_at
        remaining = self._settings.pacing_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def _build_headers(self) -> dict[str, str]:
        """Monta headers com User-Agent rotacionado a cada requisição."""
        return {
            "User-Agent": random.choice(_USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8",
            "Connection": "keep-alive",
        }

    def _backoff_delay(self, attempt: int) -> float:
        """Backoff exponencial com jitter: base * 2^tentativa + U(0, 1)."""
        return self._settings.backoff_base_seconds * (2**attempt) + random.uniform(0.0, 1.0)

    @staticmethod
    def _parse_retry_after(response: requests.Response) -> float | None:
        raw = response.headers.get("Retry-After")
        if raw is None:
            return None
        try:
            return float(raw)
        except ValueError:
            return None
