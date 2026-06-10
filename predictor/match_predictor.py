"""Modelo de previsão de partidas via Regressão de Poisson (GLM).

Abordagem (clássica para placares de futebol — Maher 1982 / Dixon-Coles):

1. Cada partida vira DUAS observações em formato longo
   (time, oponente, mando, gols marcados).
2. Ajustamos um GLM Poisson: ``gols ~ C(time) + C(oponente) + mando``.
   Os coeficientes de ``C(time)`` capturam força de ataque e os de
   ``C(oponente)`` capturam fraqueza defensiva.
3. Para prever, estimamos λ_casa e λ_fora (gols esperados) e montamos a
   matriz de probabilidades de placar P(h, a) = Pois(h; λ_casa)·Pois(a; λ_fora).
4. Vitória/Empate/Derrota = somas das regiões da matriz; placar mais
   provável = argmax da matriz.

Alternativa: para incorporar features ricas (forma recente, fadiga, xG
móvel) basta trocar o GLM por ``xgboost.XGBRegressor`` prevendo λ de cada
lado — a interface pública desta classe não muda.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy.stats import poisson

from core.exceptions import InsufficientDataError, PredictionError
from core.logging import get_logger
from domain.entities import MatchPrediction

logger = get_logger(__name__)

MODEL_VERSION = "poisson-glm-1.0"

_REQUIRED_MATCH_COLUMNS = {
    "home_team_code", "away_team_code", "home_goals", "away_goals", "neutral_venue",
}


@dataclass(frozen=True, slots=True)
class ScorelineDistribution:
    """Matriz de probabilidades de placares exatos P[gols_casa, gols_fora]."""

    matrix: np.ndarray
    home_lambda: float
    away_lambda: float

    @property
    def prob_home_win(self) -> float:
        return float(np.tril(self.matrix, k=-1).sum())

    @property
    def prob_draw(self) -> float:
        return float(np.trace(self.matrix))

    @property
    def prob_away_win(self) -> float:
        return float(np.triu(self.matrix, k=1).sum())

    @property
    def most_likely_score(self) -> tuple[int, int]:
        home, away = np.unravel_index(int(self.matrix.argmax()), self.matrix.shape)
        return int(home), int(away)


class MatchPredictor:
    """Pipeline de ML: treina nos jogos passados e prevê partidas futuras."""

    MIN_MATCHES_PER_TEAM = 3

    def __init__(self, max_goals: int = 10) -> None:
        self._max_goals = max_goals
        self._model: sm.regression.linear_model.RegressionResultsWrapper | None = None
        self._known_teams: frozenset[str] = frozenset()

    @property
    def is_fitted(self) -> bool:
        return self._model is not None

    # ------------------------------------------------------------------ fit

    def fit(self, matches: pd.DataFrame) -> "MatchPredictor":
        """Treina o GLM Poisson com partidas já disputadas.

        Args:
            matches: DataFrame com ``home_team_code``, ``away_team_code``,
                ``home_goals``, ``away_goals`` e ``neutral_venue``.

        Raises:
            InsufficientDataError: histórico vazio ou times com poucos jogos.
            PredictionError: falha numérica no ajuste do modelo.
        """
        missing = _REQUIRED_MATCH_COLUMNS - set(matches.columns)
        if missing:
            raise PredictionError("Colunas obrigatórias ausentes", missing=sorted(missing))

        played = matches.dropna(subset=["home_goals", "away_goals"])
        if played.empty:
            raise InsufficientDataError("Nenhuma partida disputada para treinar")

        long_format = self._to_long_format(played)
        games_per_team = long_format["team"].value_counts()
        thin_teams = games_per_team[games_per_team < self.MIN_MATCHES_PER_TEAM]
        if not thin_teams.empty:
            logger.warning(
                "times_com_pouco_historico",
                extra={"context": {"teams": thin_teams.index.tolist()}},
            )

        try:
            self._model = smf.glm(
                formula="goals ~ C(team) + C(opponent) + home_advantage",
                data=long_format,
                family=sm.families.Poisson(),
            ).fit()
        except Exception as exc:
            raise PredictionError("Falha ao ajustar o GLM Poisson") from exc

        self._known_teams = frozenset(long_format["team"].unique())
        logger.info(
            "modelo_treinado",
            extra={
                "context": {
                    "matches": len(played),
                    "teams": len(self._known_teams),
                    "model_version": MODEL_VERSION,
                }
            },
        )
        return self

    # -------------------------------------------------------------- predict

    def predict(
        self,
        home_team: str,
        away_team: str,
        match_id: str,
        neutral_venue: bool = True,
    ) -> MatchPrediction:
        """Prevê probabilidades 1X2 e o placar exato mais provável.

        Args:
            home_team / away_team: códigos das seleções (como no treino).
            neutral_venue: ``True`` para campo neutro (caso geral da Copa);
                ``False`` dá vantagem de mando ao ``home_team`` (anfitriões
                EUA/México/Canadá).
        """
        distribution = self.predict_scoreline_distribution(home_team, away_team, neutral_venue)
        score = distribution.most_likely_score
        return MatchPrediction(
            match_id=match_id,
            home_team_code=home_team,
            away_team_code=away_team,
            prob_home_win=distribution.prob_home_win,
            prob_draw=distribution.prob_draw,
            prob_away_win=distribution.prob_away_win,
            expected_home_goals=distribution.home_lambda,
            expected_away_goals=distribution.away_lambda,
            most_likely_score=score,
            most_likely_score_prob=float(distribution.matrix[score]),
            model_version=MODEL_VERSION,
            generated_at=datetime.utcnow(),
        )

    def predict_scoreline_distribution(
        self, home_team: str, away_team: str, neutral_venue: bool = True
    ) -> ScorelineDistribution:
        """Calcula a matriz completa de probabilidades de placares."""
        if self._model is None:
            raise PredictionError("Modelo não treinado: chame fit() antes de predict()")
        for team in (home_team, away_team):
            if team not in self._known_teams:
                raise InsufficientDataError(
                    "Seleção sem histórico no conjunto de treino", team=team
                )

        home_lambda = self._expected_goals(home_team, away_team,
                                           home_advantage=0.0 if neutral_venue else 1.0)
        away_lambda = self._expected_goals(away_team, home_team, home_advantage=0.0)

        goals = np.arange(self._max_goals + 1)
        home_pmf = poisson.pmf(goals, home_lambda)
        away_pmf = poisson.pmf(goals, away_lambda)
        matrix = np.outer(home_pmf, away_pmf)
        matrix /= matrix.sum()  # renormaliza a massa truncada em max_goals

        return ScorelineDistribution(
            matrix=matrix, home_lambda=home_lambda, away_lambda=away_lambda
        )

    # ------------------------------------------------------------- internos

    def _expected_goals(self, team: str, opponent: str, home_advantage: float) -> float:
        assert self._model is not None
        observation = pd.DataFrame(
            {"team": [team], "opponent": [opponent], "home_advantage": [home_advantage]}
        )
        try:
            return float(self._model.predict(observation).iloc[0])
        except Exception as exc:
            raise PredictionError(
                "Falha ao estimar gols esperados", team=team, opponent=opponent
            ) from exc

    @staticmethod
    def _to_long_format(matches: pd.DataFrame) -> pd.DataFrame:
        """Converte 1 linha/partida em 2 linhas/observação (uma por equipe)."""
        # Em campo neutro nenhuma equipe recebe o termo de vantagem de mando.
        home_side = pd.DataFrame(
            {
                "team": matches["home_team_code"],
                "opponent": matches["away_team_code"],
                "goals": matches["home_goals"].astype(int),
                "home_advantage": (~matches["neutral_venue"].astype(bool)).astype(float),
            }
        )
        away_side = pd.DataFrame(
            {
                "team": matches["away_team_code"],
                "opponent": matches["home_team_code"],
                "goals": matches["away_goals"].astype(int),
                "home_advantage": 0.0,
            }
        )
        return pd.concat([home_side, away_side], ignore_index=True)
