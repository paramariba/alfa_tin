import asyncio
import json
from datetime import date

import httpx
from fastapi.testclient import TestClient

from app import main
from app.ai_coach import GeminiCoach, LESSON_SYSTEM_PROMPT, fallback_monthly_analysis


def test_lesson_assistant_uses_strict_system_prompt(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        answer = {"answer": "Акция — это небольшая доля в компании.", "key_points": ["Цена может меняться"]}
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(answer, ensure_ascii=False)}]}}]})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            coach = GeminiCoach(client=client)
            return await coach.ask_lesson(
                {"id": 3, "title": "Ты — совладелец", "description": "Что означает акция"},
                "Что такое акция?",
            )

    result = asyncio.run(scenario())
    assert result["method"] == "gemini"
    assert "простыми словами" in captured["systemInstruction"]["parts"][0]["text"]
    assert "не выдумывай факты" in LESSON_SYSTEM_PROMPT
    assert captured["generationConfig"]["responseMimeType"] == "application/json"


def test_lesson_assistant_falls_back_to_available_gemini_model(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite")
    requested_models = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_models.append(str(request.url))
        if "gemini-2.5-flash:" in str(request.url):
            return httpx.Response(429, request=request, json={"error": {"status": "RESOURCE_EXHAUSTED"}})
        answer = {"answer": "План помогает заранее ограничить риск.", "key_points": ["Сначала цель и срок"]}
        return httpx.Response(200, request=request, json={"candidates": [{"content": {"parts": [{"text": json.dumps(answer, ensure_ascii=False)}]}}]})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await GeminiCoach(client=client).ask_lesson(
                {"id": 1, "title": "План", "description": "Зачем нужен план"},
                "Зачем мне план?",
            )

    result = asyncio.run(scenario())
    assert len(requested_models) == 2
    assert result["method"] == "gemini"
    assert result["model"] == "gemini-3.5-flash-lite"


def test_monthly_gemini_drops_invented_decision_ids(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    def handler(_: httpx.Request) -> httpx.Response:
        result = {
            "summary": "Была одна продажа с убытком.",
            "strengths": [],
            "mistakes": [
                {"title": "Минусовая продажа", "explanation": "Результат ниже нуля.", "related_decision_ids": ["trade-2", "invented-99"]},
                {"title": "Выдумка", "explanation": "Нет основания.", "related_decision_ids": ["invented-100"]},
            ],
            "next_steps": ["Заранее записывать условия выхода"],
        }
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(result, ensure_ascii=False)}]}}]})

    facts = {
        "month": "2026-08",
        "metrics": {"decisions_count": 1},
        "decisions": [{"id": "trade-2", "kind": "sell", "game_pnl": -12, "at": "2026-08-10T10:00:00+00:00"}],
    }

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await GeminiCoach(client=client).analyze_month(facts)

    result = asyncio.run(scenario())
    assert result["mistakes"] == [
        {"title": "Минусовая продажа", "explanation": "Результат ниже нуля.", "related_decision_ids": ["trade-2"]}
    ]


def seed_synthetic_month(tmp_path):
    main.DB_PATH = tmp_path / "coach.db"
    main.init_db()
    with main.db() as con:
        for index in range(1, 4):
            con.execute(
                "INSERT INTO trades(user_id,instrument_id,side,quantity,raw_quote_tkn,raw_pnl,game_pnl,cash_change_tkn,status,idempotency_key,executed_at) "
                "VALUES(1,1,'buy','1','3','0','0','-3','executed',?,?)",
                (f"synthetic-buy-{index}", f"2026-08-0{index}T10:00:00+00:00"),
            )
        con.execute(
            "INSERT INTO trades(user_id,instrument_id,side,quantity,raw_quote_tkn,raw_pnl,game_pnl,cash_change_tkn,status,idempotency_key,executed_at) "
            "VALUES(1,1,'sell','1','2.8','-1.2','-12','0','executed','synthetic-loss','2026-08-10T10:00:00+00:00')"
        )
        con.execute(
            "INSERT INTO trades(user_id,instrument_id,side,quantity,raw_quote_tkn,raw_pnl,game_pnl,cash_change_tkn,status,idempotency_key,executed_at) "
            "VALUES(1,1,'sell','1','3.2','0.5','5','8','executed','synthetic-win','2026-08-12T10:00:00+00:00')"
        )
        con.execute("INSERT INTO lesson_progress VALUES(1,1,'2026-08-15T10:00:00+00:00')")
        con.execute(
            "INSERT INTO ledger_entries(user_id,currency,event_type,amount,balance_after,reference_type,reference_id,metadata_json,created_at) "
            "VALUES(1,'TKN','PIGGY_DEPOSIT','-25','500','','','{}','2026-08-16T10:00:00+00:00')"
        )


def test_monthly_report_metrics_on_synthetic_decisions(tmp_path):
    seed_synthetic_month(tmp_path)
    with main.db() as con:
        facts = main.build_monthly_facts(con, "2026-08")

    assert facts["metrics"]["trades_count"] == 5
    assert facts["metrics"]["buy_count"] == 3
    assert facts["metrics"]["sell_count"] == 2
    assert facts["metrics"]["realized_pnl_tkn"] == -7.0
    assert facts["metrics"]["money_lost_tkn"] == 12.0
    assert facts["metrics"]["winning_sells"] == 1
    assert facts["metrics"]["losing_sells"] == 1
    assert facts["metrics"]["unique_buy_tickers"] == 1
    assert facts["metrics"]["lessons_completed"] == 1
    analysis = fallback_monthly_analysis(facts)
    related = {decision_id for item in analysis["mistakes"] for decision_id in item["related_decision_ids"]}
    losing_decision = next(item["id"] for item in facts["decisions"] if item["kind"] == "sell" and item["game_pnl"] == -12.0)
    assert losing_decision in related
    assert related <= {item["id"] for item in facts["decisions"]}


