"""Orquestrador do pipeline Copa 2026.

Etapas (cada uma pode ser pulada via flags de linha de comando):

1. **scrape**  — verifica se há dados novos no FBref e atualiza o banco;
2. **train**   — reconstrói features e treina/atualiza o ``MatchPredictor``;
3. **predict** — gera previsões para os próximos jogos e as persiste.

Uso::

    python main.py                       # pipeline completo
    python main.py --skip-scrape         # só treinar e prever (dados locais)
    python main.py --upcoming-limit 8    # prever apenas os 8 próximos jogos
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta

import pandas as pd

from config.settings import Settings, get_settings
from core.exceptions import CopaPredictorError, InsufficientDataError, ScraperError
from core.logging import get_logger, setup_logging
from domain.entities import Match, MatchPrediction, MatchStatus
from domain.repositories import MatchRepository, PredictionRepository
from predictor.feature_engine import FeatureEngine
from predictor.match_predictor import MatchPredictor
from scraper.fbref_scraper import FBrefScraper
from storage.database import Database
from storage.repositories import (
    SqlMatchRepository,
    SqlPredictionRepository,
    SqlTeamRepository,
)

logger = get_logger(__name__)

# Fontes de dados padrão (qualificatórias + torneio). Ajuste conforme a
# cobertura desejada: cada URL é uma página de competição do FBref.
DEFAULT_SOURCES: dict[str, str] = {
    "world_cup_2026_schedule": "https://fbref.com/en/comps/1/schedule/World-Cup-Scores-and-Fixtures",
    "world_cup_2026_stats": "https://fbref.com/en/comps/1/stats/World-Cup-Stats",
}

# Após este intervalo sem partidas novas, consideramos o banco "fresco"
# e pulamos o scraping (controle incremental simples).
STALENESS_THRESHOLD = timedelta(days=1)


class Pipeline:
    """Liga extração, persistência, treino e previsão."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._db = Database(settings.database_url)
        self._db.create_schema()
        self._teams = SqlTeamRepository(self._db)
        self._matches: MatchRepository = SqlMatchRepository(self._db)
        self._predictions: PredictionRepository = SqlPredictionRepository(self._db)
        self._feature_engine = FeatureEngine(
            rolling_window=settings.predictor.rolling_window
        )
        self._predictor = MatchPredictor(max_goals=settings.predictor.max_goals)

    # ----------------------------------------------------------- etapa 1

    def scrape_if_stale(self, force: bool = False) -> bool:
        """Atualiza o banco com dados do FBref se houver indício de dados novos.

        Returns:
            ``True`` se houve scraping; ``False`` se o banco estava fresco.
        """
        latest = self._matches.latest_played_kickoff()
        if not force and latest is not None and datetime.utcnow() - latest < STALENESS_THRESHOLD:
            logger.info(
                "scrape_pulado_banco_fresco",
                extra={"context": {"latest_played": latest.isoformat()}},
            )
            return False

        with FBrefScraper(self._settings.scraper) as scraper:
            fixtures = scraper.fetch_fixtures(DEFAULT_SOURCES["world_cup_2026_schedule"])
            self._persist_fixtures(fixtures)
            # squad/player stats alimentam features avançadas (xG/xA, fadiga):
            # scraper.fetch_squad_stats(DEFAULT_SOURCES["world_cup_2026_stats"])
            # scraper.fetch_player_stats(DEFAULT_SOURCES["world_cup_2026_stats"])
        return True

    def _persist_fixtures(self, fixtures: pd.DataFrame) -> None:
        """Converte o DataFrame do scraper em entidades ``Match`` e persiste."""
        matches: list[Match] = []
        for _, row in fixtures.iterrows():
            home = str(row.get("home_team", "")).strip()
            away = str(row.get("away_team", "")).strip()
            raw_date = row.get("date") or ""
            if not home or not away or not raw_date:
                continue
            kickoff = pd.to_datetime(raw_date, errors="coerce")
            if pd.isna(kickoff):
                continue
            played = pd.notna(row.get("home_goals")) and pd.notna(row.get("away_goals"))
            match_id = f"{kickoff.date().isoformat()}_{home}_{away}".replace(" ", "-")
            matches.append(
                Match(
                    match_id=match_id,
                    home_team_code=home,
                    away_team_code=away,
                    kickoff=kickoff.to_pydatetime(),
                    competition="World Cup 2026",
                    status=MatchStatus.PLAYED if played else MatchStatus.SCHEDULED,
                    home_goals=int(row["home_goals"]) if played else None,
                    away_goals=int(row["away_goals"]) if played else None,
                    neutral_venue=True,
                )
            )
        affected = self._matches.upsert_many(matches)
        logger.info("fixtures_persistidos", extra={"context": {"matches": affected}})

    # ----------------------------------------------------------- etapa 2

    def train(self) -> None:
        """Reconstrói o dataset de treino a partir do banco e ajusta o modelo."""
        played = self._matches.list_played()
        if not played:
            raise InsufficientDataError("Banco sem partidas disputadas para treino")

        training_frame = pd.DataFrame(
            {
                "home_team_code": [m.home_team_code for m in played],
                "away_team_code": [m.away_team_code for m in played],
                "home_goals": [m.home_goals for m in played],
                "away_goals": [m.away_goals for m in played],
                "neutral_venue": [m.neutral_venue for m in played],
            }
        )
        self._predictor.fit(training_frame)

    # ----------------------------------------------------------- etapa 3

    def predict_upcoming(self, limit: int | None = None) -> list[MatchPrediction]:
        """Gera e persiste previsões para os próximos jogos agendados."""
        upcoming = self._matches.list_upcoming(limit=limit)
        if not upcoming:
            logger.info("sem_jogos_futuros")
            return []

        predictions: list[MatchPrediction] = []
        for match in upcoming:
            try:
                prediction = self._predictor.predict(
                    home_team=match.home_team_code,
                    away_team=match.away_team_code,
                    match_id=match.match_id,
                    neutral_venue=match.neutral_venue,
                )
            except InsufficientDataError as exc:
                logger.warning(
                    "previsao_pulada_sem_historico",
                    extra={"context": {"match_id": match.match_id, "reason": str(exc)}},
                )
                continue
            predictions.append(prediction)

        if predictions:
            self._predictions.save_many(predictions)
        logger.info(
            "previsoes_geradas",
            extra={"context": {"count": len(predictions), "upcoming": len(upcoming)}},
        )
        return predictions

    # ------------------------------------------------------------ ciclo

    def run(
        self,
        skip_scrape: bool = False,
        force_scrape: bool = False,
        upcoming_limit: int | None = None,
    ) -> list[MatchPrediction]:
        if not skip_scrape:
            try:
                self.scrape_if_stale(force=force_scrape)
            except ScraperError:
                # Extração falhou, mas dados antigos ainda permitem prever.
                logger.exception("scrape_falhou_usando_dados_locais")
        self.train()
        return self.predict_upcoming(limit=upcoming_limit)

    def close(self) -> None:
        self._db.dispose()


