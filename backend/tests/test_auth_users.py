from fastapi.testclient import TestClient

from app import main


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_name_password_auth_and_user_isolation(tmp_path, monkeypatch):
    main.DB_PATH = tmp_path / "auth-users.db"
    monkeypatch.setattr(main, "AUTH_REQUIRED", True)

    with TestClient(main.app) as client:
        assert client.get("/api/v1/dashboard").status_code == 401

        alice = client.post("/api/v1/auth/register", json={"name": "Алиса", "password": "alice-pass"})
        bob = client.post("/api/v1/auth/register", json={"name": "Борис", "password": "boris-pass"})
        assert alice.status_code == 200
        assert bob.status_code == 200
        assert alice.json()["user"]["id"] != bob.json()["user"]["id"]
        assert alice.json()["user"]["public_id"].startswith("TIN-")

        duplicate = client.post("/api/v1/auth/register", json={"name": "  АЛИСА ", "password": "another-pass"})
        assert duplicate.status_code == 409

        alice_headers = auth_headers(alice.json()["access_token"])
        bob_headers = auth_headers(bob.json()["access_token"])
        assert client.get("/api/v1/auth/me", headers=alice_headers).json()["display_name"] == "Алиса"
        assert client.get("/api/v1/auth/me", headers=bob_headers).json()["display_name"] == "Борис"

        client.post("/api/v1/onboarding/complete", json={"shop_item_id": 4}, headers=alice_headers)
        client.post("/api/v1/onboarding/complete", json={"shop_item_id": 4}, headers=bob_headers)
        bought = client.post(
            "/api/v1/trades/buy",
            json={"instrument_id": 1, "quantity": "1"},
            headers={**alice_headers, "Idempotency-Key": "alice-buy"},
        )
        assert bought.status_code == 200
        assert bought.json()["is_first_purchase"] is True
        assert bought.json()["share_prompt"] is True
        assert len(client.get("/api/v1/portfolio/positions", headers=alice_headers).json()) == 1
        assert client.get("/api/v1/portfolio/positions", headers=bob_headers).json() == []

        bob_id = bob.json()["user"]["id"]
        bob_public_id = bob.json()["user"]["public_id"]
        search = client.get(f"/api/v1/social/users?search={bob_public_id.lower()}", headers=alice_headers)
        assert [user["id"] for user in search.json()] == [bob_id]
        added = client.post(f"/api/v1/social/friends/{bob_id}", headers=alice_headers)
        assert added.json()["is_friend"] is True
        assert [user["id"] for user in client.get("/api/v1/social/feed?scope=friends", headers=alice_headers).json()["friends"]] == [bob_id]
        assert client.get("/api/v1/social/feed?scope=friends", headers=bob_headers).json()["friends"] == []

        posted = client.post(
            "/api/v1/social/posts",
            json={"trade_id": bought.json()["trade_id"], "comment": "Моя первая покупка @SBER и слежу за @TMOS"},
            headers=alice_headers,
        )
        assert posted.status_code == 200
        alice_id = alice.json()["user"]["id"]
        client.post(f"/api/v1/social/friends/{alice_id}", headers=bob_headers)
        friend_posts = client.get("/api/v1/social/feed?scope=friends", headers=bob_headers).json()["posts"]
        assert friend_posts[0]["comment"].startswith("Моя первая покупка")
        assert [item["ticker"] for item in friend_posts[0]["mentions"]] == ["SBER", "TMOS"]
        assert "trade" not in friend_posts[0]
        forbidden = client.post("/api/v1/social/posts", json={"trade_id": bought.json()["trade_id"], "comment": "Чужая"}, headers=bob_headers)
        assert forbidden.status_code == 404

        login = client.post("/api/v1/auth/login", json={"name": "  алиса ", "password": "alice-pass"})
        assert login.status_code == 200
        assert login.json()["user"]["id"] == alice.json()["user"]["id"]


