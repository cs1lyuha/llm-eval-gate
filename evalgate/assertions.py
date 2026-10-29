"""Aserțiunile. Fiecare întoarce (scor 0..1, a trecut?, motiv).

Deterministe: contains / icontains / not_contains / regex / not_regex / json_schema /
max_words / min_words / language / similar / no_pii.
Cu model: `llm_rubric`: un model-judecător notează răspunsul după o rubrică. Folosește
aceeași casetă, deci și judecata e reproductibilă în CI.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from evalgate.providers import Provider
from evalgate.suite import Assertion


@dataclass
class Check:
    type: str
    passed: bool
    score: float
    reason: str
    weight: float = 1.0


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def detect_language(text: str) -> str:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "unknown"
    if sum("Ѐ" <= c <= "ӿ" for c in letters) / len(letters) > 0.3:
        return "ru"
    words = set(_words(text))
    ro = len(words & {"și", "este", "sunt", "pentru", "în", "de", "la", "cu", "vă", "nu", "puteți", "zile"})
    en = len(words & {"the", "and", "is", "are", "for", "you", "your", "can", "days", "with", "to"})
    if any(c in text for c in "ăâîșțĂÂÎȘȚ"):
        ro += 2
    return "ro" if ro >= en else "en"


PII = [re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), re.compile(r"(?:\+373|\b0)[67]\d[ -]?\d{3}[ -]?\d{3}\b"),
       re.compile(r"\b(?:\d[ -]?){13,16}\b")]


def _json_schema_ok(value: Any, schema: dict) -> str | None:
    """Validator minimal (type / required / properties / enum), suficient pentru output-uri de tip formular."""
    t = schema.get("type")
    types = {"object": dict, "array": list, "string": str, "number": (int, float), "integer": int, "boolean": bool}
    if t and not isinstance(value, types[t]):
        return f"tip {type(value).__name__}, așteptat {t}"
    if "enum" in schema and value not in schema["enum"]:
        return f"{value!r} nu e în {schema['enum']}"
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                return f"lipsește cheia {key!r}"
        for key, sub in schema.get("properties", {}).items():
            if key in value and (err := _json_schema_ok(value[key], sub)):
                return f"{key}: {err}"
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            if err := _json_schema_ok(item, schema["items"]):
                return f"[{i}]: {err}"
    return None


RUBRIC_PROMPT = """Ești evaluator. Notează RĂSPUNSUL după RUBRICĂ.
Întoarce DOAR JSON: {{"score": <0..1>, "reason": "<o propoziție>"}}

RUBRICĂ: {rubric}

ÎNTREBARE: {question}

RĂSPUNS: {answer}"""


def evaluate(a: Assertion, output: str, *, case_vars: dict[str, str], judge: Provider | None = None,
             judge_model: str = "") -> Check:
    t, v = a.type, a.value
    if t == "contains":
        ok = str(v) in output
        return Check(t, ok, float(ok), f"conține {v!r}" if ok else f"lipsește {v!r}", a.weight)
    if t == "icontains":
        values = v if isinstance(v, list) else [v]
        found = [x for x in values if str(x).lower() in output.lower()]
        ok = bool(found)
        return Check(t, ok, float(ok), f"găsit {found[0]!r}" if ok else f"lipsește oricare din {values}", a.weight)
    if t == "not_contains":
        values = v if isinstance(v, list) else [v]
        bad = [x for x in values if str(x).lower() in output.lower()]
        return Check(t, not bad, float(not bad), f"conține interzis {bad}" if bad else "ok", a.weight)
    if t in ("regex", "not_regex"):
        hit = re.search(v, output, flags=re.I | re.S) is not None
        ok = hit if t == "regex" else not hit
        return Check(t, ok, float(ok), f"/{v}/ {'găsit' if hit else 'negăsit'}", a.weight)
    if t in ("max_words", "min_words"):
        n = len(_words(output))
        ok = n <= v if t == "max_words" else n >= v
        return Check(t, ok, float(ok), f"{n} cuvinte (limită {v})", a.weight)
    if t == "language":
        expected = case_vars.get(v[1:], v) if isinstance(v, str) and v.startswith("$") else v
        got = detect_language(output)
        return Check(t, got == expected, float(got == expected), f"limba {got}, așteptat {expected}", a.weight)
    if t == "json_schema":
        try:
            data = json.loads(output)
        except json.JSONDecodeError as err:
            return Check(t, False, 0.0, f"nu e JSON: {err.msg}", a.weight)
        err = _json_schema_ok(data, v)
        return Check(t, err is None, float(err is None), err or "schemă respectată", a.weight)
    if t == "similar":
        ref, got = set(_words(str(v))), set(_words(output))
        score = len(ref & got) / len(ref | got) if ref | got else 1.0
        th = a.threshold if a.threshold is not None else 0.3
        return Check(t, score >= th, score, f"similaritate Jaccard {score:.2f} (prag {th})", a.weight)
    if t == "no_pii":
        leaks = [m.group(0) for p in PII for m in p.finditer(output)]
        return Check(t, not leaks, float(not leaks), f"date personale în răspuns: {leaks}" if leaks else "ok", a.weight)
    if t == "llm_rubric":
        if judge is None:
            raise ValueError("llm_rubric cere un judecător")
        prompt = RUBRIC_PROMPT.format(rubric=v, question=case_vars.get("question", ""), answer=output)
        raw = judge.complete(judge_model, "", prompt).text
        try:
            verdict = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
            score = max(0.0, min(1.0, float(verdict["score"])))
            reason = str(verdict.get("reason", ""))
        except (ValueError, KeyError, TypeError):
            return Check(t, False, 0.0, f"judecătorul a răspuns invalid: {raw[:80]!r}", a.weight)
        th = a.threshold if a.threshold is not None else 0.7
        return Check(t, score >= th, score, f"{score:.2f}: {reason}", a.weight)
    raise ValueError(f"tip necunoscut: {t}")
