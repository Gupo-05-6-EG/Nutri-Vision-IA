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
pip install -e .
uvicorn app.main:app --reload     # docs em http://127.0.0.1:8000/docs
```

> Em Python 3.9 no Windows, instale `greenlet==3.1.1` antes (a versao mais nova nao tem wheel
> pronto e tentaria compilar).

## Modulos

| arquivo | papel |
|---|---|
| `app/models.py` | `Analysis` (fila), `AnalysisItem` (`ai_*` vs confirmado), `ItemEditLog` (auditoria) |
| `app/service.py` | regras da RF23 -- unico lugar que escreve no banco |
| `app/worker.py` | a fila: roda a inferencia e grava a estimativa |
| `app/vision.py` | **stub do YOLO** -- trocar `detectar()` pelo modelo de verdade |

## O que falta plugar

- `vision.detectar()`: `ultralytics.YOLO(...).predict()` + conversao de area/volume em gramas.
- O de-para com a **TACO** e o calculo de macros: ficam **fora** deste modulo. A IA nao
  conhece a TACO, e o Core de Registros so guarda nome + gramas. Outro servico le os itens
  confirmados (`GET /api/v1/analises/{id}`) e resolve os macros.
- Fila real (worker separado varrendo `status = QUEUED`) quando o volume justificar -- o modelo
  de dados ja esta pronto para isso.
