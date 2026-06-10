"""Cache local de páginas HTML para desenvolvimento.

Evita martelar o FBref durante iterações de parsing: a primeira execução
baixa e grava o ``.html`` em disco; as seguintes leem do arquivo. Em
produção basta desabilitar via ``CACHE_ENABLED=false``.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from core.exceptions import CacheError
from core.logging import get_logger

logger = get_logger(__name__)

_SLUG_RE = re.compile(r"[^a-zA-Z0-9]+")


class HtmlCache:
    """Cache de HTML em disco, chaveado pela URL."""

    def __init__(self, cache_dir: Path, enabled: bool = True) -> None:
        self._dir = cache_dir
        self._enabled = enabled
        if enabled:
            try:
                self._dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise CacheError("Não foi possível criar o diretório de cache",
                                 cache_dir=str(cache_dir)) from exc

    @property
    def enabled(self) -> bool:
        return self._enabled

    def get(self, url: str) -> str | None:
        """Retorna o HTML em cache para a URL, ou ``None`` se ausente."""
        if not self._enabled:
            return None
        path = self._path_for(url)
        if not path.exists():
            return None
        try:
            html = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise CacheError("Falha ao ler arquivo de cache", path=str(path)) from exc
        logger.debug("cache_hit", extra={"context": {"url": url, "path": str(path)}})
        return html

    def set(self, url: str, html: str) -> None:
        """Grava o HTML em disco para reuso futuro."""
        if not self._enabled:
            return
        path = self._path_for(url)
        try:
            path.write_text(html, encoding="utf-8")
        except OSError as exc:
            raise CacheError("Falha ao gravar arquivo de cache", path=str(path)) from exc
        logger.debug("cache_set", extra={"context": {"url": url, "path": str(path)}})

    def _path_for(self, url: str) -> Path:
        """Nome legível (slug) + hash curto para evitar colisões."""
        slug = _SLUG_RE.sub("-", url.split("//", 1)[-1]).strip("-")[:80]
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
        return self._dir / f"{slug}-{digest}.html"
