# Copa 2026 Predictor — Extração de Dados e Previsão de Resultados

Pipeline em Python para **extrair dados de seleções e jogadores do FBref** e
**prever resultados da Copa do Mundo de 2026** (probabilidades 1X2 + placar
exato mais provável) usando Regressão de Poisson.

## Arquitetura

O projeto segue **Clean Architecture**: o domínio (`domain/`) não depende de
nada; scraper, predictor e storage dependem apenas do domínio e do `core`;
o `main.py` é a única peça que conhece todas as camadas.

```
ExtracaoDadosCopa/
├── main.py                  # Orquestrador: scrape → persistir → treinar → prever
├── config/
│   └── settings.py          # Configuração via variáveis de ambiente (.env)
├── core/                    # Transversal (sem regra de negócio)
│   ├── logging.py           # Logs estruturados em JSON
│   └── exceptions.py        # Hierarquia de exceções com contexto
├── domain/                  # Núcleo da Clean Architecture
│   ├── entities.py          # Team, Player, Match, MatchPrediction...
│   └── repositories.py      # Interfaces abstratas (Repository Pattern)
├── scraper/                 # MÓDULO DE EXTRAÇÃO
│   ├── fbref_scraper.py     # FBrefScraper (fachada de extração)
│   ├── http_client.py       # Pacing 4s, backoff exponencial p/ 429, rotação de UA
│   ├── parsers.py           # Unwrap de comentários HTML + parsing por data-stat
│   └── cache.py             # Cache local de .html para desenvolvimento
├── predictor/               # MÓDULO DE PREVISÃO
│   ├── feature_engine.py    # FeatureEngine: xG/xA móvel, fadiga, forças relativas
│   └── match_predictor.py   # MatchPredictor: GLM Poisson + matriz de placares
├── storage/                 # CAMADA DE PERSISTÊNCIA
│   ├── database.py          # Engine/sessões SQLAlchemy (SQLite ⇄ SQL Server)
│   ├── models.py            # Modelos ORM (SQLAlchemy 2.0)
│   └── repositories.py      # Implementações SQL das interfaces do domínio
├── data/cache/              # HTMLs em cache (ignorados pelo git)
└── tests/                   # pytest
```

## Instalação

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                # ajuste se necessário
```

Requer **Python ≥ 3.11**.

## Uso

```bash
python main.py                       # pipeline completo (scrape + treino + previsão)
python main.py --skip-scrape         # usar somente dados já persistidos
python main.py --force-scrape        # raspar mesmo com banco atualizado
python main.py --upcoming-limit 8    # prever apenas os 8 próximos jogos
```

Saída (além dos logs JSON em stdout):

```
=== Previsões — Copa do Mundo 2026 ===

BRA vs USA | V 61.2%  E 22.4%  D 16.4% | placar mais provável: 2 x 0 (14.8%)
```

## Decisões técnicas

### Fontes de dados e execução em CI
O FBref responde **HTTP 403 para IPs de datacenter** (Cloudflare), então o
scraping só funciona de IPs residenciais (sua máquina). Para rodar no GitHub
Actions, o pipeline tem um fallback automático: ao receber erro do FBref, ele
ingere o dataset aberto de resultados de seleções
([martj42/international_results](https://github.com/martj42/international_results),
CC0) via `raw.githubusercontent.com`, que funciona em qualquer ambiente.

Jogos futuros (o calendário oficial da Copa) são fornecidos em
`data/fixtures.csv` — copie `data/fixtures.example.csv` e preencha com o
chaveamento real; os nomes das seleções devem coincidir com os do histórico
(ex.: `Brazil`, `United States`).

### Scraper resiliente (`scraper/`)
- **Tabelas escondidas em comentários**: o FBref serve várias tabelas dentro
  de `<!-- -->` (reidratadas via JS). `parsers.unwrap_html_comments()` remove
  os delimitadores **antes** do BeautifulSoup, tornando-as pesquisáveis.
- **Pacing**: mínimo de 4 s entre requisições (`SCRAPER_PACING_SECONDS`).
- **HTTP 429**: backoff exponencial com jitter, respeitando `Retry-After`
  quando o servidor o envia; após esgotar as tentativas, `RateLimitError`.
- **Rotação de User-Agent** a cada requisição.
- **Cache local**: cada página vai para `data/cache/*.html`; durante o
  desenvolvimento as releituras não tocam a rede (`CACHE_ENABLED=false`
  desliga).

### Modelo (`predictor/`)
- **Regressão de Poisson (statsmodels GLM)** na parametrização clássica
  ataque × defesa (Maher/Dixon-Coles): `gols ~ C(time) + C(oponente) + mando`.
- A previsão monta a **matriz de placares** `P(h,a) = Pois(h;λ_casa)·Pois(a;λ_fora)`;
  1X2 são as somas das regiões e o placar exato é o argmax.
- **Campo neutro por padrão** (Copa do Mundo); passe `neutral_venue=False`
  para os anfitriões EUA/México/Canadá.
- O `FeatureEngine` produz features prontas (xG/xA móveis com `shift(1)` para
  evitar vazamento, índice de fadiga por minutos acumulados, forças relativas)
  para evoluir o modelo para **XGBoost** sem mudar a interface pública do
  `MatchPredictor`.

### Persistência (`storage/`)
- **Repository Pattern**: o domínio define as interfaces; o storage implementa
  com SQLAlchemy. Trocar SQLite por **SQL Server** é só mudar `DATABASE_URL`:

  ```
  DATABASE_URL=mssql+pyodbc://usuario:senha@servidor:1433/copa2026?driver=ODBC+Driver+18+for+SQL+Server
  ```

## Testes

```bash
pip install -e ".[dev]"
pytest
```

## Próximos passos sugeridos

1. Implementar correção Dixon-Coles para placares baixos (0x0, 1x1).
2. Conectar as features do `FeatureEngine` a um `XGBRegressor` prevendo λ.
3. Simulação Monte Carlo do chaveamento completo (campeão provável).
4. Agendamento do `main.py` (cron/Airflow) e métricas de calibração (Brier score).
