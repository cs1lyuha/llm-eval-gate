"""CLI.

    python -m evalgate run suites/support.json                         # replay din casete (CI)
    python -m evalgate run suites/support.json --prompt prompts/support_v2.txt
    python -m evalgate run suites/support.json --mode record --provider claude   # înregistrează răspunsuri noi
    python -m evalgate run suites/support.json --update-baseline

Exit code 1 când gate-ul pică, deci pasul din CI pică și el. Dacă există
GITHUB_STEP_SUMMARY, raportul apare direct în pagina job-ului de pe GitHub.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from evalgate.providers import Cassette, ClaudeProvider, FunctionProvider
from evalgate.runner import decide, load_baseline, run_suite, save_baseline, to_json, to_markdown
from evalgate.suite import load_suite


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="evalgate")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("suite")
    r.add_argument("--prompt", help="alt șablon de prompt (de ex. versiunea nouă)")
    r.add_argument("--mode", choices=["replay", "record", "live"], default="replay")
    r.add_argument("--provider", choices=["demo", "claude"], default="demo")
    r.add_argument("--cassette-dir", default="cassettes")
    r.add_argument("--baseline")
    r.add_argument("--update-baseline", action="store_true")
    r.add_argument("--report", help="scrie raportul Markdown și aici")
    r.add_argument("--json", help="rezultatele complete în JSON")
    a = p.parse_args(argv)

    suite = load_suite(a.suite, a.prompt)
    if a.provider == "claude":
        provider = judge_provider = ClaudeProvider()
    else:
        from evalgate.demo import demo_judge, demo_model
        provider, judge_provider = FunctionProvider(demo_model), FunctionProvider(demo_judge)
    cdir = Path(a.cassette_dir)
    model = Cassette(cdir / f"{suite.name}.{a.provider}.json", provider, a.mode)
    judge = Cassette(cdir / f"{suite.name}.{a.provider}.judge.json", judge_provider, a.mode)

    run = run_suite(suite, model, judge)
    if a.mode == "record":
        model.save()
        judge.save()
    baseline_path = a.baseline or f"baselines/{suite.name}.json"
    baseline = load_baseline(baseline_path)
    decision = decide(run, suite, baseline)
    md = to_markdown(run, decision)
    print(md)
    for target in filter(None, [a.report, os.environ.get("GITHUB_STEP_SUMMARY")]):
        with open(target, "a", encoding="utf-8") as f:
            f.write(md)
    if a.json:
        Path(a.json).write_text(json.dumps(to_json(run, decision), ensure_ascii=False, indent=1), encoding="utf-8")
    if a.update_baseline:
        save_baseline(run, baseline_path)
        print(f"baseline actualizat: {baseline_path}")
        return 0
    return 0 if decision.passed else 1


if __name__ == "__main__":
    sys.exit(main())
