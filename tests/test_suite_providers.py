import json

import pytest
from pydantic import ValidationError

from evalgate.providers import Cassette, CassetteMiss, FunctionProvider, request_key
from evalgate.suite import Suite, load_suite


def suite_dict(**kw):
    d = {"name": "t", "prompt": "prompts/test.txt",
         "cases": [{"id": "a", "vars": {"question": "Cât costă livrarea?"},
                    "assert": [{"type": "icontains", "value": "lei"}]}]}
    d.update(kw)
    return d


def test_load_and_render(tmp_path):
    (tmp_path / "suites").mkdir()
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "test.txt").write_text("Întrebare: {question}")
    (tmp_path / "suites" / "s.json").write_text(json.dumps(suite_dict()))
    s = load_suite(tmp_path / "suites" / "s.json")
    assert s.render(s.cases[0]) == "Întrebare: Cât costă livrarea?"
    assert s.cases[0].assert_[0].type == "icontains"


def test_missing_variable_is_explicit(tmp_path):
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "test.txt").write_text("{question} {context}")
    s = Suite.model_validate({**suite_dict(), "base_dir": tmp_path})
    with pytest.raises(KeyError, match="context"):
        s.render(s.cases[0])


@pytest.mark.parametrize("bad", [
    {"cases": []},
    {"cases": [{"id": "a", "vars": {}}, {"id": "a", "vars": {}}]},
    {"cases": [{"id": "A B", "vars": {}}]},
    {"cases": [{"id": "a", "vars": {}, "assert": [{"type": "contains"}]}]},
    {"cases": [{"id": "a", "vars": {}, "assert": [{"type": "magie", "value": 1}]}]},
])
def test_invalid_suites_rejected(bad):
    with pytest.raises(ValidationError):
        Suite.model_validate(suite_dict(**bad))


def test_cassette_record_then_replay(tmp_path):
    path = tmp_path / "c.json"
    live = FunctionProvider(lambda s, p: "răspuns: " + p)
    rec = Cassette(path, live, mode="record")
    assert rec.complete("m", "", "salut").text == "răspuns: salut"
    rec.save()
    replay = Cassette(path, None, mode="replay")
    assert replay.complete("m", "", "salut").text == "răspuns: salut"
    assert live.calls == 1
    with pytest.raises(CassetteMiss, match="--record"):
        replay.complete("m", "", "alt prompt")


def test_cassette_prune_removes_unused(tmp_path):
    path = tmp_path / "c.json"
    rec = Cassette(path, FunctionProvider(lambda s, p: p), mode="record")
    rec.complete("m", "", "unu")
    rec.complete("m", "", "doi")
    rec.save()
    again = Cassette(path, None, mode="replay")
    again.complete("m", "", "unu")
    again.save(prune=True)
    assert list(json.loads(path.read_text())) == [request_key("m", "", "unu")]
