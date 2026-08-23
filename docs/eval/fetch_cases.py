"""Собрать реальные ходы из прода в файл — основу для офлайн-прогона моделей."""
import asyncio, asyncpg, json, os, re, sys

sys.path.insert(0, "/src")
from app.sales.funnel_steps import client_refused, client_wants_design_edit, asks_confirmation
from app.sales.non_answer import is_non_answer

DSN = os.environ["DATABASE_URL"].replace("+asyncpg", "")
OUT = os.environ.get("EVAL_DIR", ".eval") + "/cases.json"


# Явный уход клиента. Голое «нет» сюда не берём: в проде это чаще всего ответ на
# нашу же сверку («Всё верно?» → «Нет»), то есть правка макета, а не отказ.
_WALKS_AWAY_RE = re.compile(
    r"не\s+(?:надо|нужно|хочу|буду|интересует|интересно|актуально)"
    r"|ничего\s+не\s+(?:надо|нужно)|откажусь|отказ\w*|передума\w+"
    r"|не\s+актуальн\w*|отмен(?:а|ю|ите|ить)\w*",
    re.I,
)


def classify(user_text: str, our_recent: list[str]) -> str:
    if client_refused(user_text) and _WALKS_AWAY_RE.search(user_text or ""):
        return "отказ"
    if is_non_answer(user_text):
        return "переспрос"
    if client_wants_design_edit(user_text):
        return "правка дизайна"
    if sum(1 for t in our_recent if asks_confirmation(t)) >= 2:
        return "сверка подряд"
    return "обычный ход"


async def main():
    c = await asyncpg.connect(DSN, statement_cache_size=0)
    rows = await c.fetch("""
        select r.id, r.dialog_id, r.full_context, r.source_script_id,
               r.confidence_score, m.text as reply_text
        from ai_runs r
        left join messages m on m.id = r.output_message_id
        where r.full_context is not null
          and r.full_context->>'system' like '%ТЕХНИЧЕСКАЯ ЧАСТЬ%'
          and r.created_at > '2026-08-17'
        order by r.id desc
        limit 2000
    """)
    await c.close()

    cases = []
    for r in rows:
        ctx = r["full_context"]
        if isinstance(ctx, str):
            ctx = json.loads(ctx)
        msgs = ctx.get("messages") or []
        # Хвост — финальный ответ модели, его отрезаем: именно его и переигрываем.
        while msgs and isinstance(msgs[-1], dict) and msgs[-1].get("type") == "message":
            msgs = msgs[:-1]
        if not msgs:
            continue
        user_texts = [
            m.get("content") for m in msgs
            if isinstance(m, dict) and m.get("role") == "user" and isinstance(m.get("content"), str)
        ]
        # Последняя реплика клиента — не служебный блок в квадратных скобках.
        client_text = next(
            (t for t in reversed(user_texts) if not t.lstrip().startswith("[")), ""
        )
        our_recent = [
            m.get("content") for m in msgs
            if isinstance(m, dict) and m.get("role") == "assistant"
            and isinstance(m.get("content"), str)
        ][-3:]
        cases.append({
            "run_id": r["id"],
            "dialog_id": r["dialog_id"],
            "class": classify(client_text, our_recent),
            "client_text": client_text[:200],
            "messages": msgs,
            "baseline_reply": r["reply_text"],
            "baseline_script_id": r["source_script_id"],
            "baseline_confidence": float(r["confidence_score"] or 0),
        })

    by_class: dict[str, list] = {}
    for case in cases:
        by_class.setdefault(case["class"], []).append(case)
    print("реальных ходов найдено:", len(cases))
    for k, v in sorted(by_class.items(), key=lambda kv: -len(kv[1])):
        print(f"  {len(v):4d}  {k}")

    import os
    os.makedirs(os.environ.get("EVAL_DIR", ".eval"), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(cases, f, ensure_ascii=False)
    print("сохранено в", OUT)

asyncio.run(main())
