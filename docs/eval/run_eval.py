"""Офлайн-прогон моделей на реальных ходах из прода.

Берём записанный контекст боевого прогона (системный промпт + вся история хода
вместе с вызовами инструментов), подменяем системный промпт на текущий и просим
модель написать ответ заново. Дальше считаем нарушения теми же проверками,
которыми их ловит runner на бою.
"""
import asyncio, json, os, random, sys, time
from collections import defaultdict

sys.path.insert(0, "/src")

from app.sales.funnel_steps import asks_confirmation, lets_client_go, reply_advances_funnel
from app.sales.offer_terms import (
    data_requested_after_payment, hedges_delivery_price,
    promises_both_gifts, promises_offer_another_day,
)
from app.sales.product_photo import claims_picture_already_sent

MODELS = (sys.argv[1] if len(sys.argv) > 1 else "gpt-5.6-luna").split(",")
PER_CLASS = int(sys.argv[2]) if len(sys.argv) > 2 else 3
CONCURRENCY = 4
ADVANCING = {363, 379, 380, 399}

CENTER = "по центру"

# Схема ответа — та же, что у боевого агента (app.ai.schemas.AgentOutput), но в
# strict-виде: без неё модели отвечают то JSON, то прозой, и сравнивать нечего.
OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "reply_text", "next_status", "confidence_score", "need_curator",
        "curator_reason", "selected_script", "source_script_id",
        "detected_objection", "action_hint",
    ],
    "properties": {
        "reply_text": {"type": "string"},
        "next_status": {"type": ["string", "null"]},
        "confidence_score": {"type": "number"},
        "need_curator": {"type": "boolean"},
        "curator_reason": {"type": ["string", "null"]},
        "selected_script": {"type": ["string", "null"]},
        "source_script_id": {"type": ["integer", "null"]},
        "detected_objection": {"type": ["string", "null"]},
        "action_hint": {
            "type": "string",
            "enum": ["send_reply", "wait", "close_dialog", "escalate"],
        },
    },
}


async def system_prompt() -> str:
    from app.ai.prompts import get_system_prompt
    from app.db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        return await get_system_prompt(db, type_id=1)


def violations(case: dict, reply: str, script_id) -> list[str]:
    bad = []
    text = reply or ""
    if CENTER in text.lower():
        bad.append("имя по центру груди")
    # Вопрос спрашиваем только с собственной реплики модели: когда указан скрипт,
    # вопрос задаёт последнее звено связки — так же считает и боевой гейт.
    if "?" not in text and not script_id:
        bad.append("ход без вопроса")
    if hedges_delivery_price(text):
        bad.append("доставка обтекаемо")
    if promises_both_gifts(text):
        bad.append("оба подарка")
    if promises_offer_another_day(text):
        bad.append("подарок на другой день")
    if data_requested_after_payment(text):
        bad.append("данные после оплаты")
    if claims_picture_already_sent(text):
        bad.append("ссылка на картинку вместо картинки")
    cls = case["class"]
    if cls in ("отказ", "переспрос", "правка дизайна"):
        if reply_advances_funnel(text, script_id, ADVANCING):
            bad.append("двигает воронку на отказе")
    if cls == "отказ" and lets_client_go(text):
        bad.append("отпускает клиента")
    if cls == "сверка подряд" and asks_confirmation(text):
        bad.append("третья сверка подряд")
    return bad


async def ask(client, model: str, system: str, case: dict) -> dict:
    started = time.monotonic()
    try:
        r = await client.responses.create(
            model=model, instructions=system, input=case["messages"],
            text={"format": {
                "type": "json_schema", "name": "agent_output", "strict": True,
                "schema": OUTPUT_SCHEMA,
            }},
        )
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"[:200]}
    raw = (r.output_text or "").strip()
    reply, script_id, conf = raw, None, None
    try:
        parsed = json.loads(raw)
        reply = parsed.get("reply_text") or ""
        script_id = parsed.get("source_script_id")
        conf = parsed.get("confidence_score")
    except (json.JSONDecodeError, AttributeError):
        pass
    u = r.usage
    return {
        "reply": reply, "script_id": script_id, "confidence": conf,
        "ms": int((time.monotonic() - started) * 1000),
        "in_tok": getattr(u, "input_tokens", 0), "out_tok": getattr(u, "output_tokens", 0),
        "json_ok": reply is not raw,
    }


