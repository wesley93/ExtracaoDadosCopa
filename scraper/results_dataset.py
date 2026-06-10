"""Fonte de dados alternativa: dataset aberto de resultados internacionais.

O FBref fica atrás da Cloudflare e responde **HTTP 403 para IPs de
datacenter** (AWS, Azure, runners do GitHub Actions) — o scraping só
funciona a partir de IPs residenciais. Para que o pipeline rode em CI,
este módulo oferece um fallback: o dataset público de resultados de
seleções (martj42/international_results, licença CC0), servido via
``raw.githubusercontent.com`` — acessível de qualquer ambiente.

Colunas do CSV: ``date, home_team, away_team, home_score, away_score,
tournament, city, country, neutral``.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Final

from config.settings import ScraperSettings
from core.exceptions import ParsingError, ScraperError
from core.logging import get_logger
from domain.entities import Match, MatchStatus
from scraper.http_client import ResilientHttpClient

logger = get_logger(__name__)

RESULTS_CSV_URL: Final[str] = (
    "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
)


def build_match_id(kickoff: datetime, home: str, away: str) -> str:
    """ID determinístico de partida (mesma chave usada em todo o pipeline)."""
    return f"{kickoff.date().isoformat()}_{home}_{away}".replace(" ", "-")


def parse_results_csv(csv_text: str, since_year: int) -> list[Match]:
    """Converte o CSV do dataset aberto em entidades ``Match`` (já disputadas).

    Linhas malformadas ou sem placar são ignoradas individualmente — uma
    linha ruim não derruba a ingestão inteira.
    """
    matches: list[Match] = []
    reader = csv.DictReader(io.StringIO(csv_text))
    if reader.fieldnames is None or "date" not in reader.fieldnames:
        raise ParsingError(
            "CSV de resultados sem o cabeçalho esperado",
            fieldnames=reader.fieldnames,
        )

    for row in reader:
        try:
            kickoff = datetime.strptime(row["date"], "%Y-%m-%d")
        except (KeyError, TypeError, ValueError):
            continue
        if kickoff.year < since_year:
            continue

        home = (row.get("home_team") or "").strip()
        away = (row.get("away_team") or "").strip()
        if not home or not away:
            continue

        try:
            home_goals = int(float(row["home_score"]))
            away_goals = int(float(row["away_score"]))
        except (KeyError, TypeError, ValueError):
            continue  # partida futura, abandonada ou sem placar

        neutral = (row.get("neutral") or "").strip().lower() in {"true", "1", "yes"}
        matches.append(
            Match(
                match_id=build_match_id(kickoff, home, away),
                home_team_code=home,
                away_team_code=away,
                kickoff=kickoff,
                competition=(row.get("tournament") or "International").strip(),
                status=MatchStatus.PLAYED,
                home_goals=home_goals,
                away_goals=away_goals,
                neutral_venue=neutral,
            )
        )
    return matches


class OpenResultsDataset:
    """Baixa e converte o dataset aberto de resultados de seleções."""

    def __init__(
        self, settings: ScraperSettings, client: ResilientHttpClient | None = None
    ) -> None:
        self._settings = settings
        self._client = client

    def fetch_played_matches(self, since_year: int = 2021) -> list[Match]:
        """Baixa o CSV e retorna as partidas disputadas desde ``since_year``.

        Raises:
            ScraperError: falha de rede ao baixar o CSV.
            ParsingError: CSV em formato inesperado.
        """
        client = self._client or ResilientHttpClient(self._settings)
        owns_client = self._client is None
        try:
            csv_text = client.get(RESULTS_CSV_URL)
        except ScraperError:
            raise
        finally:
            if owns_client:
                client.close()

        matches = parse_results_csv(csv_text, since_year=since_year)
        logger.info(
            "dataset_aberto_ingerido",
            extra={"context": {"matches": len(matches), "since_year": since_year}},
        )
        return matches
