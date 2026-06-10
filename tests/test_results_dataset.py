"""Testes do parser do dataset aberto de resultados internacionais."""

from __future__ import annotations

import pytest

from core.exceptions import ParsingError
from domain.entities import MatchStatus
from scraper.results_dataset import build_match_id, parse_results_csv

_SAMPLE_CSV = """date,home_team,away_team,home_score,away_score,tournament,city,country,neutral
2019-06-01,Brazil,Argentina,2,0,Friendly,Rio,Brazil,FALSE
2024-07-14,Argentina,Colombia,1,0,Copa América,Miami,United States,TRUE
2025-03-20,Brazil,Colombia,2,1,FIFA World Cup qualification,Brasília,Brazil,FALSE
2026-06-11,Mexico,Senegal,,,FIFA World Cup,Mexico City,Mexico,FALSE
linha,quebrada
"""


def test_parse_filters_by_year_and_skips_unplayed() -> None:
    matches = parse_results_csv(_SAMPLE_CSV, since_year=2021)
    ids = [m.match_id for m in matches]
    # 2019 fora do recorte; jogo de 2026 sem placar é ignorado; linha quebrada idem.
    assert len(matches) == 2
    assert "2024-07-14_Argentina_Colombia" in ids
    assert all(m.status is MatchStatus.PLAYED for m in matches)


def test_parse_maps_scores_and_neutral_flag() -> None:
    matches = parse_results_csv(_SAMPLE_CSV, since_year=2021)
    copa_america = next(m for m in matches if m.home_team_code == "Argentina")
    assert (copa_america.home_goals, copa_america.away_goals) == (1, 0)
    assert copa_america.neutral_venue is True
    qualifier = next(m for m in matches if m.kickoff.year == 2025)
    assert qualifier.neutral_venue is False


def test_parse_invalid_header_raises() -> None:
    with pytest.raises(ParsingError):
        parse_results_csv("foo,bar\n1,2\n", since_year=2021)


def test_build_match_id_replaces_spaces() -> None:
    from datetime import datetime

    match_id = build_match_id(datetime(2026, 6, 12), "United States", "Ecuador")
    assert match_id == "2026-06-12_United-States_Ecuador"
    assert " " not in match_id
