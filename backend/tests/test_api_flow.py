import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app import main


def test_portfolio_total_has_an_explicit_additive_breakdown(tmp_path):
    main.DB_PATH = tmp_path / "portfolio-breakdown.db"
    with TestClient(main.app) as client:
        portfolio = client.get("/api/v1/portfolio").json()

    assert "piggy" in portfolio
    assert round(portfolio["cash"] + portfolio["invested"] + portfolio["piggy"], 2) == round(portfolio["net_worth"], 2)
    assert round(portfolio["stocks"] + portfolio["funds"], 2) == round(portfolio["invested"], 2)
    assert portfolio["eligible_profit"] <= portfolio["cash"]


def test_dashboard_quest_summary_matches_current_quest_list(tmp_path):
    main.DB_PATH = tmp_path / "quest-summary.db"
    with TestClient(main.app) as client:
        dashboard = client.get("/api/v1/dashboard").json()
        quests = client.get("/api/v1/quests/daily").json()

    summary = dashboard["quest_summary"]
    assert summary["total"] == len(quests) == 5
    assert summary["done"] == sum(int(item["completed"]) for item in quests)
    assert summary["daily_total"] == sum(item["type"] == "daily" for item in quests)
    assert summary["weekly_total"] == sum(item["type"] == "weekly" for item in quests)


def test_demo_user_can_complete_critical_economy_flow(tmp_path):
    main.DB_PATH = tmp_path / "flow.db"
    with TestClient(main.app) as client:
        dashboard = client.get("/api/v1/dashboard")
        assert dashboard.status_code == 200
        assert dashboard.json()["user"]["display_name"] == "Саша"

        buy = client.post(
            "/api/v1/trades/buy",
            json={"instrument_id": 2, "quantity": "1.25"},
            headers={"Idempotency-Key": "integration-buy"},
        )
        assert buy.status_code == 200

        duplicate = client.post(
            "/api/v1/trades/buy",
            json={"instrument_id": 2, "quantity": "1.25"},
            headers={"Idempotency-Key": "integration-buy"},
        )
        assert duplicate.json() == buy.json()

        sell = client.post(
            "/api/v1/trades/sell",
            json={"instrument_id": 1, "quantity": "2"},
            headers={"Idempotency-Key": "integration-sell"},
        )
        assert sell.status_code == 200
        assert sell.json()["game_pnl"] > 0

        before = client.get("/api/v1/economy/conversion").json()
        convert = client.post("/api/v1/economy/convert", json={"tokens": "5"})
        assert convert.status_code == 200
        assert convert.json()["received"] > 0
        after = client.get("/api/v1/economy/conversion").json()
        assert after["eligible"] == before["eligible"] - 5

        contest = client.post(
            "/api/v1/contest/apply",
            json={
                "full_name": "Саша Альфов",
                "ege_year": 2026,
                "ege_subject": "Математика",
                "ege_score": 82,
                "certificate_mock": "DEMO",
                "consent": True,
            },
        )
        assert contest.json()["contest_tokens"] == 1000
        assert client.get("/api/v1/dashboard").json()["wallet"]["token_cash"] != "1000"


def test_trade_preview_returns_exact_buy_cost_and_sell_credit(tmp_path):
    main.DB_PATH = tmp_path / "trade-preview.db"
    with TestClient(main.app) as client:
        buy = client.post(
            "/api/v1/trades/preview?side=buy",
            json={"instrument_id": 1, "quantity": "2"},
        )
        sell = client.post(
            "/api/v1/trades/preview?side=sell",
            json={"instrument_id": 1, "quantity": "2"},
        )

    assert buy.status_code == 200
    assert buy.json()["cash_change"] == round(-buy.json()["quote"] * 2, 2)
    assert buy.json()["enough_cash"] is True
    assert sell.status_code == 200
    assert sell.json()["cash_change"] >= 0
    assert "game_pnl" in sell.json()


