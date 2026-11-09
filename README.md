# Nutri-Vision-IA

Serviço que analisa a foto de uma refeição e devolve os alimentos do prato, já identificados na **Tabela Brasileira de Composição de Alimentos (TACO)**, com a quantidade estimada em gramas.

Ele faz só isso: recebe a foto, analisa e entrega o resultado. Correções, confirmação da refeição, histórico e cálculo de macros ficam na API que consome este serviço. A foto não é guardada: ela existe só enquanto está sendo analisada.

## Funcionalidades

- **Reconhecimento por foto**: o Google Gemini identifica cada alimento e estima os gramas.
- **Mapeamento para a TACO**: cada item vem com o `taco_id` de um dos 597 alimentos da tabela.
- **Compressão da foto**: a imagem é corrigida pela rotação da câmera, reduzida para 1280 px e
  convertida para JPEG sem metadados (GPS etc.). Aceita HEIC do iPhone.
- **Checagem de qualidade**: fotos borradas, escuras ou estouradas são recusadas na hora, antes
  de gastar uma chamada à IA.
- **Processamento em fila**: as análises rodam em background (Redis + RQ), com retry automático
  quando a API do Gemini está sobrecarregada.
- **Sem armazenamento**: a imagem some quando a análise termina, e o resultado expira sozinho
  depois de 24 h.

## Como funciona

```
                ┌──────────────┐   foto ok    ┌─────────────────┐        ┌──────────┐
 cliente ─foto─►│     API      │─────────────►│      Redis      │◄───────│  worker  │
                │  (FastAPI)   │  enfileira   │ fila + resultado│ grava  │   (RQ)   │
                └──────────────┘              └─────────────────┘        └────┬─────┘
                foto ruim: responde na hora                                   ▼
                                                                       ┌──────────────┐
                                                                       │ Google Gemini│
                                                                       └──────────────┘
```

1. O cliente envia a foto para `POST /api/v1/analyses` e recebe um `id`.
2. A API comprime a foto e mede nitidez e luminosidade. Se a foto estiver ruim, a resposta já
   vem como `NOT_ESTIMATED`, sem chamar a IA.
3. Se estiver boa, a imagem entra na fila do Redis junto com o job.
4. O worker envia a foto e a lista da TACO ao Gemini e grava o resultado no Redis. O job, com a
   imagem dentro, é apagado em seguida.
5. O cliente consulta `GET /api/v1/analyses/{id}` até o status sair de `QUEUED`/`PROCESSING`.

## Stack

| | |
|---|---|
| API | Python 3.12, FastAPI, Pydantic |
| Fila e resultados | Redis 7 + RQ |
| IA | Google Gemini (`google-genai`) |
| Imagem | Pillow, pi-heif |
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
| `REDIS_URL` | `redis://localhost:6379/0` | fila e resultados |
| `RESULT_TTL_SECONDS` | `86400` | por quanto tempo o resultado fica disponível (24 h) |
| `TACO_CSV` | `app/data/taco.csv` | arquivo da tabela TACO |
| `MAX_UPLOAD_BYTES` | `10485760` | tamanho máximo da foto enviada (10 MB) |
| `IMAGE_MAX_SIDE` | `1280` | lado maior da foto depois da compressão |
| `JPEG_QUALITY` | `85` | qualidade do JPEG comprimido |
| `MIN_SHARPNESS` | `60.0` | nitidez mínima (variância do laplaciano) |
| `MIN_BRIGHTNESS` | `45.0` | brilho médio mínimo |
| `MAX_BRIGHTNESS` | `220.0` | brilho médio máximo |
| `MIN_CONFIDENCE` | `0.50` | confiança mínima para um item contar como identificado |

## API

| método | rota | descrição |
|---|---|---|
| `POST` | `/api/v1/analyses` | envia a foto (multipart, campo `file`) e devolve o `id` da análise |
| `GET` | `/api/v1/analyses/{id}` | resultado da análise (404 se não existe ou já expirou) |
| `GET` | `/health` | status da API e do Redis |

Formatos aceitos: qualquer imagem que o Pillow abra (JPEG, PNG, WebP, HEIC...). Arquivo que
não é imagem retorna 415.

### Exemplo

