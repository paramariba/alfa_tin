from fastapi.testclient import TestClient

from app import main


def test_rostics_wheel_has_equal_win_and_empty_segments(tmp_path):
    main.DB_PATH = tmp_path / "wheel-config.db"
    with TestClient(main.app) as client:
        payload = client.get("/api/v1/shop/rostics-wheel").json()

    assert payload["cost_tkn"] == 50
    assert len(payload["segments"]) == 8
    assert sum(bool(segment["is_win"]) for segment in payload["segments"]) == 4
    assert payload["win_probability"] == 0.5


def test_rostics_spin_charges_tokens_once_and_records_result(tmp_path, monkeypatch):
    main.DB_PATH = tmp_path / "wheel-spin.db"
    outcomes = iter((0, 1))
    monkeypatch.setattr(main.secrets, "randbelow", lambda _: next(outcomes))

    with TestClient(main.app) as client:
        with main.db() as con:
            con.execute("UPDATE wallets SET token_cash='100' WHERE user_id=1")

        headers = {"Idempotency-Key": "wheel-spin-1"}
        first = client.post("/api/v1/shop/rostics-wheel/spin", headers=headers)
        repeated = client.post("/api/v1/shop/rostics-wheel/spin", headers=headers)
        second = client.post(
            "/api/v1/shop/rostics-wheel/spin",
            headers={"Idempotency-Key": "wheel-spin-2"},
        )
        state = client.get("/api/v1/shop/rostics-wheel").json()

    assert first.status_code == 200
    assert first.json()["result"]["is_win"] is True
    assert first.json()["token_cash"] == 50
    assert repeated.json() == first.json()
    assert second.status_code == 200
    assert second.json()["result"]["is_win"] is False
    assert second.json()["token_cash"] == 0
    assert len(state["history"]) == 2
    assert state["token_cash"] == 0


def test_rostics_spin_rejects_insufficient_balance_without_charge(tmp_path):
    main.DB_PATH = tmp_path / "wheel-balance.db"
    with TestClient(main.app) as client:
        with main.db() as con:
            con.execute("UPDATE wallets SET token_cash='49.99' WHERE user_id=1")

        response = client.post(
            "/api/v1/shop/rostics-wheel/spin",
            headers={"Idempotency-Key": "wheel-too-expensive"},
        )
        state = client.get("/api/v1/shop/rostics-wheel").json()

    assert response.status_code == 400
    assert state["token_cash"] == 49.99
    assert state["history"] == []
