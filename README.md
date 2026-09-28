# Nutri-Vision-IA

Core de Registros: o paciente manda a foto do prato, a IA estima quantos gramas tem de cada
alimento, e o paciente corrige o que estiver errado -- **sem que a estimativa original se perca**
(RF23, Task 2.7). E essa diferenca entre estimado e confirmado que alimenta a metrica de
acuracia (Task 3.4).

## Fluxo

```
POST /api/v1/analises            (imagem)  -> 202 { id, status: "QUEUED" }
                                               worker roda o YOLO e grava a analise
GET  /api/v1/analises/{id}                 -> estimativa da IA lado a lado com o confirmado
PATCH /api/v1/analises/{id}/itens/{item}   -> corrige alimento e/ou gramas
POST /api/v1/analises/{id}/confirmar       -> fecha a refeicao
```

Resposta de um item:

```json
{
  "ai":         { "food": "carne bovina", "grams": 500.0, "confidence": 0.87 },
  "confirmado": { "food": "carne bovina", "grams": 420.0 },
  "was_edited": true, "edited_fields": ["grams"], "grams_delta": -80.0,
  "origin": "ia", "removido": false
}
```

## Rodando

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -e ".[dev]"
uvicorn app.main:app --reload     # docs em http://127.0.0.1:8000/docs
pytest -q
```

Sem `NUTRIVISION_MODEL_PATH` o app sobe com o **detector stub** (3 alimentos fixos). Para o
YOLO de verdade:

```bash
pip install -e ".[vision]"                 # ultralytics + torch
set NUTRIVISION_MODEL_PATH=pesos\best.pt   # ou no .env
uvicorn app.main:app
```

O modelo e carregado **uma vez** no startup (`lifespan`) e aquecido com uma inferencia vazia;
`GET /health` mostra qual modelo esta em memoria. Se o caminho estiver definido mas o arquivo nao
existir (ou o ultralytics nao estiver instalado), o app nao sobe.

| variavel (`NUTRIVISION_*`) | padrao | |
|---|---|---|
| `MODEL_PATH` | - | pesos `.pt` do YOLO |
| `MODEL_IMGSZ` / `MODEL_CONF` / `MODEL_DEVICE` | 640 / 0.25 / cpu | parametros do `predict` |
| `IMAGE_MAX_SIDE` / `JPEG_QUALITY` | 1280 / 85 | compressao no upload |
| `PLATE_REFERENCE_GRAMS` | 600 | heuristica provisoria area -> gramas |

> Em Python 3.9 no Windows, instale `greenlet==3.1.1` antes (a versao mais nova nao tem wheel
> pronto e tentaria compilar).

## Imagem

No upload a foto e validada e **comprimida** antes de ir para o disco (`app/imagem.py`): aplica a
rotacao do EXIF, converte para RGB, reduz o lado maior para 1280px e salva JPEG q85 **sem
metadados** (GPS etc.). So a versao comprimida e guardada. Aceita HEIC do iPhone (`pi-heif`).
Arquivo que nao abre como imagem -> 415.

## Modulos

| arquivo | papel |
|---|---|
| `app/models.py` | `Analysis` (fila), `AnalysisItem` (`ai_*` vs confirmado), `ItemEditLog` (auditoria) |
| `app/service.py` | regras da RF23 -- unico lugar que escreve no banco |
| `app/worker.py` | a fila: roda a inferencia e grava a estimativa |
| `app/imagem.py` | validacao + compressao da foto no upload |
| `app/vision.py` | `YoloDetector` (ultralytics, em memoria) e `StubDetector`; `carregar_detector()` escolhe |

## O que falta plugar

- Pesos treinados com alimentos brasileiros: o COCO (`yolov8n.pt`) so conhece poucos alimentos
  (broccoli, pizza, sandwich...), e os nomes saem em ingles.
- `vision._estimar_gramas()`: hoje e so a proporcao da foto ocupada pelo box x um prato de
  referencia. Trocar por volume/densidade por classe.
- O de-para com a **TACO** e o calculo de macros: ficam **fora** deste modulo. A IA nao
  conhece a TACO, e o Core de Registros so guarda nome + gramas. Outro servico le os itens
  confirmados (`GET /api/v1/analises/{id}`) e resolve os macros.
- Fila real (worker separado varrendo `status = QUEUED`) quando o volume justificar -- o modelo
  de dados ja esta pronto para isso.
