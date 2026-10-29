"""Model și judecător SIMULATE pentru demo (fără cheie API).

`demo_model` se comportă ca un LLM care respectă (sau nu) instrucțiunile din prompt:
- „limba clientului” → răspunde în rusă la întrebări în rusă, altfel mereu în română;
- „o singură propoziție” → păstrează doar prima propoziție (și pierde termenele din a doua).
Așa `support_v2.txt` produce o regresie reală, pe care gate-ul trebuie s-o prindă.
Cu o cheie API, aceleași suite rulează pe Claude: `--provider claude --mode record`.
"""

from __future__ import annotations

import json
import re

FACTS = {
    "retur": {"ro": ["Puteți returna produsul.", "Termenul este de 30 de zile de la livrare, iar cererea trece prin verificare."],
              "ru": ["Вы можете вернуть товар.", "Срок — 30 дней с момента доставки, заявка проходит проверку."]},
    "livrare": {"ro": ["Livrarea standard costă 50 de lei.", "Peste 1000 de lei este gratuită, în 1-3 zile lucrătoare."],
                "ru": ["Стандартная доставка стоит 50 леев.", "При заказе от 1000 леев — бесплатно, 1-3 рабочих дня."]},
    "garantie": {"ro": ["Produsele noi au garanție de 24 de luni.", "Bateriile au 12 luni, iar reparația durează maximum 14 zile."],
                 "ru": ["Новые товары имеют гарантию 24 месяца.", "На батареи — 12 месяцев, ремонт до 14 дней."]},
    "rambursare": {"ro": ["Banii ajung pe card în 5-10 zile lucrătoare.", "Rambursarea se face după verificarea produsului la depozit."],
                   "ru": ["Деньги поступят на карту за 5-10 рабочих дней.", "Возврат после проверки товара на складе."]},
    "rate": {"ro": ["Oferim rate fără dobândă pe 6, 10 sau 12 luni.", "Se aplică pentru produse de peste 3000 de lei."],
             "ru": ["Рассрочка без процентов на 6, 10 или 12 месяцев.", "Для товаров дороже 3000 леев."]},
    "plata": {"ro": ["Plata ramburs este disponibilă până la 20 000 de lei.", "Nova Poșta acceptă doar numerar."],
              "ru": ["Наложенный платёж доступен до 20 000 леев.", "Nova Poșta принимает только наличные."]},
}
KEYWORDS = {
    "retur": ["return", "retur", "вернуть", "возврат товар"], "livrare": ["livrar", "доставк"],
    "garantie": ["garan", "гарант"], "rambursare": ["banii", "ramburs", "деньги"],
    "rate": ["rate", "рассроч"], "plata": ["ramburs", "plăt", "наличн", "оплат"],
}


def _topic(question: str) -> str | None:
    q = question.lower()
    best = max(KEYWORDS, key=lambda t: sum(k in q for k in KEYWORDS[t]))
    return best if any(k in q for k in KEYWORDS[best]) else None


def demo_model(system: str, prompt: str) -> str:
    question = prompt.rsplit("Întrebarea clientului:", 1)[-1].strip()
    is_ru = bool(re.search(r"[а-яА-Я]", question))
    lang = "ru" if is_ru and "limba clientului" in prompt else "ro"
    topic = _topic(question)
    if topic is None:
        return ("Извините, по этому вопросу вас проконсультирует оператор." if lang == "ru"
                else "Îmi pare rău, pentru această întrebare vă va ajuta un operator.")
    sentences = FACTS[topic][lang]
    if "o singură propoziție" in prompt:
        sentences = sentences[:1]
    return " ".join(sentences)


def demo_judge(system: str, prompt: str) -> str:
    """Judecător simulat: penalizează promisiunile și răspunsurile fără cifre concrete."""
    answer = prompt.rsplit("RĂSPUNS:", 1)[-1].lower()
    if "operator" in answer or "оператор" in answer:  # escaladarea corectă nu are nevoie de cifre
        return json.dumps({"score": 1.0, "reason": "escaladare corectă la operator"})
    score = 1.0
    if re.search(r"(garantat|sigur primiți|aprobat)", answer):
        score -= 0.6
    if not re.search(r"\d", answer):
        score -= 0.5
    return json.dumps({"score": max(score, 0.0), "reason": "răspuns concret" if score > 0.7 else "lipsesc detalii concrete"})