def test_monthly_report_endpoint_caches_same_input(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    seed_synthetic_month(tmp_path)
    with TestClient(main.app) as client:
        first = client.get("/api/v1/coach/monthly-report?month=2026-08")
        second = client.get("/api/v1/coach/monthly-report?month=2026-08")
    assert first.status_code == 200
    assert second.json() == first.json()
    assert first.json()["metrics"]["money_lost_tkn"] == 12.0
    with main.db() as con:
        assert con.execute("SELECT COUNT(*) FROM monthly_ai_reports WHERE month='2026-08'").fetchone()[0] == 1


def test_lesson_requires_correct_answer_and_rewards_once(tmp_path):
    main.DB_PATH = tmp_path / "lesson.db"
    with TestClient(main.app) as client:
        wrong = client.post("/api/v1/learning/lessons/1/complete", json={"answer_index": 0})
        assert wrong.status_code == 400
        before = client.get("/api/v1/dashboard").json()
        correct = client.post("/api/v1/learning/lessons/1/complete", json={"answer_index": 1})
        repeat = client.post("/api/v1/learning/lessons/1/complete", json={"answer_index": 1})
        after = client.get("/api/v1/dashboard").json()
        quests = client.get("/api/v1/quests/daily").json()
    assert correct.json()["xp"] == 80
    assert repeat.json()["already_completed"] is True
    assert repeat.json()["xp"] == 0
    assert after["user"]["xp"] - before["user"]["xp"] == 80
    assert next(item for item in quests if item["id"] == 2)["progress"] == 1
    assert next(item for item in quests if item["id"] == 4)["progress"] == 1


def test_current_lesson_client_requires_the_complete_three_answer_quiz(tmp_path):
    main.DB_PATH = tmp_path / "lesson-full-quiz.db"
    with TestClient(main.app) as client:
        lessons = client.get("/api/v1/learning/courses").json()
        partial = client.post("/api/v1/learning/lessons/1/complete", json={"answers": [1]})
        one_wrong = client.post("/api/v1/learning/lessons/1/complete", json={"answers": [1, 0, 0]})
        correct = client.post("/api/v1/learning/lessons/1/complete", json={"answers": [1, 0, 2]})

    assert len(lessons) == 18
    assert lessons[-1]["title"] == "Что делать, когда рынок падает"
    assert partial.status_code == 400
    assert one_wrong.status_code == 400
    assert correct.status_code == 200
    assert correct.json()["xp"] == 80


def test_gamification_reset_preserves_financial_history(tmp_path):
    seed_synthetic_month(tmp_path)
    with main.db() as con:
        cash_before = con.execute("SELECT token_cash FROM wallets WHERE user_id=1").fetchone()[0]
        trades_before = con.execute("SELECT COUNT(*) FROM trades WHERE user_id=1").fetchone()[0]
        con.execute("INSERT INTO user_achievements VALUES(1,3,'2026-08-16T10:00:00+00:00')")
        main.reset_gamification_progress(con)
    with main.db() as con:
        assert con.execute("SELECT COUNT(*) FROM lesson_progress").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM user_achievements").fetchone()[0] == 0
        assert con.execute("SELECT xp FROM users WHERE id=1").fetchone()[0] == 0
        assert con.execute("SELECT SUM(progress) FROM user_quests WHERE user_id=1").fetchone()[0] == 0
        assert con.execute("SELECT token_cash FROM wallets WHERE user_id=1").fetchone()[0] == cash_before
        assert con.execute("SELECT COUNT(*) FROM trades WHERE user_id=1").fetchone()[0] == trades_before
        assert all(not item["unlocked"] for item in main.achievement_items(con))


def test_daily_quests_roll_over_but_weekly_period_stays(tmp_path):
    main.DB_PATH = tmp_path / "quest-periods.db"
    main.init_db()
    with main.db() as con:
        day_one = main.ensure_current_quests(con, at=date(2026, 8, 19))
        con.execute("UPDATE user_quests SET progress=1,completed=1 WHERE user_id=1 AND quest_id=1 AND period_key=?", (day_one["daily"],))
        day_two = main.ensure_current_quests(con, at=date(2026, 8, 20))
        old_progress = con.execute("SELECT progress FROM user_quests WHERE user_id=1 AND quest_id=1 AND period_key=?", (day_one["daily"],)).fetchone()[0]
        new_progress = con.execute("SELECT progress FROM user_quests WHERE user_id=1 AND quest_id=1 AND period_key=?", (day_two["daily"],)).fetchone()[0]
    assert old_progress == 1
    assert new_progress == 0
    assert day_one["weekly"] == day_two["weekly"]


def test_achievement_unlocks_only_from_actions_after_reset(tmp_path):
    main.DB_PATH = tmp_path / "achievement-reset.db"
    main.init_db()
    with main.db() as con:
        main.reset_gamification_progress(con)
        assert main.achievement_items(con)[0]["unlocked"] is False
        con.execute(
            "INSERT INTO trades(user_id,instrument_id,side,quantity,raw_quote_tkn,raw_pnl,game_pnl,cash_change_tkn,status,idempotency_key,executed_at) "
            "VALUES(1,1,'buy','1','3','0','0','-3','executed','after-reset',?)",
            (main.now(),),
        )
        assert main.achievement_items(con)[0]["unlocked"] is True
    with TestClient(main.app) as client:
        claimed = client.post("/api/v1/achievements/1/claim")
        repeated = client.post("/api/v1/achievements/1/claim")
    assert claimed.status_code == 200
    assert claimed.json()["xp"] == 100
    assert repeated.status_code == 400
