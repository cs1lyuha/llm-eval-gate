"""Providerii și „casetele” (record / replay).

Problema evaluărilor în CI: un apel LLM costă bani, e lent și nu e determinist. Soluția,
ca la VCR pentru HTTP: înregistrăm o dată răspunsurile (`--record`), le salvăm în
`cassettes/*.json` lângă cod, iar CI-ul le **redă**. Dacă promptul sau un caz se schimbă,
cheia nu mai există în casetă, iar CI-ul pică cu un mesaj clar: „rulează local cu --record”.
Diff-ul casetei apare în pull request, deci și răspunsurile noi trec prin code review.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Protocol


@dataclass
class Completion:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0


class Provider(Protocol):
    def complete(self, model: str, system: str, prompt: str) -> Completion: ...


class FunctionProvider:
    """Provider dintr-o funcție Python. Pentru teste și pentru demo."""

    def __init__(self, fn: Callable[[str, str], str]) -> None:
        self.fn = fn
        self.calls = 0

    def complete(self, model: str, system: str, prompt: str) -> Completion:
        self.calls += 1
        t0 = time.perf_counter()
        text = self.fn(system, prompt)
        return Completion(text, model, len(system + prompt) // 4, len(text) // 4, (time.perf_counter() - t0) * 1000)


class ClaudeProvider:  # pragma: no cover - cere cheie API
    def __init__(self, client: Any = None) -> None:
        import anthropic
        self.client = client or anthropic.Anthropic()

    def complete(self, model: str, system: str, prompt: str) -> Completion:
        t0 = time.perf_counter()
        kwargs: dict[str, Any] = {"model": model, "max_tokens": 2048, "output_config": {"effort": "low"},
                                  "messages": [{"role": "user", "content": prompt}]}
        if system:
            kwargs["system"] = system
        msg = self.client.messages.create(**kwargs)
        text = "".join(b.text for b in msg.content if b.type == "text")
        return Completion(text, msg.model, msg.usage.input_tokens, msg.usage.output_tokens,
                          (time.perf_counter() - t0) * 1000)


class CassetteMiss(Exception):
    pass


def request_key(model: str, system: str, prompt: str) -> str:
    return hashlib.sha256(json.dumps([model, system, prompt], ensure_ascii=False).encode()).hexdigest()[:24]


class Cassette:
    """`replay`: doar din casetă (CI). `record`: apelează providerul pentru ce lipsește și salvează.
    `live`: mereu providerul, fără să salveze."""

    def __init__(self, path: str | Path, provider: Provider | None,
                 mode: Literal["replay", "record", "live"] = "replay") -> None:
        self.path = Path(path)
        self.provider = provider
        self.mode = mode
        self.entries: dict[str, dict] = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.used: set[str] = set()
        self.recorded = 0

    def complete(self, model: str, system: str, prompt: str) -> Completion:
        key = request_key(model, system, prompt)
        self.used.add(key)
        if self.mode != "live" and key in self.entries:
            return Completion(**self.entries[key]["completion"])
        if self.mode == "replay":
            raise CassetteMiss(f"răspuns lipsă în {self.path.name} (cheia {key}). Promptul s-a schimbat? "
                               "Rulează local cu --record și comite caseta.")
        if self.provider is None:
            raise CassetteMiss("niciun provider configurat pentru --record / --live")
        completion = self.provider.complete(model, system, prompt)
        if self.mode == "record":
            self.entries[key] = {"model": model, "prompt_preview": prompt[:120], "completion": asdict(completion)}
            self.recorded += 1
        return completion

    def save(self, prune: bool = False) -> None:
        """`prune` elimină intrările nefolosite, ca să nu crească la infinit."""
        if prune:
            self.entries = {k: v for k, v in self.entries.items() if k in self.used}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.entries, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                             encoding="utf-8")
