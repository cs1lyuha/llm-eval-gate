# 🚧 llm-eval-gate

**Evaluări LLM ca teste de regresie.** Schimbi promptul și CI-ul îți spune *înainte de merge* că răspunsurile
în rusă au început să vină în română și că termenul de retur a dispărut din răspunsuri.

```
suites/support.json ──▶ evalgate run ──▶ 20 de cazuri × aserțiuni ──▶ gate ──▶ exit 0 / 1
                          │ prompturi din prompts/
                          │ răspunsuri din cassettes/ (replay: gratuit, determinist)
                          └ comparație cu baselines/ → regresii, reparări
```

> Pasul 6 din planul meu de studiu: „evaluări automate în CI ca teste de regresie; dacă scorul scade, build-ul pică”.
> E o versiune mică, scrisă de mână, a ideii din promptfoo / DeepEval.

![CI](https://github.com/cs1lyuha/llm-eval-gate/actions/workflows/ci.yml/badge.svg)

## Demo: o „optimizare” de prompt care strică produsul

`prompts/support_v2.txt` pare o îmbunătățire: „Fii foarte scurt: o singură propoziție.” Răspunsuri mai scurte înseamnă mai puțini tokeni. Gate-ul spune altceva:

```
$ python -m evalgate run suites/support.json --prompt prompts/support_v2.txt
## ❌ Evaluare `support-replies` — prompt `prompts/support_v2.txt`
- trecute: 6/20 (30.0%)
- scor mediu: 0.772 (-0.228 față de baseline)

Gate picat:
- cazuri critice picate: retur-termen, retur-fara-promisiuni, retur-ru
- rata de trecere 30.0% < minimul 90%
- scorul a scăzut cu 0.228 (maxim permis 0.03)

Regresii (treceau înainte): retur-termen, retur-ru, livrare-ru, garantie-ru, rate-prag, ...

| caz          | critic | scor | motiv                                                           |
| retur-ru     | ⚠️      | 0.50 | language: limba ro, așteptat ru; icontains: lipsește '30 дней'  |
| garantie-... |        | 0.78 | icontains: lipsește '12 luni'                                   |
```

Au ieșit la iveală două regresii pe care nu le-ai fi văzut cu ochiul pe 2–3 exemple:
1. **Limba:** promptul nou nu mai spune „răspunde în limba clientului”, deci clienții vorbitori de rusă primesc răspunsuri în română.
2. **Detaliile:** cu o singură propoziție, termenele (30 de zile, 12 luni, 14 zile) dispar exact din răspunsurile unde contează.

`prompts/support_v1.txt` trece 20/20, iar asta rulează în CI la fiecare push.

> **Sincer despre demo:** răspunsurile din `cassettes/*.demo.json` vin dintr-un **model simulat** (`evalgate/demo.py`), care se comportă ca un LLM ce respectă sau nu instrucțiunile din prompt. Rostul lui e să arate mecanismul fără cheie API. Pe Claude, același flux e: `--provider claude --mode record`.

## Ideea centrală: casete (record / replay)

Evaluările cu un LLM real în CI au trei probleme: costă bani la fiecare push, sunt lente și nu sunt deterministe. Soluția, ca la VCR pentru HTTP:

| mod | ce face | când |
|---|---|---|
| `record` | apelează modelul doar pentru cererile noi și le salvează în `cassettes/` | local, când schimbi un prompt sau adaugi cazuri |
| `replay` | doar din casetă; o cerere lipsă = caz picat, cu mesajul „rulează cu --record” | **CI**: gratuit, determinist, în câteva secunde |
| `live` | mereu modelul, fără salvare | o rulare nocturnă, ca să prinzi schimbări ale modelului |

Bonus: caseta e JSON comis în repo, deci **diff-ul răspunsurilor apare în pull request** și trece prin code review ca orice cod.

## Aserțiuni

| tip | exemplu | deterministă |
|---|---|:-:|
| `contains` / `icontains` / `not_contains` | `"30 de zile"`, `["garantat", "aprobat"]` | ✓ |
| `regex` / `not_regex` | `"5\\s*-\\s*10 zile"` | ✓ |
| `max_words` / `min_words` | `80` | ✓ |
| `language` | `"ru"` sau `"$lang"` (din variabilele cazului) | ✓ |
| `json_schema` | type / required / properties / enum / items | ✓ |
| `similar` | Jaccard față de o referință, cu prag | ✓ |
| `no_pii` | fără e-mail / telefon / card în răspuns | ✓ |
| `llm_rubric` | un model-judecător notează 0..1 după o rubrică, cu prag | prin casetă |

Fiecare aserțiune are o pondere, iar fiecare caz poate fi `critical`: un caz critic picat oprește build-ul chiar dacă restul e perfect.

## Gate-ul

Pică dacă: **(1)** un caz critic pică, **(2)** rata de trecere < `min_pass_rate` sau **(3)** scorul mediu scade cu mai mult de `max_score_drop` față de `baselines/`.
Raportul listează *regresiile* (treceau, acum pică) și *reparările*. Pe GitHub, raportul apare automat în pagina job-ului (`GITHUB_STEP_SUMMARY`).

## Pornire

```bash
git clone https://github.com/cs1lyuha/llm-eval-gate.git && cd llm-eval-gate
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt

python -m evalgate run suites/support.json                                   # ✅ v1
python -m evalgate run suites/support.json --prompt prompts/support_v2.txt   # ❌ v2
pytest -q                                                                     # 37 de teste

# pe Claude (cere ANTHROPIC_API_KEY)
pip install anthropic
python -m evalgate run suites/support.json --provider claude --mode record --update-baseline
```

## Structura

| Fișier | Rol |
|---|---|
| `evalgate/suite.py` | formatul suitelor (Pydantic), randarea prompturilor |
| `evalgate/providers.py` | `FunctionProvider`, `ClaudeProvider`, `Cassette` (record / replay / live) |
| `evalgate/assertions.py` | toate aserțiunile, inclusiv `llm_rubric` |
| `evalgate/runner.py` | rularea, gate-ul, baseline-ul, raportul Markdown |
| `evalgate/__main__.py` | CLI, exit code, `GITHUB_STEP_SUMMARY` |
| `evalgate/demo.py` | modelul și judecătorul simulate |

## Ce urmează

- [ ] Casete reale de la Claude Haiku 5.5 și comparația cu cele simulate
- [ ] Rulare nocturnă `live` care deschide un issue când modelul se schimbă
- [ ] Comentariu automat pe pull request cu diff-ul răspunsurilor
- [ ] Mai multe repetări per caz pentru modelele nedeterministe (pass@k)
