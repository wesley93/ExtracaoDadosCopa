"""Testes do MatchPredictor (GLM Poisson) com um histórico sintético."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.exceptions import InsufficientDataError, PredictionError
from predictor.match_predictor import MatchPredictor

RNG = np.random.default_rng(42)
TEAMS = ["BRA", "ARG", "FRA", "GER", "USA", "JPN"]


@pytest.fixture()
def synthetic_history() -> pd.DataFrame:
    """Gera um round-robin duplo com gols ~ Poisson de forças distintas."""
    strength = {team: 0.8 + 0.15 * i for i, team in enumerate(TEAMS)}
    rows: list[dict[str, object]] = []
    for home in TEAMS:
        for away in TEAMS:
            if home == away:
                continue
            rows.append(
                {
                    "home_team_code": home,
                    "away_team_code": away,
                    "home_goals": int(RNG.poisson(strength[home])),
                    "away_goals": int(RNG.poisson(strength[away])),
                    "neutral_venue": True,
                }
            )
    return pd.DataFrame(rows)


def test_fit_and_predict_returns_valid_probabilities(
    synthetic_history: pd.DataFrame,
) -> None:
    predictor = MatchPredictor(max_goals=10).fit(synthetic_history)
    prediction = predictor.predict("BRA", "USA", match_id="teste-1")

    total = prediction.prob_home_win + prediction.prob_draw + prediction.prob_away_win
    assert total == pytest.approx(1.0, abs=1e-6)
    assert 0 <= prediction.most_likely_score[0] <= 10
    assert prediction.expected_home_goals > 0


def test_predict_without_fit_raises(synthetic_history: pd.DataFrame) -> None:
    with pytest.raises(PredictionError):
        MatchPredictor().predict("BRA", "ARG", match_id="x")


def test_unknown_team_raises_insufficient_data(synthetic_history: pd.DataFrame) -> None:
    predictor = MatchPredictor().fit(synthetic_history)
    with pytest.raises(InsufficientDataError):
        predictor.predict("BRA", "ZZZ", match_id="x")


def test_fit_empty_history_raises() -> None:
    empty = pd.DataFrame(
        columns=["home_team_code", "away_team_code", "home_goals", "away_goals", "neutral_venue"]
    )
    with pytest.raises(InsufficientDataError):
        MatchPredictor().fit(empty)
