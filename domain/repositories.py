"""Interfaces de persistência (Repository Pattern).

A camada de domínio define *o que* precisa ser persistido; a camada
``storage/`` decide *como* (SQLite, SQL Server, etc.). Orquestração e
modelo dependem apenas destas abstrações — nunca de SQLAlchemy direto.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime

from domain.entities import (
    Match,
    MatchPrediction,
    Player,
    PlayerMatchStats,
    Team,
    TeamMatchStats,
)


class TeamRepository(ABC):
    @abstractmethod
    def upsert_many(self, teams: Sequence[Team]) -> int:
        """Insere/atualiza seleções; retorna o nº de registros afetados."""

    @abstractmethod
    def get_by_code(self, code: str) -> Team | None: ...

    @abstractmethod
    def list_all(self) -> list[Team]: ...


class PlayerRepository(ABC):
    @abstractmethod
    def upsert_many(self, players: Sequence[Player]) -> int: ...

    @abstractmethod
    def list_by_team(self, team_code: str) -> list[Player]: ...

    @abstractmethod
    def save_match_stats(self, stats: Sequence[PlayerMatchStats]) -> int: ...

    @abstractmethod
    def get_match_stats(self, player_fbref_id: str) -> list[PlayerMatchStats]: ...


class MatchRepository(ABC):
    @abstractmethod
    def upsert_many(self, matches: Sequence[Match]) -> int: ...

    @abstractmethod
    def list_played(self, since: datetime | None = None) -> list[Match]: ...

    @abstractmethod
    def list_upcoming(self, limit: int | None = None) -> list[Match]: ...

    @abstractmethod
    def save_team_stats(self, stats: Sequence[TeamMatchStats]) -> int: ...

    @abstractmethod
    def get_team_stats(self, team_code: str) -> list[TeamMatchStats]: ...

    @abstractmethod
    def latest_played_kickoff(self) -> datetime | None:
        """Data da partida mais recente já persistida (controle incremental)."""


class PredictionRepository(ABC):
    @abstractmethod
    def save_many(self, predictions: Sequence[MatchPrediction]) -> int: ...

    @abstractmethod
    def get_latest_for_match(self, match_id: str) -> MatchPrediction | None: ...
