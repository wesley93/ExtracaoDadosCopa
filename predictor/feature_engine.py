"""Engenharia de features a partir dos dados brutos extraídos.

Transforma logs de partidas (times e jogadores) em variáveis preditivas:

- **Médias móveis de xG/xA**: forma recente ofensiva/criativa (janela
  configurável, padrão 5 jogos).
- **Índice de fadiga**: minutos acumulados nos últimos N dias, normalizado
  pelo máximo teórico — relevante numa Copa com calendário congestionado.
- **Força ofensiva/defensiva relativa**: razão entre a média de gols
  marcados/sofridos da seleção e a média global do conjunto de dados
  (parametrização clássica do modelo de Poisson).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from core.exceptions import FeatureEngineeringError
from core.logging import get_logger

logger = get_logger(__name__)

_REQUIRED_TEAM_COLUMNS = {"team_code", "kickoff", "goals_for", "goals_against"}
_REQUIRED_PLAYER_COLUMNS = {"player_id", "kickoff", "minutes"}


@dataclass(frozen=True, slots=True)
class TeamStrength:
    """Força relativa de uma seleção (1.0 = média do conjunto de dados)."""

    team_code: str
    attack: float
    defense: float  # > 1.0 significa defesa PIOR que a média (sofre mais gols)
    matches: int


class FeatureEngine:
    """Constrói as variáveis preditivas consumidas pelo ``MatchPredictor``."""

    def __init__(self, rolling_window: int = 5, fatigue_lookback_days: int = 21) -> None:
        if rolling_window < 1:
            raise FeatureEngineeringError(
                "rolling_window deve ser >= 1", rolling_window=rolling_window
            )
        self._window = rolling_window
        self._fatigue_lookback = pd.Timedelta(days=fatigue_lookback_days)

    # ------------------------------------------------------ features de time

    def rolling_team_form(self, team_matches: pd.DataFrame) -> pd.DataFrame:
        """Médias móveis de xG (feito/sofrido) e gols por seleção.

        Args:
            team_matches: uma linha por (seleção, partida), exigindo as
                colunas ``team_code``, ``kickoff``, ``goals_for``,
                ``goals_against`` e opcionalmente ``xg_for``/``xg_against``.

        Returns:
            DataFrame original acrescido das colunas ``*_rolling`` —
            calculadas com ``shift(1)`` para nunca vazar o próprio jogo
            (data leakage) para dentro da feature.
        """
        self._validate_columns(team_matches, _REQUIRED_TEAM_COLUMNS, "team_matches")

        frame = team_matches.sort_values(["team_code", "kickoff"]).copy()
        grouped = frame.groupby("team_code", sort=False)
        for source in ("goals_for", "goals_against", "xg_for", "xg_against"):
            if source not in frame.columns:
                continue
            frame[f"{source}_rolling"] = grouped[source].transform(
                lambda s: s.shift(1).rolling(self._window, min_periods=1).mean()
            )
        return frame

    def team_strengths(self, team_matches: pd.DataFrame) -> dict[str, TeamStrength]:
        """Força ofensiva/defensiva relativa de cada seleção.

        attack  = média de gols marcados da seleção / média global
        defense = média de gols sofridos da seleção / média global
        """
        self._validate_columns(team_matches, _REQUIRED_TEAM_COLUMNS, "team_matches")
        if team_matches.empty:
            raise FeatureEngineeringError("Sem partidas para calcular forças relativas")

        global_scored = float(team_matches["goals_for"].mean())
        if global_scored <= 0:
            raise FeatureEngineeringError("Média global de gols inválida",
                                          global_scored=global_scored)

        strengths: dict[str, TeamStrength] = {}
        for team_code, games in team_matches.groupby("team_code"):
            strengths[str(team_code)] = TeamStrength(
                team_code=str(team_code),
                attack=float(games["goals_for"].mean()) / global_scored,
                defense=float(games["goals_against"].mean()) / global_scored,
                matches=len(games),
            )
        logger.info("forcas_calculadas", extra={"context": {"teams": len(strengths)}})
        return strengths

    # --------------------------------------------------- features de jogador

    def player_rolling_xg_xa(self, player_matches: pd.DataFrame) -> pd.DataFrame:
        """Médias móveis de xG e xA por jogador (janela ``rolling_window``)."""
        self._validate_columns(player_matches, _REQUIRED_PLAYER_COLUMNS, "player_matches")

        frame = player_matches.sort_values(["player_id", "kickoff"]).copy()
        grouped = frame.groupby("player_id", sort=False)
        for source in ("xg", "xa", "goals", "assists"):
            if source not in frame.columns:
                continue
            frame[f"{source}_rolling"] = grouped[source].transform(
                lambda s: s.shift(1).rolling(self._window, min_periods=1).mean()
            )
        return frame

    def fatigue_index(self, player_matches: pd.DataFrame) -> pd.DataFrame:
        """Índice de fadiga em [0, 1]: minutos acumulados na janela recente.

        ``1.0`` = jogou todos os minutos possíveis (90 por jogo da própria
        equipe) nos últimos ``fatigue_lookback_days`` dias.
        """
        self._validate_columns(player_matches, _REQUIRED_PLAYER_COLUMNS, "player_matches")

        frame = player_matches.sort_values(["player_id", "kickoff"]).copy()
        frame["kickoff"] = pd.to_datetime(frame["kickoff"])

        def _per_player(games: pd.DataFrame) -> pd.Series:
            indexed = games.set_index("kickoff")["minutes"]
            cumulative = indexed.rolling(self._fatigue_lookback).sum()
            possible = indexed.rolling(self._fatigue_lookback).count() * 90.0
            return (cumulative / possible).clip(upper=1.0).reset_index(drop=True)

        frame["fatigue_index"] = (
            frame.groupby("player_id", group_keys=False)[["kickoff", "minutes"]]
            .apply(_per_player)
            .reset_index(drop=True)
        )
        return frame

    def squad_fatigue(self, player_matches: pd.DataFrame, team_of_player: pd.Series) -> pd.Series:
        """Fadiga média do elenco por seleção (agregação para nível de time)."""
        with_fatigue = self.fatigue_index(player_matches)
        with_fatigue["team_code"] = with_fatigue["player_id"].map(team_of_player)
        return with_fatigue.groupby("team_code")["fatigue_index"].mean()

    # ------------------------------------------------------------- internos

    @staticmethod
    def _validate_columns(frame: pd.DataFrame, required: set[str], name: str) -> None:
        missing = required - set(frame.columns)
        if missing:
            raise FeatureEngineeringError(
                "Colunas obrigatórias ausentes", dataframe=name, missing=sorted(missing)
            )