def test_conversion_uses_rolling_capital_and_cannot_be_improved_by_instant_balance_drop(tmp_path):
    main.DB_PATH = tmp_path / "rolling-conversion.db"
    with TestClient(main.app) as client:
        with main.db() as con:
            con.execute("DELETE FROM positions WHERE user_id=1")
            con.execute("UPDATE piggy_accounts SET balance_tkn='0' WHERE user_id=1")
            con.execute("UPDATE wallets SET token_cash='1000',eligible_profit_tokens='100',pending_activity_boost='0' WHERE user_id=1")
            con.execute("DELETE FROM net_worth_snapshots WHERE user_id=1")
            con.execute(
                "INSERT INTO net_worth_snapshots(user_id,token_net_worth,created_at) VALUES(1,'5000',?)",
                (main.now(),),
            )

        conversion = client.get("/api/v1/economy/conversion").json()

    assert conversion["current_net_worth"] == 1000
    assert conversion["rolling_average_net_worth"] == 5000
    assert conversion["rolling_net_worth"] == 5000
    assert conversion["rate"] == 22.36


def test_piggy_accepts_all_free_cash_and_credits_convertible_yield(tmp_path):
    main.DB_PATH = tmp_path / "piggy-unlimited.db"
    with TestClient(main.app) as client:
        with main.db() as con:
            con.execute("DELETE FROM positions WHERE user_id=1")
            con.execute("UPDATE wallets SET token_cash='5000',eligible_profit_tokens='0' WHERE user_id=1")
            con.execute("UPDATE piggy_accounts SET balance_tkn='0',current_apr='0.12',yield_remainder_tkn='0',last_accrual_at=? WHERE user_id=1", (main.now(),))

        deposited = client.post("/api/v1/piggy/deposit", json={"amount": "5000"})
        assert deposited.status_code == 200
        assert deposited.json() == {"balance": 5000.0, "cash": 0.0}

        accrual_time = datetime.now(timezone.utc)
        with main.db() as con:
            con.execute(
                "UPDATE piggy_accounts SET last_accrual_at=?,yield_remainder_tkn='0' WHERE user_id=1",
                ((accrual_time - timedelta(days=2)).isoformat(),),
            )
            assert main.accrue_piggy_yield(con, 1, accrual_time) == main.d("3.28")

        state = client.get("/api/v1/piggy").json()
        conversion = client.get("/api/v1/economy/conversion").json()
        converted = client.post("/api/v1/economy/convert", json={"tokens": "1"})

    assert state["cap"] is None
    assert state["unlimited_deposit"] is True
    assert state["yield_convertible_to_ac"] is True
    assert conversion["eligible"] == 3.28
    assert conversion["piggy_yield_convertible"] is True
    assert converted.status_code == 200
    assert converted.json()["burned"] == 1.0


def test_rolling_conversion_cap_counts_previous_conversions(tmp_path):
    main.DB_PATH = tmp_path / "conversion-cap.db"
    with TestClient(main.app) as client:
        with main.db() as con:
            con.execute("UPDATE wallets SET token_cash='1000',eligible_profit_tokens='1000',pending_activity_boost='1000' WHERE user_id=1")
            con.execute(
                "INSERT INTO conversions(user_id,tokens_burned,conversion_rate,base_ac,activity_bonus_ac,total_ac,rolling_net_worth,created_at) "
                "VALUES(1,'60','50','2400','600','3000','1000',?)",
                (main.now(),),
            )

        state = client.get("/api/v1/economy/conversion").json()
        preview = client.post("/api/v1/economy/conversion/preview", json={"tokens": "10"}).json()
        blocked = client.post("/api/v1/economy/convert", json={"tokens": "10"})

    assert state["caps"]["total"] == {"limit": 3000.0, "used": 3000.0, "remaining": 0.0}
    assert preview["tokens"] == 0
    assert preview["total_ac"] == 0
    assert blocked.status_code == 400
    assert "30 дней" in blocked.json()["detail"]


