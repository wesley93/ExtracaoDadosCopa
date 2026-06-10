"""Testes do parsing de HTML — em especial o unwrap de comentários."""

from __future__ import annotations

import pytest

from core.exceptions import ParsingError
from scraper.parsers import build_soup, extract_fbref_id, parse_stats_table, unwrap_html_comments

_HIDDEN_TABLE_HTML = """
<html><body>
<div id="all_stats">
<!--
<table id="stats_squads_standard_for">
  <tbody>
    <tr>
      <th data-stat="team"><a href="/en/squads/206d90db/Brazil">Brazil</a></th>
      <td data-stat="goals">12</td>
      <td data-stat="xg">9.7</td>
    </tr>
    <tr class="thead"><td data-stat="team">Squad</td></tr>
    <tr>
      <th data-stat="team"><a href="/en/squads/132ebc33/Argentina">Argentina</a></th>
      <td data-stat="goals">10</td>
      <td data-stat="xg">8.1</td>
    </tr>
  </tbody>
</table>
-->
</div>
</body></html>
"""


def test_unwrap_exposes_commented_tables() -> None:
    html = unwrap_html_comments(_HIDDEN_TABLE_HTML)
    assert "<!--" not in html and "-->" not in html


def test_parse_hidden_table_extracts_rows_and_skips_thead() -> None:
    soup = build_soup(_HIDDEN_TABLE_HTML)
    frame = parse_stats_table(soup, "stats_squads_standard_for")
    assert len(frame) == 2
    assert list(frame["team"]) == ["Brazil", "Argentina"]
    assert frame.loc[0, "team_href"] == "/en/squads/206d90db/Brazil"


def test_parse_missing_table_raises_parsing_error() -> None:
    soup = build_soup(_HIDDEN_TABLE_HTML)
    with pytest.raises(ParsingError):
        parse_stats_table(soup, "tabela_inexistente")


def test_extract_fbref_id() -> None:
    assert extract_fbref_id("/en/squads/206d90db/Brazil") == "206d90db"
    assert extract_fbref_id("/en/players/d70ce98e/Lionel-Messi") == "d70ce98e"
    assert extract_fbref_id("/en/comps/1/schedule") is None
