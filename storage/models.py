"""Modelos ORM (SQLAlchemy 2.0, estilo ``Mapped``).

Espelham as entidades de domínio em ``domain/entities.py``. A conversão
entidade <-> ORM acontece exclusivamente em ``storage/repositories.py``.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TeamModel(Base):
    __tablename__ = "teams"

    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    fbref_id: Mapped[str | None] = mapped_column(String(16))
    confederation: Mapped[str | None] = mapped_column(String(16))


class PlayerModel(Base):
    __tablename__ = "players"

    fbref_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    team_code: Mapped[str] = mapped_column(ForeignKey("teams.code"), index=True)
    position: Mapped[str | None] = mapped_column(String(8))
    birth_date: Mapped[date | None] = mapped_column(Date)


class MatchModel(Base):
    __tablename__ = "matches"

    match_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    home_team_code: Mapped[str] = mapped_column(ForeignKey("teams.code"), index=True)
    away_team_code: Mapped[str] = mapped_column(ForeignKey("teams.code"), index=True)
    kickoff: Mapped[datetime] = mapped_column(DateTime, index=True)
    competition: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(16), default="scheduled", index=True)
    home_goals: Mapped[int | None] = mapped_column(Integer)
    away_goals: Mapped[int | None] = mapped_column(Integer)
    neutral_venue: Mapped[bool] = mapped_column(Boolean, default=True)


class TeamMatchStatsModel(Base):
    __tablename__ = "team_match_stats"
    __table_args__ = (UniqueConstraint("team_code", "match_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_code: Mapped[str] = mapped_column(ForeignKey("teams.code"), index=True)
    match_id: Mapped[str] = mapped_column(ForeignKey("matches.match_id"), index=True)
    goals_for: Mapped[int] = mapped_column(Integer)
    goals_against: Mapped[int] = mapped_column(Integer)
    xg_for: Mapped[float | None] = mapped_column(Float)
    xg_against: Mapped[float | None] = mapped_column(Float)
    possession: Mapped[float | None] = mapped_column(Float)
    shots: Mapped[int | None] = mapped_column(Integer)
    shots_on_target: Mapped[int | None] = mapped_column(Integer)


class PlayerMatchStatsModel(Base):
    __tablename__ = "player_match_stats"
    __table_args__ = (UniqueConstraint("player_fbref_id", "match_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_fbref_id: Mapped[str] = mapped_column(ForeignKey("players.fbref_id"), index=True)
    match_id: Mapped[str] = mapped_column(ForeignKey("matches.match_id"), index=True)
    minutes: Mapped[int] = mapped_column(Integer)
    goals: Mapped[int] = mapped_column(Integer, default=0)
    assists: Mapped[int] = mapped_column(Integer, default=0)
    xg: Mapped[float | None] = mapped_column(Float)
    xa: Mapped[float | None] = mapped_column(Float)
    shots: Mapped[int | None] = mapped_column(Integer)
    key_passes: Mapped[int | None] = mapped_column(Integer)


class PredictionModel(Base):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(ForeignKey("matches.match_id"), index=True)
    home_team_code: Mapped[str] = mapped_column(String(3))
    away_team_code: Mapped[str] = mapped_column(String(3))
    prob_home_win: Mapped[float] = mapped_column(Float)
    prob_draw: Mapped[float] = mapped_column(Float)
    prob_away_win: Mapped[float] = mapped_column(Float)
    expected_home_goals: Mapped[float] = mapped_column(Float)
    expected_away_goals: Mapped[float] = mapped_column(Float)
    most_likely_home_goals: Mapped[int] = mapped_column(Integer)
    most_likely_away_goals: Mapped[int] = mapped_column(Integer)
    most_likely_score_prob: Mapped[float] = mapped_column(Float)
    model_version: Mapped[str] = mapped_column(String(40))
    generated_at: Mapped[datetime] = mapped_column(DateTime, index=True)