def test_profanity_rejects_only_the_post(tmp_path, monkeypatch):
    main.DB_PATH = tmp_path / "moderation.db"
    monkeypatch.setattr(main, "AUTH_REQUIRED", True)

    with TestClient(main.app) as client:
        registered = client.post("/api/v1/auth/register", json={"name": "Нарушитель", "password": "safe-pass"})
        headers = auth_headers(registered.json()["access_token"])
        regular = client.post("/api/v1/social/posts", json={"comment": "Сравниваю @YDEX и @TMOS"}, headers=headers)
        assert regular.status_code == 200
        assert regular.json()["mentions"] == ["YDEX", "TMOS"]
        rejected = client.post("/api/v1/social/posts", json={"comment": "Это блядь плохой пост"}, headers=headers)
        assert rejected.status_code == 422
        assert "не отправлен" in rejected.json()["detail"].lower()
        spaced = client.post("/api/v1/social/posts", json={"comment": "Это б л я д ь плохой пост"}, headers=headers)
        assert spaced.status_code == 422
        with_digits = client.post("/api/v1/social/posts", json={"comment": "Это б1л2я3д4ь плохой пост"}, headers=headers)
        assert with_digits.status_code == 422
        assert client.post("/api/v1/social/posts", json={"comment": "х у й"}, headers=headers).status_code == 422
        assert client.post("/api/v1/social/posts", json={"comment": "х1у2й"}, headers=headers).status_code == 422
        assert client.post("/api/v1/social/posts", json={"comment": "пездос"}, headers=headers).status_code == 422
        assert client.post("/api/v1/social/posts", json={"comment": "п е з д о с"}, headers=headers).status_code == 422
        assert client.post("/api/v1/social/posts", json={"comment": "п1е2з3д4о5с"}, headers=headers).status_code == 422
        assert client.get("/api/v1/dashboard", headers=headers).status_code == 200
        assert client.post("/api/v1/auth/login", json={"name": "Нарушитель", "password": "safe-pass"}).status_code == 200
        corrected = client.post("/api/v1/social/posts", json={"comment": "Исправленный пост про @YDEX"}, headers=headers)
        assert corrected.status_code == 200


def test_only_post_owner_can_delete_it(tmp_path, monkeypatch):
    main.DB_PATH = tmp_path / "post-deletion.db"
    monkeypatch.setattr(main, "AUTH_REQUIRED", True)

    with TestClient(main.app) as client:
        alice = client.post("/api/v1/auth/register", json={"name": "Алиса", "password": "alice-pass"}).json()
        bob = client.post("/api/v1/auth/register", json={"name": "Борис", "password": "boris-pass"}).json()
        alice_headers = auth_headers(alice["access_token"])
        bob_headers = auth_headers(bob["access_token"])

        created = client.post("/api/v1/social/posts", json={"comment": "Мой пост про @YDEX"}, headers=alice_headers)
        post_id = created.json()["post_id"]
        assert client.delete(f"/api/v1/social/posts/{post_id}", headers=bob_headers).status_code == 403
        assert client.delete(f"/api/v1/social/posts/{post_id}", headers=alice_headers).json()["message"] == "Пост удалён"
        assert client.delete(f"/api/v1/social/posts/{post_id}", headers=alice_headers).status_code == 404
        assert all(post["id"] != post_id for post in client.get("/api/v1/social/feed", headers=alice_headers).json()["posts"])


def test_profanity_is_rejected_in_registration_and_profile_name(tmp_path, monkeypatch):
    main.DB_PATH = tmp_path / "name-moderation.db"
    monkeypatch.setattr(main, "AUTH_REQUIRED", True)

    with TestClient(main.app) as client:
        assert client.post("/api/v1/auth/register", json={"name": "пездос", "password": "safe-pass"}).status_code == 422
        assert client.post("/api/v1/auth/register", json={"name": "п е з д о с", "password": "safe-pass"}).status_code == 422
        assert client.post("/api/v1/auth/register", json={"name": "п1е2з3д4о5с", "password": "safe-pass"}).status_code == 422

        registered = client.post("/api/v1/auth/register", json={"name": "Нормальное Имя", "password": "safe-pass"}).json()
        headers = auth_headers(registered["access_token"])
        rejected = client.put(
            "/api/v1/auth/me",
            json={"display_name": "х у й", "birth_date": "2009-01-01"},
            headers=headers,
        )
        assert rejected.status_code == 422
        assert client.get("/api/v1/auth/me", headers=headers).json()["display_name"] == "Нормальное Имя"


def test_password_can_be_changed_from_security_screen(tmp_path, monkeypatch):
    main.DB_PATH = tmp_path / "password-change.db"
    monkeypatch.setattr(main, "AUTH_REQUIRED", True)

    with TestClient(main.app) as client:
        registered = client.post("/api/v1/auth/register", json={"name": "Алиса", "password": "old-pass"}).json()
        headers = auth_headers(registered["access_token"])

        wrong = client.post(
            "/api/v1/auth/password",
            json={"current_password": "wrong-pass", "new_password": "new-safe-pass"},
            headers=headers,
        )
        assert wrong.status_code == 400
        same = client.post(
            "/api/v1/auth/password",
            json={"current_password": "old-pass", "new_password": "old-pass"},
            headers=headers,
        )
        assert same.status_code == 422
        changed = client.post(
            "/api/v1/auth/password",
            json={"current_password": "old-pass", "new_password": "new-safe-pass"},
            headers=headers,
        )
        assert changed.json()["message"] == "Пароль изменён"
        assert client.post("/api/v1/auth/login", json={"name": "Алиса", "password": "old-pass"}).status_code == 401
        assert client.post("/api/v1/auth/login", json={"name": "Алиса", "password": "new-safe-pass"}).status_code == 200
