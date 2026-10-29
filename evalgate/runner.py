"""Rularea unei suite și decizia gate-ului.

Scorul unui caz e media ponderată a aserțiunilor. Un caz trece dacă toate aserțiunile trec.
Gate-ul pică dacă:
1. un caz `critical` pică (de ex. „nu promite rambursări”);
2. rata de trecere e sub `min_pass_rate`;
3. scorul mediu scade cu mai mult de `max_score_drop` față de baseline.
În plus, raportul listează **regresiile** (cazuri care treceau în baseline și acum pică).
"""

from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path

from evalgate.assertions import Check, evaluate
from evalgate.providers import Provider
from evalgate.suite import Suite


@dataclass
class CaseResult:
    id: str
    passed: bool
    score: float
    critical: bool
    output: str
    checks: list[Check]
    latency_ms: float = 0.0
    tokens: int = 0
    error: str = ""


@dataclass
class RunResult:
    suite: str
    prompt: str
    cases: list[CaseResult]

    @property
    def pass_rate(self) -> float:
        return sum(c.passed for c in self.cases) / len(self.cases)

    @property
    def score(self) -> float:
        return statistics.mean(c.score for c in self.cases)

    @property
    def critical_failures(self) -> list[str]:
        return [c.id for c in self.cases if c.critical and not c.passed]

    def to_baseline(self) -> dict:
        return {"suite": self.suite, "prompt": self.prompt, "pass_rate": round(self.pass_rate, 4),
                "score": round(self.score, 4), "cases": {c.id: {"passed": c.passed, "score": round(c.score, 4)}
                                                         for c in self.cases}}


def run_suite(suite: Suite, provider: Provider, judge: Provider | None = None) -> RunResult:
    results = []
    for case in suite.cases:
        prompt = suite.render(case)
        try:
            completion = provider.complete(suite.model, suite.system, prompt)
        except Exception as err:  # o eroare de provider (sau casetă lipsă) pică acest caz, nu toată rularea
            results.append(CaseResult(case.id, False, 0.0, case.critical, "", [], error=str(err)))
            continue
        checks = [evaluate(a, completion.text, case_vars=case.vars, judge=judge, judge_model=suite.judge_model)
                  for a in suite.defaults + case.assert_]
        total_w = sum(c.weight for c in checks) or 1.0
        score = sum(c.score * c.weight for c in checks) / total_w if checks else 1.0
        results.append(CaseResult(case.id, all(c.passed for c in checks), score, case.critical, completion.text,
                                  checks, completion.latency_ms, completion.input_tokens + completion.output_tokens))
    return RunResult(suite.name, suite.prompt, results)


@dataclass
class GateDecision:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    regressions: list[str] = field(default_factory=list)
    fixes: list[str] = field(default_factory=list)
    score_delta: float | None = None


def decide(run: RunResult, suite: Suite, baseline: dict | None) -> GateDecision:
    d = GateDecision(True)
    if run.critical_failures:
        d.reasons.append(f"cazuri critice picate: {', '.join(run.critical_failures)}")
    if run.pass_rate < suite.gate.min_pass_rate:
        d.reasons.append(f"rata de trecere {run.pass_rate:.1%} < minimul {suite.gate.min_pass_rate:.0%}")
    if baseline:
        d.score_delta = run.score - baseline["score"]
        if d.score_delta < -suite.gate.max_score_drop:
            d.reasons.append(f"scorul a scăzut cu {-d.score_delta:.3f} (maxim permis {suite.gate.max_score_drop})")
        before = baseline.get("cases", {})
        for c in run.cases:
            if c.id in before:
                if before[c.id]["passed"] and not c.passed:
                    d.regressions.append(c.id)
                elif not before[c.id]["passed"] and c.passed:
                    d.fixes.append(c.id)
    d.passed = not d.reasons
    return d


def save_baseline(run: RunResult, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(run.to_baseline(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def load_baseline(path: str | Path) -> dict | None:
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def to_markdown(run: RunResult, decision: GateDecision) -> str:
    icon = "✅" if decision.passed else "❌"
    delta = f" ({decision.score_delta:+.3f} față de baseline)" if decision.score_delta is not None else ""
    lines = [f"## {icon} Evaluare `{run.suite}` — prompt `{run.prompt}`", "",
             f"- trecute: **{sum(c.passed for c in run.cases)}/{len(run.cases)}** ({run.pass_rate:.1%})",
             f"- scor mediu: **{run.score:.3f}**{delta}"]
    if decision.reasons:
        lines += ["", "**Gate picat:**"] + [f"- {r}" for r in decision.reasons]
    if decision.regressions:
        lines += ["", "**Regresii** (treceau înainte): " + ", ".join(f"`{r}`" for r in decision.regressions)]
    if decision.fixes:
        lines += ["", "**Reparate:** " + ", ".join(f"`{r}`" for r in decision.fixes)]
    failed = [c for c in run.cases if not c.passed]
    if failed:
        lines += ["", "| caz | critic | scor | motiv |", "|---|:-:|---:|---|"]
        for c in failed:
            why = c.error or "; ".join(f"{k.type}: {k.reason}" for k in c.checks if not k.passed)
            lines.append(f"| `{c.id}` | {'⚠️' if c.critical else ''} | {c.score:.2f} | {why[:160]} |")
    return "\n".join(lines) + "\n"


def to_json(run: RunResult, decision: GateDecision) -> dict:
    return {"decision": asdict(decision), "pass_rate": run.pass_rate, "score": run.score,
            "cases": [{**{k: v for k, v in asdict(c).items() if k != "checks"},
                       "checks": [asdict(k) for k in c.checks]} for c in run.cases]}
