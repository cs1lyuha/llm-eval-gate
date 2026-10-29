from evalgate.providers import CassetteMiss, FunctionProvider
from evalgate.runner import decide, load_baseline, run_suite, save_baseline, to_markdown
from evalgate.suite import Suite


def make_suite(tmp_path, **gate):
    (tmp_path / "prompts").mkdir(exist_ok=True)
    (tmp_path / "prompts" / "p.txt").write_text("Q: {question}")
    return Suite.model_validate({
        "name": "s", "prompt": "prompts/p.txt", "base_dir": tmp_path, "gate": gate or {"min_pass_rate": 0.5},
        "defaults": [{"type": "max_words", "value": 50}],
        "cases": [
            {"id": "retur", "critical": True, "vars": {"question": "retur?"},
             "assert": [{"type": "icontains", "value": "30 de zile"}]},
            {"id": "livrare", "vars": {"question": "livrare?"}, "assert": [{"type": "icontains", "value": "50 de lei"}]},
            {"id": "politete", "vars": {"question": "salut"}, "assert": [{"type": "not_contains", "value": "idiot"}]},
        ]})


GOOD = FunctionProvider(lambda s, p: {"Q: retur?": "Aveți 30 de zile.", "Q: livrare?": "Costă 50 de lei."}.get(p, "Bună!"))
WORSE = FunctionProvider(lambda s, p: {"Q: retur?": "Aveți 30 de zile."}.get(p, "Bună!"))
BROKEN = FunctionProvider(lambda s, p: "Nu știu.")


def test_all_pass(tmp_path):
    s = make_suite(tmp_path)
    run = run_suite(s, GOOD)
    assert run.pass_rate == 1.0 and decide(run, s, None).passed


def test_critical_failure_blocks_even_with_good_pass_rate(tmp_path):
    s = make_suite(tmp_path, min_pass_rate=0.3)
    d = decide(run_suite(s, BROKEN), s, None)
    assert not d.passed and "retur" in d.reasons[0]


def test_regression_against_baseline(tmp_path):
    s = make_suite(tmp_path, min_pass_rate=0.5, max_score_drop=0.05)
    base = run_suite(s, GOOD)
    save_baseline(base, tmp_path / "b.json")
    d = decide(run_suite(s, WORSE), s, load_baseline(tmp_path / "b.json"))
    assert not d.passed and d.regressions == ["livrare"] and d.score_delta < 0
    md = to_markdown(run_suite(s, WORSE), d)
    assert "❌" in md and "`livrare`" in md


def test_fix_is_reported(tmp_path):
    s = make_suite(tmp_path)
    save_baseline(run_suite(s, WORSE), tmp_path / "b.json")
    d = decide(run_suite(s, GOOD), s, load_baseline(tmp_path / "b.json"))
    assert d.passed and d.fixes == ["livrare"] and d.score_delta > 0


def test_provider_error_fails_only_that_case(tmp_path):
    s = make_suite(tmp_path)

    class Flaky:
        def complete(self, model, system, prompt):
            if "livrare" in prompt:
                raise CassetteMiss("lipsă")
            return GOOD.complete(model, system, prompt)

    run = run_suite(s, Flaky())
    failed = [c for c in run.cases if not c.passed]
    assert [c.id for c in failed] == ["livrare"] and "lipsă" in failed[0].error


def test_default_assertions_apply_to_all(tmp_path):
    s = make_suite(tmp_path)
    run = run_suite(s, FunctionProvider(lambda sys, p: "30 de zile, 50 de lei " + "cuvânt " * 60))
    assert all(any(k.type == "max_words" and not k.passed for k in c.checks) for c in run.cases)