def _render_report(predictions: list[MatchPrediction]) -> str:
    if not predictions:
        return "Nenhuma previsão gerada (sem jogos futuros ou sem histórico)."
    lines = ["", "=== Previsões — Copa do Mundo 2026 ===", ""]
    for p in predictions:
        score = f"{p.most_likely_score[0]} x {p.most_likely_score[1]}"
        lines.append(
            f"{p.home_team_code} vs {p.away_team_code} | "
            f"V {p.prob_home_win:.1%}  E {p.prob_draw:.1%}  D {p.prob_away_win:.1%} | "
            f"placar mais provável: {score} ({p.most_likely_score_prob:.1%})"
        )
    return "\n".join(lines)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pipeline de previsão da Copa 2026")
    parser.add_argument("--skip-scrape", action="store_true",
                        help="não acessar o FBref; usar apenas dados locais")
    parser.add_argument("--force-scrape", action="store_true",
                        help="raspar mesmo que o banco esteja atualizado")
    parser.add_argument("--upcoming-limit", type=int, default=None,
                        help="prever apenas os N próximos jogos")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    settings = get_settings()
    setup_logging(settings.log_level)

    pipeline = Pipeline(settings)
    try:
        predictions = pipeline.run(
            skip_scrape=args.skip_scrape,
            force_scrape=args.force_scrape,
            upcoming_limit=args.upcoming_limit,
        )
    except CopaPredictorError:
        logger.exception("pipeline_abortado")
        return 1
    except Exception:
        logger.exception("erro_nao_tratado")
        return 2
    finally:
        pipeline.close()

    print(_render_report(predictions))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