def test_bcrypt_auth_register_and_login(tmp_path):
    main.DB_PATH = tmp_path / "auth.db"
    with TestClient(main.app) as client:
        # Register new user
        reg = client.post(
            "/api/v1/auth/register",
            json={"name": "Новый Инвестор", "password": "securepassword123"},
        )
        assert reg.status_code == 200
        assert "access_token" in reg.json()

        # Login with correct credentials
        login_ok = client.post(
            "/api/v1/auth/login",
            json={"name": "Новый Инвестор", "password": "securepassword123"},
        )
        assert login_ok.status_code == 200
        assert "access_token" in login_ok.json()

        # Login with invalid password
        login_bad = client.post(
            "/api/v1/auth/login",
            json={"name": "Новый Инвестор", "password": "wrongpassword"},
        )
        assert login_bad.status_code == 401


def test_new_interactive_features(tmp_path):
    main.DB_PATH = tmp_path / "interactive.db"
    with TestClient(main.app) as client:
        # Profile Update
        update_res = client.put("/api/v1/auth/me", json={"display_name": "Алекс Инвестор", "birth_date": "2008-10-10"})
        assert update_res.status_code == 200
        assert update_res.json()["user"]["display_name"] == "Алекс Инвестор"

        # Streak Claim
        streak_res = client.post("/api/v1/streak/claim")
        assert streak_res.status_code == 200
        assert "message" in streak_res.json()

        # Quest Progress
        quest_res = client.post("/api/v1/quests/progress", json={"quest_action": "company_view"})
        assert quest_res.status_code == 200
        assert quest_res.json()["updated"] is True

        # Conversion and cart checkout are tested independently.
        client.post("/api/v1/trades/buy", json={"instrument_id": 1, "quantity": "2"}, headers={"Idempotency-Key": "k1"})
        client.post("/api/v1/trades/sell", json={"instrument_id": 1, "quantity": "2"}, headers={"Idempotency-Key": "k2"})
        client.post("/api/v1/economy/convert", json={"tokens": "5"})
        with main.db() as con:
            con.execute("UPDATE wallets SET alfa_coins='2700' WHERE user_id=1")

        cart_res = client.post("/api/v1/shop/orders/cart", json={"items": [{"shop_item_id": 1, "quantity": 1}]})
        assert cart_res.status_code == 200
        assert cart_res.json()["ok"] is True


def test_merch_prices_put_stickers_near_one_and_a_half_easy_months(tmp_path):
    main.DB_PATH = tmp_path / "merch-pacing.db"
    with TestClient(main.app) as client:
        conversion = client.get("/api/v1/economy/conversion").json()
        items = client.get("/api/v1/shop/items").json()
        dashboard = client.get("/api/v1/dashboard").json()

    cheapest = min(item["price_ac"] for item in items)
    prices = [item["price_ac"] for item in items]
    assert dashboard["wallet"]["alfa_coins"] == "0"
    assert conversion["caps"]["total"]["limit"] == 3000
    assert cheapest == 2700
    assert cheapest == 1800 * 1.5
    assert cheapest < conversion["caps"]["total"]["limit"]
    assert prices == [2700, 5000, 7300, 9600]


