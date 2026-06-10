"""Entidades de domínio (puras, sem dependência de framework ou ORM).

São ``dataclasses`` imutáveis: a camada de persistência (storage/) é
responsável por mapeá-las de/para o banco, e a camada de extração
(scraper/) por construí-las a partir do HTML.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum


class MatchStatus(StrEnum):
    SCHEDULED = "scheduled"
    PLAYED = "played"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class Team:
    """Seleção nacional."""

    code: str  # código FIFA de 3 letras, ex.: "BRA"
    name: str
    fbref_id: str | None = None
    confederation: str | None = None  # UEFA, CONMEBOL, ...


@dataclass(frozen=True, slots=True)
class Player:
    """Jogador convocável por uma seleção."""

    fbref_id: str
    name: str
    team_code: str
    position: str | None = None
    birth_date: date | None = None


@dataclass(frozen=True, slots=True)
class TeamMatchStats:
    """Estatísticas agregadas de uma seleção em uma partida."""

    team_code: str
    match_id: str
    goals_for: int
    goals_against: int
    xg_for: float | None = None
    xg_against: float | None = None
    possession: float | None = None
    shots: int | None = None
    shots_on_target: int | None = None


@dataclass(frozen=True, slots=True)
class PlayerMatchStats:
    """Estatísticas individuais de um jogador em uma partida."""

    player_fbref_id: str
    match_id: str
    minutes: int
    goals: int = 0
    assists: int = 0
    xg: float | None = None
    xa: float | None = None
    shots: int | None = None
    key_passes: int | None = None


@dataclass(frozen=True, slots=True)
class Match:
    """Partida entre duas seleções (histórica ou agendada)."""

    match_id: str
    home_team_code: str
    away_team_code: str
    kickoff: datetime
    competition: str
    status: MatchStatus = MatchStatus.SCHEDULED
    home_goals: int | None = None
    away_goals: int | None = None
    neutral_venue: bool = True  # Copa do Mundo: neutro exceto para anfitriões

    @property
    def is_played(self) -> bool:
        return self.status is MatchStatus.PLAYED


@dataclass(frozen=True, slots=True)
class MatchPrediction:
    """Resultado do modelo para uma partida futura.

    As probabilidades referem-se sempre à perspectiva da equipe mandante
    (``home``): vitória / empate / derrota.
    """

    match_id: str
    home_team_code: str
    away_team_code: str
    prob_home_win: float
    prob_draw: float
    prob_away_win: float
    expected_home_goals: float
    expected_away_goals: float
    most_likely_score: tuple[int, int]
    most_likely_score_prob: float
    model_version: str
    generated_at: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self) -> None:
        total = self.prob_home_win + self.prob_draw + self.prob_away_win
        if not 0.99 <= total <= 1.01:
            raise ValueError(
                f"Probabilidades devem somar ~1.0; soma atual = {total:.4f}"
            )