```bash
curl -F "file=@prato.jpg;type=image/jpeg" http://localhost:8000/api/v1/analyses
# { "id": "6f1c...", "status": "QUEUED" }

curl http://localhost:8000/api/v1/analyses/6f1c...
```

```json
{
  "id": "6f1c...",
  "status": "DONE",
  "model_version": "gemini-3.8-flash",
  "items": [
    { "food": "Arroz, tipo 1, cozido", "taco_id": 3, "grams": 160.0, "confidence": 0.95 },
    { "food": "Feijão, preto, cozido", "taco_id": 567, "grams": 110.0, "confidence": 0.95 }
  ]
}
```

Campos sem valor não aparecem na resposta. Um item que o Gemini não encontrou na TACO vem sem
`taco_id`; quem consome decide o que fazer com ele e com a `confidence`.

### Status da análise

| status | quando | campos extras |
|---|---|---|
| `QUEUED` | na fila, aguardando o worker | - |
| `PROCESSING` | o worker está consultando o Gemini | - |
| `DONE` | alimentos identificados | `model_version`, `items` |
| `NOT_ESTIMATED` | a IA não conseguiu estimar | `reason`, `items` |
| `FAILED` | erro no Gemini mesmo depois dos retries | `error` |

Valores de `reason`:

| reason | significado |
|---|---|
| `bad_photo` | foto borrada ou mal iluminada (`issues`: `blurry`, `too_dark`, `too_bright`) |
| `nothing_detected` | nenhum alimento na foto |
| `low_confidence` | nenhum item com confiança suficiente ou encontrado na TACO |

```json
{ "id": "911e...", "status": "NOT_ESTIMATED", "reason": "bad_photo", "issues": ["blurry"], "items": [] }
```

## Estrutura do projeto

```
app/
├── main.py                  # aplicação FastAPI, /health e tratamento de erros
├── schemas.py               # formato das respostas da API
├── core/
│   └── config.py            # configurações via variáveis de ambiente
├── api/
│   └── analyses.py          # rotas de envio e consulta da análise
├── services/
│   ├── analysis_result.py   # status e montagem do resultado
│   ├── food_recognition.py  # integração com o Gemini
│   ├── image_compression.py # rotação, redimensionamento e conversão para JPEG
│   ├── image_quality.py     # checagem de nitidez e luminosidade
│   └── taco_table.py        # leitura da tabela TACO
├── worker/
│   ├── job_queue.py         # envio de análises para a fila
│   ├── result_store.py      # resultado das análises no Redis, com expiração
│   └── tasks.py             # processamento das análises
└── data/
    └── taco.csv             # tabela TACO (id;name;category)
tests/
```

## Padrões de projeto

### Singleton

Três recursos são criados uma única vez e compartilhados por todo o serviço:

| onde | o que | como |
|---|---|---|
| `app/core/config.py` | `settings` | instância criada no módulo; o Python carrega cada módulo uma só vez |
| `app/worker/job_queue.py` | `get_redis()` | `@lru_cache(maxsize=1)`: a conexão com o Redis é aberta na primeira chamada e reaproveitada depois |
| `app/services/taco_table.py` | `_load_table()` | `@lru_cache(maxsize=1)`: o CSV da TACO é lido do disco uma vez e mantido em memória |

Assim as configurações não são lidas de novo a cada uso, as requisições compartilham a mesma
conexão com o Redis e os 597 alimentos da TACO não são relidos a cada análise.

### Adapter

`_to_detections` (`app/services/food_recognition.py`) converte a resposta do Gemini
(`_GeminiResponse`) para o formato interno do serviço (`Detection`). No caminho, ela:

- descarta itens com gramas zeradas ou negativas;
- limita a `confidence` ao intervalo de 0 a 1;
- troca o nome dado pelo Gemini pelo nome oficial da TACO e, quando o `taco_id` não existe na
  tabela, mantém o nome do Gemini e deixa o item sem `taco_id`.

O resto do serviço (`analysis_result`, `worker/tasks`) só conhece `Detection`. Por isso, trocar
o Gemini por outro modelo exige mudar só esse adaptador.

## Tabela TACO

Os dados vêm da **TACO 4ª edição** (NEPA/UNICAMP, 2011), com 597 alimentos, convertidos a
partir do projeto [raulfdm/taco-api](https://github.com/raulfdm/taco-api) (licença MIT).