def test_tin_equipment_persists_per_slot_and_can_be_removed(tmp_path):
    main.DB_PATH = tmp_path / "tin-equipment.db"
    with TestClient(main.app) as client:
        with main.db() as con:
            for item_id in (1, 2, 4, 6):
                con.execute(
                    "INSERT INTO user_tamagotchi_items(user_id,item_id,acquired_at) VALUES(1,?,?)",
                    (item_id, main.now()),
                )

        assert client.post("/api/v1/tamagotchi/equip/1").json()["equipped_items"] == [1]
        assert set(client.post("/api/v1/tamagotchi/equip/2").json()["equipped_items"]) == {1, 2}
        assert set(client.post("/api/v1/tamagotchi/equip/4").json()["equipped_items"]) == {1, 2, 4}

        swapped = client.post("/api/v1/tamagotchi/equip/6").json()
        assert set(swapped["equipped_items"]) == {2, 4, 6}

        removed = client.post("/api/v1/tamagotchi/equip/6").json()
        assert removed["equipped"] is False
        assert set(removed["equipped_items"]) == {2, 4}
        persisted = json.loads(client.get("/api/v1/tamagotchi").json()["equipped_items_json"])
    assert set(persisted) == {2, 4}


def test_tin_interaction_cooldown_is_enforced_and_survives_reload(tmp_path):
    main.DB_PATH = tmp_path / "tin-cooldown.db"
    with TestClient(main.app) as client:
        initial = client.get("/api/v1/tamagotchi").json()
        assert initial["cooldowns"] == {"pet": 0, "talk": 0, "task": 0}

        first = client.post("/api/v1/tamagotchi/interact", json={"action": "pet"})
        assert first.status_code == 200
        assert first.json()["pet"]["cooldowns"]["pet"] == 30

        reloaded = client.get("/api/v1/tamagotchi").json()
        assert 1 <= reloaded["cooldowns"]["pet"] <= 30
        blocked = client.post("/api/v1/tamagotchi/interact", json={"action": "pet"})
        assert blocked.status_code == 429
        assert "Подожди" in blocked.json()["detail"]

        # Another action has an independent timer.
        assert client.post("/api/v1/tamagotchi/interact", json={"action": "talk"}).status_code == 200

        expired = (datetime.now(timezone.utc) - timedelta(seconds=31)).isoformat()
        with main.db() as con:
            con.execute(
                "UPDATE tamagotchi_interactions SET last_interaction_at=? WHERE user_id=1 AND action='pet'",
                (expired,),
            )
        assert client.post("/api/v1/tamagotchi/interact", json={"action": "pet"}).status_code == 200


def test_birth_date_changes_social_title_and_is_persisted(tmp_path):
    main.DB_PATH = tmp_path / "age-title.db"
    with TestClient(main.app) as client:
        teen = client.put("/api/v1/auth/me", json={"display_name": "Саша", "birth_date": "2010-05-14"})
        teen_feed = client.get("/api/v1/social/feed").json()
        adult = client.put("/api/v1/auth/me", json={"display_name": "Саша", "birth_date": "2000-05-14"})
        adult_dashboard = client.get("/api/v1/dashboard").json()
        adult_feed = client.get("/api/v1/social/feed").json()

    assert teen.json()["user"]["birth_date"] == "2010-05-14"
    assert teen_feed["title"] == "Тин-Ток"
    assert adult.json()["user"]["is_adult"] is True
    assert adult_dashboard["user"]["birth_date"] == "2000-05-14"
    assert adult_feed["title"] == "Ток"


def test_social_feed_profiles_and_friend_toggle(tmp_path):
    main.DB_PATH = tmp_path / "social.db"
    with TestClient(main.app) as client:
        feed = client.get("/api/v1/social/feed").json()
        user_id = feed["top_users"][0]["id"]
        profile = client.get(f"/api/v1/social/users/{user_id}").json()
        before = profile["is_friend"]
        toggled = client.post(f"/api/v1/social/friends/{user_id}").json()
        refreshed = client.get(f"/api/v1/social/users/{user_id}").json()

    assert len(feed["top_users"]) == 5
    assert feed["trades"]
    assert feed["posts"]
    assert feed["top_users"][0]["public_id"].startswith("TIN-")
    assert profile["capital_tkn"] > 0
    assert profile["positions"]
    assert profile["trades"]
    assert toggled["is_friend"] is (not before)
    assert refreshed["is_friend"] is (not before)
