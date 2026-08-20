import asyncio

import httpx
from fastapi.testclient import TestClient

from app import main


def test_finam_provider_sends_bearer_token(monkeypatch):
    monkeypatch.setenv("FINAM_API_SECRET", "test-secret")
    seen_headers = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/sessions":
            return httpx.Response(200, json={"token": "session-token"})
        seen_headers.append(request.headers.get("Authorization"))
        return httpx.Response(
            200,
            json={"quote": {"last": {"value": "276.98"}, "close": {"value": "277.72"}, "timestamp": "2026-08-19T13:02:02Z"}},
        )

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = main.FinamTradeApiProvider(client=client)
            result = await provider.get_quote("SBER@MISX")
            assert result["quote"]["last"]["value"] == "276.98"

    asyncio.run(scenario())
    assert seen_headers == ["Bearer session-token"]


def test_finam_provider_refreshes_expired_session(monkeypatch):
    monkeypatch.setenv("FINAM_API_SECRET", "test-secret")
    session_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal session_count
        if request.url.path == "/v1/sessions":
            session_count += 1
            return httpx.Response(200, json={"token": f"token-{session_count}"})
        if request.headers["Authorization"] == "Bearer token-1":
            return httpx.Response(401, json={"detail": "expired"})
        return httpx.Response(200, json={"quote": {"last": {"value": "100"}}})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = main.FinamTradeApiProvider(client=client)
            await provider.get_quote("SBER@MISX")

    asyncio.run(scenario())
    assert session_count == 2


def test_finam_provider_retries_transient_errors(monkeypatch):
    monkeypatch.setenv("FINAM_API_SECRET", "test-secret")
    quote_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal quote_count
        if request.url.path == "/v1/sessions":
            return httpx.Response(200, json={"token": "token"})
        quote_count += 1
        if quote_count == 1:
            return httpx.Response(503, json={"detail": "temporary"})
        return httpx.Response(200, json={"quote": {"last": {"value": "100"}}})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = main.FinamTradeApiProvider(client=client)
            await provider.get_quote("SBER@MISX")

    asyncio.run(scenario())
    assert quote_count == 2


def test_sync_finam_snapshot_updates_database(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "market.db")
    main.init_db()

    class FakeProvider:
        jwt_token = None

        async def refresh_session(self):
            self.jwt_token = "token"
            return self.jwt_token

        async def get_quote(self, symbol):
            return {
                "quote": {
                    "last": {"value": "123.45"},
                    "close": {"value": "120"},
                    "timestamp": "2026-08-19T13:02:02Z",
                }
            }

    updated = asyncio.run(main.sync_finam_snapshot(FakeProvider()))

    assert updated == len(main.INSTRUMENTS)
    with main.db() as con:
        row = con.execute("SELECT real_price_rub,previous_close,source,source_timestamp FROM instruments WHERE ticker='SBER'").fetchone()
    assert tuple(row) == ("123.45", "120", "finam", "2026-08-19T13:02:02Z")


def test_moex_provider_parses_quote_and_candles():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/candles.json"):
            return httpx.Response(
                200,
                json={"candles": {"columns": ["begin", "close"], "data": [["2026-08-18", 120], ["2026-08-19", 123.45]]}},
            )
        return httpx.Response(
            200,
            json={
                "securities": {"columns": ["SECID", "PREVPRICE"], "data": [["SBER", 120]]},
                "marketdata": {
                    "columns": ["SECID", "LAST", "LCURRENTPRICE", "MARKETPRICE", "SYSTIME"],
                    "data": [["SBER", 123.45, None, None, "18:40:00"]],
                },
            },
        )

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = main.MoexIssProvider(client=client)
            quote = await provider.get_quote("SBER")
            candles = await provider.get_candles("SBER")
            return quote, candles

    quote, candles = asyncio.run(scenario())
    assert quote["last"] == "123.45"
    assert quote["previous_close"] == "120"
    assert candles[-1] == {"t": "2026-08-19", "v": 1.23}


def test_sync_moex_snapshot_updates_database(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "moex-market.db")
    main.init_db()

    class FakeProvider:
        async def get_quote(self, ticker):
            return {"last": "123.45", "previous_close": "120", "timestamp": "2026-08-19T13:02:02Z"}

    updated = asyncio.run(main.sync_moex_snapshot(FakeProvider()))

    assert updated == len(main.INSTRUMENTS)
    with main.db() as con:
        row = con.execute("SELECT real_price_rub,previous_close,source,source_timestamp FROM instruments WHERE ticker='SBER'").fetchone()
    assert tuple(row) == ("123.45", "120", "moex", "2026-08-19T13:02:02Z")


def test_demo_market_snapshot_moves_fallback_prices_in_both_directions(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "demo-market.db")
    main.init_db()

    main.sync_demo_market_snapshot(tick=10)
    with main.db() as con:
        first = {row["id"]: main.d(row["real_price_rub"]) for row in con.execute("SELECT id,real_price_rub FROM instruments")}
    main.sync_demo_market_snapshot(tick=11)
    with main.db() as con:
        rows = con.execute("SELECT id,real_price_rub,source,source_timestamp FROM instruments ORDER BY id").fetchall()

    changes = [main.d(row["real_price_rub"]) - first[row["id"]] for row in rows]
    assert any(change > 0 for change in changes)
    assert any(change < 0 for change in changes)
    assert all(row["source"] == "demo-simulated" and row["source_timestamp"] for row in rows)


def test_demo_price_change_affects_a_purchase_result(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "demo-position.db")
    with TestClient(main.app) as client:
        main.sync_demo_market_snapshot(tick=10)
        bought = client.post(
            "/api/v1/trades/buy",
            json={"instrument_id": 2, "quantity": "10"},
            headers={"Idempotency-Key": "demo-moving-buy"},
        )
        main.sync_demo_market_snapshot(tick=11)
        sold = client.post(
            "/api/v1/trades/sell",
            json={"instrument_id": 2, "quantity": "10"},
            headers={"Idempotency-Key": "demo-moving-sell"},
        )

    assert bought.status_code == 200
    assert sold.status_code == 200
    assert sold.json()["game_pnl"] > 0
