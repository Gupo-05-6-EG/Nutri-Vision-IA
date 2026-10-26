# Nutri-Vision-IA

API que analisa a foto de uma refeição e devolve os alimentos do prato, já identificados na **Tabela Brasileira de Composição de Alimentos (TACO)**, com a quantidade estimada em gramas.

O usuário pode corrigir qualquer item antes de confirmar a refeição. A estimativa original da IA fica guardada ao lado do valor confirmado, então dá para auditar cada correção e medir a precisão do modelo ao longo do tempo.

## Funcionalidades

- **Reconhecimento por foto**: o Google Gemini identifica cada alimento e estima os gramas.
- **Mapeamento para a TACO**: cada item vem com o `taco_id` de um dos 597 alimentos da tabela,
  pronto para o cálculo de macronutrientes.
- **Checagem de qualidade**: fotos borradas, escuras ou estouradas são recusadas na hora, antes
  de gastar uma chamada à IA.
- **Processamento em fila**: as análises rodam em background (Redis + RQ), com retry automático
  quando a API do Gemini está sobrecarregada.
- **Correção rastreável**: toda alteração de alimento ou gramas fica registrada (quem, quando,
  valor antigo e novo), sem sobrescrever a estimativa da IA.
- **Busca na TACO**: endpoint de busca para o app oferecer a lista de alimentos ao corrigir um item.

## Como funciona

```
                ┌──────────────┐   foto ok    ┌─────────┐        ┌──────────┐
 app ── foto ──►│     API      │─────────────►│  Redis  │◄───────│  worker  │
                │  (FastAPI)   │  enfileira   │  (RQ)   │  pega  │   (RQ)   │
                └──────┬───────┘              └─────────┘        └────┬─────┘
                       │ foto ruim: responde na hora                  │
                       ▼                                              ▼
                ┌──────────────┐                               ┌──────────────┐
                │    SQLite    │◄──────── grava itens ─────────│ Google Gemini│
                └──────────────┘                               └──────────────┘
```

1. O app envia a foto para `POST /api/v1/analyses`.
2. A API mede nitidez e luminosidade. Se a foto estiver ruim, a análise já volta como
   `NOT_ESTIMATED` com o motivo.
3. Se estiver boa, a análise é criada como `QUEUED` e a imagem vai para a fila no Redis.
   Ela não é gravada em disco; o banco guarda só o hash.
4. O worker envia a foto e a lista da TACO ao Gemini, que responde um JSON com os alimentos,
   os gramas e a confiança de cada item.
5. O app consulta `GET /api/v1/analyses/{id}` até o status virar `DONE`. Depois corrige o que
   precisar e confirma a refeição.

## Stack

| | |
|---|---|
| API | Python 3.12, FastAPI, Pydantic |
| Banco | SQLAlchemy 2 + SQLite |
| Fila | Redis 7 + RQ |
| IA | Google Gemini (`google-genai`) |
| Imagem | Pillow |
| Infra | Docker / Docker Compose |
| Testes | pytest, fakeredis |

## Começando

### Pré-requisitos

