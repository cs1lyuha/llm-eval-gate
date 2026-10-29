"""Demo-ul complet, pe casetele comise: v1 trece gate-ul, v2 pică, un prompt nou fără casetă pică explicit."""

import json
from pathlib import Path

from evalgate.__main__ import main

ROOT = Path(__file__).resolve().parent.parent


def run(*args, tmp=None):
    return main(["run", str(ROOT / "suites/support.json"), "--cassette-dir", str(ROOT / "cassettes"),
                 "--baseline", str(ROOT / "baselines/support-replies.json"), *args])


def test_v1_passes_gate(capsys):
    assert run() == 0
    assert "20/20" in capsys.readouterr().out


def test_v2_regression_is_caught(capsys, tmp_path):
    out_json = tmp_path / "r.json"
    assert run("--prompt", "prompts/support_v2.txt", "--json", str(out_json)) == 1
    data = json.loads(out_json.read_text())
    assert not data["decision"]["passed"]
    assert {"retur-termen", "retur-ru"} <= set(data["decision"]["regressions"])


def test_new_prompt_without_cassette_fails_with_instructions(tmp_path, capsys):
    new = tmp_path / "v3.txt"
    new.write_text("Răspunde: {question}")
    assert run("--prompt", str(new)) == 1
    assert "--record" in capsys.readouterr().out


def test_step_summary_is_written(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    run()
    assert summary.read_text().startswith("## ✅")
