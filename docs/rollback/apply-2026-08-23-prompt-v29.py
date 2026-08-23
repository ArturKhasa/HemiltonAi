"""Регламент v29: снять противоречие про вопрос в конце хода.

Регламент требует «последнее предложение — вопрос, всегда», и он же на шагах 2 и
6 требует «вопросов не добавляй». Модель читает оба правила разом; кодовый гейт
при этом наказывает за отсутствие вопроса. 212 ответов из 563 ушли без вопроса —
большинство законно, звеньями связок, но правило обязано это признавать.
"""
import asyncio, asyncpg, os, sys, difflib

DSN = os.environ["DATABASE_URL"].replace("+asyncpg", "")

EDITS = [
    ("""- Последнее предложение сообщения — вопрос. Всегда, кроме шага 9.""",
     """- Последнее предложение сообщения — вопрос. Кроме двух случаев: шага 9 и
  шагов, где следом автоматически уходит связка (2 и 6). Там вопрос задаёт
  последнее сообщение связки, а твоя реплика — только короткое присоединение.
  Во всех остальных ходах вопрос обязателен."""),
]


async def main():
    c = await asyncpg.connect(DSN, statement_cache_size=0)
    row = await c.fetchrow(
        "select id, name, type_id, content from prompt_versions"
        " where is_active and type_id = 1 order by id desc limit 1"
    )
    old = row["content"]
    new = old
    for i, (before, after) in enumerate(EDITS, 1):
        if before not in new:
            print(f"!!! правка {i} не нашла своё место — прерываю")
            await c.close()
            sys.exit(1)
        new = new.replace(before, after, 1)

    print("\n".join(difflib.unified_diff(
        old.splitlines(), new.splitlines(),
        fromfile=f"регламент v{row['id']}", tofile="регламент v(новая)", lineterm="", n=2,
    )))
    print(f"\nбыло {len(old)} символов, стало {len(new)}")

    if "--apply" in sys.argv:
        async with c.transaction():
            await c.execute("update prompt_versions set is_active = false where is_active")
            next_id = await c.fetchval("select max(id) + 1 from prompt_versions")
            new_id = await c.fetchval(
                "insert into prompt_versions"
                " (name, version, type_id, content, is_active, created_at)"
                " values ($1, $2, $3, $4, true, now()) returning id",
                row["name"], f"v{next_id}", row["type_id"], new,
            )
            await c.execute("update prompt_versions set version = $1 where id = $2",
                            f"v{new_id}", new_id)
        print(f"\nПРИМЕНЕНО: создана версия {new_id}, версия {row['id']} выключена")
    await c.close()

asyncio.run(main())
