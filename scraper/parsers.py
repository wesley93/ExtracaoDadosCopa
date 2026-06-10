"""Parsing de HTML do FBref.

Ponto crítico: o FBref entrega várias tabelas "secundárias" (logs de
jogadores, estatísticas avançadas) **dentro de comentários HTML**
(``<!-- ... -->``) que são reidratadas via JavaScript no navegador.
O BeautifulSoup ignora o conteúdo de comentários, então removemos os
delimitadores ``<!--``/``-->`` ANTES de construir a árvore — assim as
tabelas escondidas tornam-se nós normais e pesquisáveis.
"""

from __future__ import annotations

import re
from typing import Any

import pandas as pd
from bs4 import BeautifulSoup
from bs4.element import Tag

from core.exceptions import ParsingError
from core.logging import get_logger

logger = get_logger(__name__)

_COMMENT_DELIMITERS_RE = re.compile(r"<!--|-->")


def unwrap_html_comments(html: str) -> str:
    """Remove os delimitadores de comentário, expondo as tabelas escondidas.

    Remover apenas ``<!--`` e ``-->`` (em vez de extrair os blocos) preserva
    a ordem original do documento e é resistente a comentários aninhados
    de forma irregular, comuns no markup do FBref.
    """
    return _COMMENT_DELIMITERS_RE.sub("", html)


def build_soup(html: str) -> BeautifulSoup:
    """Constrói a árvore já com os comentários expostos (parser lxml)."""
    return BeautifulSoup(unwrap_html_comments(html), "lxml")


def parse_stats_table(soup: BeautifulSoup, table_id: str) -> pd.DataFrame:
    """Converte uma tabela do FBref (por ``id``) em DataFrame.

    O FBref anota cada célula com o atributo ``data-stat``, que é um nome
    de coluna estável entre temporadas — muito mais confiável do que os
    cabeçalhos visuais (que mudam e têm múltiplos níveis).

    Raises:
        ParsingError: se a tabela não existir no documento.
    """
    table = soup.find("table", id=table_id)
    if not isinstance(table, Tag):
        raise ParsingError("Tabela não encontrada no HTML", table_id=table_id)

    body = table.find("tbody")
    if not isinstance(body, Tag):
        raise ParsingError("Tabela sem <tbody>", table_id=table_id)

    rows: list[dict[str, Any]] = []
    for tr in body.find_all("tr"):
        if not isinstance(tr, Tag):
            continue
        # Linhas de cabeçalho repetido no meio do corpo são marcadas com classes.
        css_classes = tr.get("class") or []
        if "thead" in css_classes or "spacer" in css_classes:
            continue

        row: dict[str, Any] = {}
        for cell in tr.find_all(["th", "td"]):
            if not isinstance(cell, Tag):
                continue
            stat = cell.get("data-stat")
            if not isinstance(stat, str):
                continue
            row[stat] = cell.get_text(strip=True)
            # Links carregam os IDs internos do FBref (times/jogadores/partidas).
            link = cell.find("a")
            if isinstance(link, Tag) and isinstance(link.get("href"), str):
                row[f"{stat}_href"] = link["href"]
        if row:
            rows.append(row)

    frame = pd.DataFrame(rows)
    logger.debug(
        "tabela_extraida",
        extra={"context": {"table_id": table_id, "rows": len(frame)}},
    )
    return frame


def extract_fbref_id(href: str) -> str | None:
    """Extrai o ID interno de uma URL FBref.

    Ex.: ``/en/squads/206d90db/Brazil`` -> ``206d90db``
         ``/en/players/d70ce98e/Lionel-Messi`` -> ``d70ce98e``
    """
    match = re.search(r"/(?:squads|players|matches)/([0-9a-f]{8})", href)
    return match.group(1) if match else None


def coerce_numeric(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Converte colunas textuais para numéricas, tolerando vazios ('' -> NaN)."""
    result = frame.copy()
    for column in columns:
        if column in result.columns:
            result[column] = pd.to_numeric(result[column], errors="coerce")
    return result
