"""Extrator de dados de seleções e jogadores do FBref.

Fluxo de cada método público::

    URL -> cache local? -> (senão) ResilientHttpClient.get -> grava cache
        -> unwrap de comentários HTML -> BeautifulSoup -> DataFrame tipado

O scraper devolve ``pandas.DataFrame`` normalizados; a conversão para
entidades de domínio e a persistência ficam a cargo do orquestrador.
"""

from __future__ import annotations

from typing import Final

import pandas as pd

from config.settings import ScraperSettings
from core.exceptions import ParsingError, ScraperError
from core.logging import get_logger
from scraper.cache import HtmlCache
from scraper.http_client import ResilientHttpClient
from scraper.parsers import build_soup, coerce_numeric, extract_fbref_id, parse_stats_table

logger = get_logger(__name__)

BASE_URL: Final[str] = "https://fbref.com"

# Competição "WC Qualification + amistosos" varia por confederação; estes IDs
# de tabela são os padrões do FBref para páginas de competição internacional.
_SQUAD_STANDARD_TABLE: Final[str] = "stats_squads_standard_for"
_SQUAD_STANDARD_AGAINST_TABLE: Final[str] = "stats_squads_standard_against"
_PLAYER_STANDARD_TABLE: Final[str] = "stats_standard"
_SCHEDULE_TABLE_PREFIX: Final[str] = "sched"

_TEAM_NUMERIC_COLUMNS: Final[list[str]] = [
    "games", "goals", "assists", "xg", "xg_assist", "npxg", "possession",
]
_PLAYER_NUMERIC_COLUMNS: Final[list[str]] = [
    "games", "minutes", "goals", "assists", "xg", "xg_assist", "npxg",
    "shots", "shots_on_target",
]
_FIXTURE_NUMERIC_COLUMNS: Final[list[str]] = ["home_xg", "away_xg"]


class FBrefScraper:
    """Fachada de extração: seleções, jogadores e calendário de jogos."""

    def __init__(
        self,
        settings: ScraperSettings,
        client: ResilientHttpClient | None = None,
        cache: HtmlCache | None = None,
    ) -> None:
        self._settings = settings
        self._client = client or ResilientHttpClient(settings)
        self._cache = cache or HtmlCache(settings.cache_dir, enabled=settings.cache_enabled)

    # ------------------------------------------------------------------ API

    def fetch_squad_stats(self, competition_url: str) -> pd.DataFrame:
        """Estatísticas agregadas por seleção em uma competição.

        Args:
            competition_url: URL da página de estatísticas da competição,
                ex.: ``https://fbref.com/en/comps/1/stats/World-Cup-Stats``.

        Returns:
            DataFrame com uma linha por seleção (gols, xG, posse, etc.).
        """
        soup = build_soup(self._fetch_html(competition_url))
        frame = parse_stats_table(soup, _SQUAD_STANDARD_TABLE)
        frame = coerce_numeric(frame, _TEAM_NUMERIC_COLUMNS)
        frame["fbref_team_id"] = frame.get("team_href", pd.Series(dtype=str)).map(
            lambda href: extract_fbref_id(href) if isinstance(href, str) else None
        )
        logger.info(
            "squad_stats_extraidas",
            extra={"context": {"url": competition_url, "teams": len(frame)}},
        )
        return frame

    def fetch_squad_stats_against(self, competition_url: str) -> pd.DataFrame:
        """Estatísticas *sofridas* por seleção (tabela escondida em comentário).

        Esta tabela só existe dentro de ``<!-- -->`` no HTML bruto — é o caso
        que motivou o ``unwrap_html_comments``.
        """
        soup = build_soup(self._fetch_html(competition_url))
        frame = parse_stats_table(soup, _SQUAD_STANDARD_AGAINST_TABLE)
        return coerce_numeric(frame, _TEAM_NUMERIC_COLUMNS)

    def fetch_player_stats(self, competition_url: str) -> pd.DataFrame:
        """Estatísticas individuais (xG, xA, minutos) de todos os jogadores.

        A tabela de jogadores também vem comentada no HTML do FBref.
        """
        soup = build_soup(self._fetch_html(competition_url))
        frame = parse_stats_table(soup, _PLAYER_STANDARD_TABLE)
        frame = coerce_numeric(frame, _PLAYER_NUMERIC_COLUMNS)
        frame["fbref_player_id"] = frame.get("player_href", pd.Series(dtype=str)).map(
            lambda href: extract_fbref_id(href) if isinstance(href, str) else None
        )
        logger.info(
            "player_stats_extraidas",
            extra={"context": {"url": competition_url, "players": len(frame)}},
        )
        return frame

    def fetch_fixtures(self, schedule_url: str) -> pd.DataFrame:
        """Calendário de jogos (passados e futuros) de uma competição.

        Args:
            schedule_url: ex. ``https://fbref.com/en/comps/1/schedule/...``.

        Returns:
            DataFrame com data, mandante, visitante, placar e xG por jogo.
        """
        soup = build_soup(self._fetch_html(schedule_url))
        table = soup.find("table", id=lambda value: bool(
            value and value.startswith(_SCHEDULE_TABLE_PREFIX)
        ))
        if table is None or not table.get("id"):
            raise ParsingError("Tabela de calendário não encontrada", url=schedule_url)

        frame = parse_stats_table(soup, str(table["id"]))
        frame = coerce_numeric(frame, _FIXTURE_NUMERIC_COLUMNS)
        if "score" in frame.columns:
            scores = frame["score"].str.extract(r"(?P<home_goals>\d+)\D+(?P<away_goals>\d+)")
            frame["home_goals"] = pd.to_numeric(scores["home_goals"], errors="coerce")
            frame["away_goals"] = pd.to_numeric(scores["away_goals"], errors="coerce")
        logger.info(
            "fixtures_extraidos",
            extra={"context": {"url": schedule_url, "matches": len(frame)}},
        )
        return frame

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "FBrefScraper":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ------------------------------------------------------------- internos

    def _fetch_html(self, url: str) -> str:
        """Resolve o HTML via cache local ou rede, com erros contextualizados."""
        cached = self._cache.get(url)
        if cached is not None:
            return cached
        try:
            html = self._client.get(url)
        except ScraperError:
            raise
        except Exception as exc:  # blindagem: nunca vazar exceção crua da lib
            raise ScraperError("Falha inesperada ao baixar página", url=url) from exc
        self._cache.set(url, html)
        return html
