"""Implementações SQLAlchemy das interfaces de ``domain/repositories.py``.

Única camada que conhece o ORM: recebe e devolve entidades de domínio,
fazendo o mapeamento de/para os modelos de ``storage/models.py``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select

from domain.entities import (
    Match,
    MatchPrediction,
    MatchStatus,
    Player,
    PlayerMatchStats,
    Team,
    TeamMatchStats,
)
from domain.repositories import (
    MatchRepository,
    PlayerRepository,
    PredictionRepository,
    TeamRepository,
)
from storage.database import Database
from storage.models import (
    MatchModel,
    PlayerMatchStatsModel,
    PlayerModel,
    PredictionModel,
    TeamMatchStatsModel,
    TeamModel,
)


class SqlTeamRepository(TeamRepository):
    def __init__(self, database: Database) -> None:
        self._db = database

    def upsert_many(self, teams: Sequence[Team]) -> int:
        with self._db.session() as session:
            for team in teams:
                session.merge(
                    TeamModel(
                        code=team.code,
                        name=team.name,
                        fbref_id=team.fbref_id,
                        confederation=team.confederation,
                    )
                )
        return len(teams)

    def get_by_code(self, code: str) -> Team | None:
        with self._db.session() as session:
            row = session.get(TeamModel, code)
            return self._to_entity(row) if row else None

    def list_all(self) -> list[Team]:
        with self._db.session() as session:
            rows = session.scalars(select(TeamModel).order_by(TeamModel.code)).all()
            return [self._to_entity(row) for row in rows]

    @staticmethod
    def _to_entity(row: TeamModel) -> Team:
        return Team(
            code=row.code,
            name=row.name,
            fbref_id=row.fbref_id,
            confederation=row.confederation,
        )


class SqlPlayerRepository(PlayerRepository):
    def __init__(self, database: Database) -> None:
        self._db = database

    def upsert_many(self, players: Sequence[Player]) -> int:
        with self._db.session() as session:
            for player in players:
                session.merge(
                    PlayerModel(
                        fbref_id=player.fbref_id,
                        name=player.name,
                        team_code=player.team_code,
                        position=player.position,
                        birth_date=player.birth_date,
                    )
                )
        return len(players)

    def list_by_team(self, team_code: str) -> list[Player]:
        with self._db.session() as session:
            rows = session.scalars(
                select(PlayerModel).where(PlayerModel.team_code == team_code)
            ).all()
            return [
                Player(
                    fbref_id=row.fbref_id,
                    name=row.name,
                    team_code=row.team_code,
                    position=row.position,
                    birth_date=row.birth_date,
                )
                for row in rows
            ]

    def save_match_stats(self, stats: Sequence[PlayerMatchStats]) -> int:
        with self._db.session() as session:
            for stat in stats:
                existing = session.scalar(
                    select(PlayerMatchStatsModel).where(
                        PlayerMatchStatsModel.player_fbref_id == stat.player_fbref_id,
                        PlayerMatchStatsModel.match_id == stat.match_id,
                    )
                )
                row = existing or PlayerMatchStatsModel(
                    player_fbref_id=stat.player_fbref_id, match_id=stat.match_id
                )
                row.minutes = stat.minutes
                row.goals = stat.goals
                row.assists = stat.assists
                row.xg = stat.xg
                row.xa = stat.xa
                row.shots = stat.shots
                row.key_passes = stat.key_passes
                session.add(row)
        return len(stats)

    def get_match_stats(self, player_fbref_id: str) -> list[PlayerMatchStats]:
        with self._db.session() as session:
            rows = session.scalars(
                select(PlayerMatchStatsModel).where(
                    PlayerMatchStatsModel.player_fbref_id == player_fbref_id
                )
            ).all()
            return [
                PlayerMatchStats(
                    player_fbref_id=row.player_fbref_id,
                    match_id=row.match_id,
                    minutes=row.minutes,
                    goals=row.goals,
                    assists=row.assists,
                    xg=row.xg,
                    xa=row.xa,
                    shots=row.shots,
                    key_passes=row.key_passes,
                )
                for row in rows
            ]


class SqlMatchRepository(MatchRepository):
    def __init__(self, database: Database) -> None:
        self._db = database

    def upsert_many(self, matches: Sequence[Match]) -> int:
        with self._db.session() as session:
            for match in matches:
                session.merge(
                    MatchModel(
                        match_id=match.match_id,
                        home_team_code=match.home_team_code,
                        away_team_code=match.away_team_code,
                        kickoff=match.kickoff,
                        competition=match.competition,
                        status=match.status.value,
                        home_goals=match.home_goals,
                        away_goals=match.away_goals,
                        neutral_venue=match.neutral_venue,
                    )
                )
        return len(matches)

    def list_played(self, since: datetime | None = None) -> list[Match]:
        with self._db.session() as session:
            query = select(MatchModel).where(MatchModel.status == MatchStatus.PLAYED.value)
            if since is not None:
                query = query.where(MatchModel.kickoff >= since)
            rows = session.scalars(query.order_by(MatchModel.kickoff)).all()
            return [self._to_entity(row) for row in rows]

    def list_upcoming(self, limit: int | None = None) -> list[Match]:
        with self._db.session() as session:
            query = (
                select(MatchModel)
                .where(MatchModel.status == MatchStatus.SCHEDULED.value)
                .order_by(MatchModel.kickoff)
            )
            if limit is not None:
                query = query.limit(limit)
            rows = session.scalars(query).all()
            return [self._to_entity(row) for row in rows]

    def save_team_stats(self, stats: Sequence[TeamMatchStats]) -> int:
        with self._db.session() as session:
            for stat in stats:
                existing = session.scalar(
                    select(TeamMatchStatsModel).where(
                        TeamMatchStatsModel.team_code == stat.team_code,
                        TeamMatchStatsModel.match_id == stat.match_id,
                    )
                )
                row = existing or TeamMatchStatsModel(
                    team_code=stat.team_code, match_id=stat.match_id
                )
                row.goals_for = stat.goals_for
                row.goals_against = stat.goals_against
                row.xg_for = stat.xg_for
                row.xg_against = stat.xg_against
                row.possession = stat.possession
                row.shots = stat.shots
                row.shots_on_target = stat.shots_on_target
                session.add(row)
        return len(stats)

    def get_team_stats(self, team_code: str) -> list[TeamMatchStats]:
        with self._db.session() as session:
            rows = session.scalars(
                select(TeamMatchStatsModel).where(TeamMatchStatsModel.team_code == team_code)
            ).all()
            return [
                TeamMatchStats(
                    team_code=row.team_code,
                    match_id=row.match_id,
                    goals_for=row.goals_for,
                    goals_against=row.goals_against,
                    xg_for=row.xg_for,
                    xg_against=row.xg_against,
                    possession=row.possession,
                    shots=row.shots,
                    shots_on_target=row.shots_on_target,
                )
                for row in rows
            ]

    def latest_played_kickoff(self) -> datetime | None:
        with self._db.session() as session:
            return session.scalar(
                select(MatchModel.kickoff)
                .where(MatchModel.status == MatchStatus.PLAYED.value)
                .order_by(MatchModel.kickoff.desc())
                .limit(1)
            )

    @staticmethod
    def _to_entity(row: MatchModel) -> Match:
        return Match(
            match_id=row.match_id,
            home_team_code=row.home_team_code,
            away_team_code=row.away_team_code,
            kickoff=row.kickoff,
            competition=row.competition,
            status=MatchStatus(row.status),
            home_goals=row.home_goals,
            away_goals=row.away_goals,
            neutral_venue=row.neutral_venue,
        )


class SqlPredictionRepository(PredictionRepository):
    def __init__(self, database: Database) -> None:
        self._db = database

    def save_many(self, predictions: Sequence[MatchPrediction]) -> int:
        with self._db.session() as session:
            for pred in predictions:
                session.add(
                    PredictionModel(
                        match_id=pred.match_id,
                        home_team_code=pred.home_team_code,
                        away_team_code=pred.away_team_code,
                        prob_home_win=pred.prob_home_win,
                        prob_draw=pred.prob_draw,
                        prob_away_win=pred.prob_away_win,
                        expected_home_goals=pred.expected_home_goals,
                        expected_away_goals=pred.expected_away_goals,
                        most_likely_home_goals=pred.most_likely_score[0],
                        most_likely_away_goals=pred.most_likely_score[1],
                        most_likely_score_prob=pred.most_likely_score_prob,
                        model_version=pred.model_version,
                        generated_at=pred.generated_at,
                    )
                )
        return len(predictions)

    def get_latest_for_match(self, match_id: str) -> MatchPrediction | None:
        with self._db.session() as session:
            row = session.scalar(
                select(PredictionModel)
                .where(PredictionModel.match_id == match_id)
                .order_by(PredictionModel.generated_at.desc())
                .limit(1)
            )
            if row is None:
                return None
            return MatchPrediction(
                match_id=row.match_id,
                home_team_code=row.home_team_code,
                away_team_code=row.away_team_code,
                prob_home_win=row.prob_home_win,
                prob_draw=row.prob_draw,
                prob_away_win=row.prob_away_win,
                expected_home_goals=row.expected_home_goals,
                expected_away_goals=row.expected_away_goals,
                most_likely_score=(row.most_likely_home_goals, row.most_likely_away_goals),
                most_likely_score_prob=row.most_likely_score_prob,
                model_version=row.model_version,
                generated_at=row.generated_at,
            )