- Docker e Docker Compose
- Uma chave da API do Gemini ([Google AI Studio](https://aistudio.google.com/apikey))

### Rodando

```bash
cp .env.example .env              # preencha NUTRIVISION_GEMINI_API_KEY
docker compose up --build
```

A documentação interativa (Swagger) fica em http://localhost:8000/docs.

São três serviços: `api`, `worker` e `redis`. Para processar mais fotos ao mesmo tempo, suba
mais workers:

```bash
docker compose up -d --scale worker=3
```

### Testes

Os testes não chamam o Gemini nem precisam de Redis:

```bash
python -m venv venv
venv\Scripts\activate             # Linux/macOS: source venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

> O worker do RQ não roda nativamente no Windows. Fora do Docker, use WSL.

## Configuração

Variáveis de ambiente com prefixo `NUTRIVISION_` (ou no arquivo `.env`):

| variável | padrão | descrição |
|---|---|---|
| `GEMINI_API_KEY` | - | chave da API do Gemini (obrigatória no worker) |
| `GEMINI_MODEL` | `gemini-3.8-flash` | modelo usado na análise |
| `GEMINI_TIMEOUT_MS` | `90000` | timeout de cada chamada ao Gemini (o retry fica com a fila) |
| `REDIS_URL` | `redis://localhost:6379/0` | conexão com a fila |
| `DATABASE_URL` | `sqlite:///nutrivision.db` | banco de dados (`/data/nutrivision.db` no Docker) |
| `TACO_CSV` | `app/data/taco.csv` | arquivo da tabela TACO |
| `MAX_UPLOAD_BYTES` | `10485760` | tamanho máximo da foto (10 MB) |
| `MIN_SHARPNESS` | `60.0` | nitidez mínima (variância do laplaciano) |
| `MIN_BRIGHTNESS` | `45.0` | brilho médio mínimo |
| `MAX_BRIGHTNESS` | `220.0` | brilho médio máximo |
| `MIN_CONFIDENCE` | `0.50` | confiança abaixo da qual o item é marcado como `low_confidence` |

## API

| método | rota | descrição |
|---|---|---|
| `POST` | `/api/v1/analyses` | envia a foto (multipart: `file`, `patient_id`, `meal_type`) |
| `GET` | `/api/v1/analyses/{id}` | resultado: estimativa da IA e valores confirmados |
| `PATCH` | `/api/v1/analyses/{id}/items/{item_id}` | corrige alimento (`taco_id`) e/ou `grams` |
| `POST` | `/api/v1/analyses/{id}/items` | adiciona um alimento que a IA não detectou |
| `DELETE` | `/api/v1/analyses/{id}/items/{item_id}` | remove um item (mantém o histórico) |
| `POST` | `/api/v1/analyses/{id}/confirm` | confirma a refeição (aceita correções em lote) |
| `GET` | `/api/v1/foods?search=arroz` | busca alimentos na TACO |
| `GET` | `/health` | status da API e do Redis |

Formatos aceitos: JPEG, PNG e WebP.

### Exemplo

```bash
curl -F "file=@prato.jpg;type=image/jpeg" http://localhost:8000/api/v1/analyses
# { "id": "6f1c...", "status": "QUEUED", "reason": null,
#   "quality": { "sharpness": 812.4, "brightness": 131.0, "issues": [], "ok": true } }

curl http://localhost:8000/api/v1/analyses/6f1c...
```

```json
{
  "id": "6f1c...",
  "status": "DONE",
  "confirmed": false,
  "model_version": "gemini-3.8-flash",
  "items": [
    {
      "id": "a91e...",
      "ai":        { "food": "Arroz, tipo 1, cozido", "taco_id": 3, "grams": 150.0, "confidence": 0.92 },
      "confirmed": { "food": "Arroz, tipo 1, cozido", "taco_id": 3, "grams": 150.0 },
      "was_edited": false, "edited_fields": [], "grams_delta": 0.0,
      "origin": "ai", "low_confidence": false, "removed": false
    }
  ]
}
```

Corrigindo um item, escolhendo outro alimento da TACO:

```bash
curl -X PATCH http://localhost:8000/api/v1/analyses/6f1c.../items/a91e... \
     -H "Content-Type: application/json" \
     -d '{ "taco_id": 1, "grams": 120 }'
```

O campo `ai` nunca muda. `confirmed` passa a ter o novo valor, e `edited_fields` mostra o que
foi alterado.

### Status da análise

| status | quando |
|---|---|
| `QUEUED` | na fila, aguardando o worker |
| `PROCESSING` | o worker está consultando o Gemini |
| `DONE` | alimentos identificados |
| `NOT_ESTIMATED` | a IA não conseguiu estimar (ver `reason`) |
| `FAILED` | erro no Gemini mesmo depois dos retries (ver `error`) |

Valores de `reason`:

| reason | significado |
|---|---|
| `bad_photo` | foto borrada ou mal iluminada (`quality.issues`: `blurry`, `too_dark`, `too_bright`) |
| `nothing_detected` | nenhum alimento na foto |
| `low_confidence` | todos os itens ficaram abaixo da confiança mínima |

Em qualquer desses casos a refeição ainda pode ser registrada: o app pode pedir outra foto,
adicionar os itens manualmente ou confirmar sem itens.

## Estrutura do projeto

```
app/
├── main.py                  # aplicação FastAPI e tratamento de erros
├── models.py                # tabelas: Analysis, AnalysisItem, ItemEditLog
├── schemas.py               # modelos de entrada e saída da API
├── core/
│   ├── config.py            # configurações via variáveis de ambiente
│   └── database.py          # conexão e sessão do banco
├── api/
│   ├── analyses.py          # rotas de análise
│   └── foods.py             # rota de busca na TACO
├── services/
│   ├── analysis_service.py  # regras de negócio (criação, correção, confirmação)
│   ├── food_recognition.py  # integração com o Gemini
│   ├── image_quality.py     # checagem de nitidez e luminosidade
│   └── taco_table.py        # leitura e busca na tabela TACO
├── worker/
│   ├── job_queue.py         # envio de análises para a fila
│   └── tasks.py             # processamento das análises
└── data/
    └── taco.csv             # tabela TACO (id;name;category)
tests/
```

## Tabela TACO

Os dados vêm da **TACO 4ª edição** (NEPA/UNICAMP, 2011), com 597 alimentos, convertidos a
partir do projeto [raulfdm/taco-api](https://github.com/raulfdm/taco-api) (licença MIT).

## Próximos passos

- Cálculo de macronutrientes a partir do `taco_id` e dos gramas confirmados.
- Migrações de banco (Alembic) e suporte a Postgres para vários workers em paralelo.
- Painel de precisão do modelo comparando a estimativa da IA com os valores confirmados.
