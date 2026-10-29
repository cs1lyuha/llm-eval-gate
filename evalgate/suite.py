"""Formatul unei suite de evaluare (JSON), validat cu Pydantic.

{
  "name": "support-replies",
  "prompt": "prompts/support_v1.txt",          // șablon cu {variabile}
  "model": "claude-haiku-5-5",
  "gate": {"min_pass_rate": 0.9, "max_score_drop": 0.03},
  "defaults": [{"type": "max_words", "value": 120}],   // aserțiuni aplicate tuturor cazurilor
  "cases": [
    {"id": "retur-30-zile", "critical": true, "vars": {"question": "..."},
     "assert": [{"type": "icontains", "value": "30 de zile"}]}
  ]
}
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

AssertionType = Literal["contains", "icontains", "not_contains", "regex", "not_regex", "json_schema",
                        "max_words", "min_words", "language", "similar", "llm_rubric", "no_pii"]


class Assertion(BaseModel):
    type: AssertionType
    value: Any = None
    weight: float = Field(default=1.0, gt=0)
    threshold: float | None = Field(default=None, ge=0, le=1)  # pentru similar / llm_rubric

    @model_validator(mode="after")
    def needs_value(self) -> "Assertion":
        if self.type not in ("no_pii",) and self.value is None:
            raise ValueError(f"aserțiunea {self.type} cere `value`")
        return self


class Case(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    vars: dict[str, str]
    assert_: list[Assertion] = Field(default_factory=list, alias="assert")
    critical: bool = False
    tags: list[str] = Field(default_factory=list)


class Gate(BaseModel):
    min_pass_rate: float = Field(default=0.9, ge=0, le=1)
    max_score_drop: float = Field(default=0.03, ge=0, le=1)


class Suite(BaseModel):
    name: str
    prompt: str
    system: str = ""
    model: str = "claude-haiku-5-5"
    judge_model: str = "claude-sonnet-5-5"
    gate: Gate = Field(default_factory=Gate)
    defaults: list[Assertion] = Field(default_factory=list)
    cases: list[Case] = Field(min_length=1)
    base_dir: Path = Path(".")

    @model_validator(mode="after")
    def unique_ids(self) -> "Suite":
        ids = [c.id for c in self.cases]
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            raise ValueError(f"id-uri duplicate: {sorted(dup)}")
        return self

    def prompt_template(self) -> str:
        return (self.base_dir / self.prompt).read_text(encoding="utf-8")

    def render(self, case: Case) -> str:
        template = self.prompt_template()
        missing = [k for k in _placeholders(template) if k not in case.vars]
        if missing:
            raise KeyError(f"cazul {case.id} nu are variabilele {missing}")
        return template.format_map(case.vars)


def _placeholders(template: str) -> list[str]:
    import string
    return [field for _, field, _, _ in string.Formatter().parse(template) if field]


def load_suite(path: str | Path, prompt_override: str | None = None) -> Suite:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if prompt_override:
        data["prompt"] = prompt_override
    return Suite.model_validate({**data, "base_dir": path.parent.parent if path.parent.name == "suites" else path.parent})