async def main():
    from openai import AsyncOpenAI

    cases = json.load(open(os.environ.get("EVAL_DIR", ".eval") + "/cases.json", encoding="utf-8"))
    random.seed(20260823)
    picked = []
    by_class = defaultdict(list)
    for c in cases:
        by_class[c["class"]].append(c)
    for cls, items in by_class.items():
        random.shuffle(items)
        picked += items[: PER_CLASS if cls == "обычный ход" else min(len(items), PER_CLASS * 3)]
    print(f"ходов в прогоне: {len(picked)}")

    system = await system_prompt()
    print(f"системный промпт: {len(system)} символов\n")
    client = AsyncOpenAI()
    sem = asyncio.Semaphore(CONCURRENCY)

    report = {}
    for model in MODELS:
        async def one(case):
            async with sem:
                return case, await ask(client, model, system, case)

        results = await asyncio.gather(*(one(c) for c in picked))
        stats = {
            "нарушений": 0, "ходов": 0, "ошибок": 0, "json": 0,
            "in_tok": 0, "out_tok": 0, "ms": 0, "скрипт указан": 0, "conf": [],
        }
        detail = defaultdict(int)
        for case, out in results:
            if out.get("error"):
                stats["ошибок"] += 1
                print(f"  [{model}] ошибка на run {case['run_id']}: {out['error']}")
                continue
            stats["ходов"] += 1
            stats["json"] += 1 if out["json_ok"] else 0
            stats["in_tok"] += out["in_tok"]
            stats["out_tok"] += out["out_tok"]
            stats["ms"] += out["ms"]
            stats["скрипт указан"] += 1 if out["script_id"] else 0
            if out["confidence"] is not None:
                stats["conf"].append(out["confidence"])
            bad = violations(case, out["reply"], out["script_id"])
            stats["нарушений"] += len(bad)
            for b in bad:
                detail[b] += 1
            if bad and os.environ.get("EVAL_DUMP"):
                print(f"\n  [{model}] {case['class']} | run {case['run_id']} | клиент: {case['client_text'][:60]!r}")
                print(f"    скрипт={out['script_id']} нарушения={bad}")
                print(f"    ответ: {(out['reply'] or '')[:200]!r}")
        report[model] = (stats, dict(detail), results)

    print("\n" + "=" * 78)
    for model, (s, detail, _) in report.items():
        n = max(s["ходов"], 1)
        conf = sum(s["conf"]) / len(s["conf"]) if s["conf"] else 0
        print(f"\n{model}")
        print(f"  ходов {s['ходов']}, ошибок {s['ошибок']}, валидный JSON {s['json']}/{n}")
        print(f"  нарушений всего {s['нарушений']} → {s['нарушений'] / n:.2f} на ход")
        print(f"  скрипт указан {s['скрипт указан']}/{n}, средняя уверенность {conf:.2f}")
        print(f"  среднее время {s['ms'] // n} мс, токенов вход/выход {s['in_tok']}/{s['out_tok']}")
        for k, v in sorted(detail.items(), key=lambda kv: -kv[1]):
            print(f"    {v:3d}  {k}")

    with open(os.environ.get("EVAL_DIR", ".eval") + "/last_run.json", "w", encoding="utf-8") as f:
        json.dump(
            {m: {"stats": {k: v for k, v in s.items() if k != "conf"}, "detail": d}
             for m, (s, d, _) in report.items()},
            f, ensure_ascii=False, indent=2,
        )

asyncio.run(main())
