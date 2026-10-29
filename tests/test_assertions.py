import json

import pytest

from evalgate.assertions import detect_language, evaluate
from evalgate.providers import FunctionProvider
from evalgate.suite import Assertion

OUT = "Puteți returna produsul în 30 de zile de la livrare. Banii ajung în 5-10 zile lucrătoare."


def check(type_, value=None, output=OUT, **kw):
    return evaluate(Assertion(type=type_, value=value, **kw), output, case_vars={"question": "q", "lang": "ro"})


@pytest.mark.parametrize("type_,value,ok", [
    ("contains", "30 de zile", True), ("contains", "30 De Zile", False),
    ("icontains", "30 DE ZILE", True), ("icontains", ["14 zile", "30 de zile"], True),
    ("not_contains", ["garantat", "100%"], True), ("not_contains", "livrare", False),
    ("regex", r"\d+\s*-\s*\d+ zile", True), ("not_regex", r"rambursare aprobată", True),
    ("max_words", 10, False), ("min_words", 5, True),
    ("language", "ro", True), ("language", "$lang", True), ("language", "en", False),
])
def test_deterministic(type_, value, ok):
    assert check(type_, value).passed is ok


def test_language_detection():
    assert detect_language("Вы можете вернуть товар в течение 30 дней.") == "ru"
    assert detect_language("You can return the product within 30 days.") == "en"
    assert detect_language(OUT) == "ro"


def test_json_schema():
    schema = {"type": "object", "required": ["intent", "urgent"],
              "properties": {"intent": {"enum": ["retur", "livrare"]}, "urgent": {"type": "boolean"}}}
    assert check("json_schema", schema, output='{"intent": "retur", "urgent": false}').passed
    assert "enum" not in check("json_schema", schema, output='{"intent": "x", "urgent": false}').reason
    assert not check("json_schema", schema, output='{"intent": "retur"}').passed
    assert not check("json_schema", schema, output="nu e json").passed


def test_similar_threshold():
    c = check("similar", "Produsul poate fi returnat în 30 de zile", threshold=0.2)
    assert c.passed and 0 < c.score < 1


def test_no_pii():
    assert check("no_pii").passed
    assert not check("no_pii", output="Clientul ana@mail.md, tel 069 123 456").passed


def test_llm_rubric_with_judge():
    judge = FunctionProvider(lambda s, p: json.dumps({"score": 0.9 if "30 de zile" in p else 0.2, "reason": "x"}))
    a = Assertion(type="llm_rubric", value="Menționează termenul de retur")
    assert evaluate(a, OUT, case_vars={"question": "q"}, judge=judge).passed
    assert not evaluate(a, "Nu știu.", case_vars={"question": "q"}, judge=judge).passed
    broken = FunctionProvider(lambda s, p: "nu e json")
    assert "invalid" in evaluate(a, OUT, case_vars={}, judge=broken).reason
    with pytest.raises(ValueError):
        evaluate(a, OUT, case_vars={})
