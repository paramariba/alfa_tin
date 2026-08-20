from datetime import datetime

from app import main


def at(day: int, hour: int = 10, minute: int = 15) -> datetime:
    return datetime(2026, 8, day, hour, minute, tzinfo=main.APP_TIMEZONE)


def prepare(tmp_path, last_active: str = "2026-08-18", streak: int = 4):
    main.DB_PATH = tmp_path / "streak.db"
    main.init_db()
    with main.db() as con:
        con.execute(
            "UPDATE users SET streak_count=?,last_active_date=? WHERE id=1",
            (streak, last_active),
        )
        return (
            con.execute("SELECT xp FROM users WHERE id=1").fetchone()[0],
            float(con.execute("SELECT pending_activity_boost FROM wallets WHERE user_id=1").fetchone()[0]),
        )


def test_same_day_claim_is_idempotent_and_persists_rewards(tmp_path):
    initial_xp, initial_boost = prepare(tmp_path)

    with main.db() as con:
        first = main.claim_streak_reward(con, at=at(19))
    with main.db() as con:
        second = main.claim_streak_reward(con, at=at(19, 22, 30))

    assert first["streak_count"] == 5
    assert first["awarded"] == {"xp": 25, "boost": 20}
    assert second["already_claimed"] is True
    assert second["awarded"] == {"xp": 0, "boost": 0}
    assert second["total_rewards"] == {"xp": 25, "boost": 20, "days": 1}
    assert second["history"][0]["claimed_at"] == "2026-08-19T07:15:00+00:00"

    with main.db() as con:
        assert con.execute("SELECT COUNT(*) FROM streak_checkins").fetchone()[0] == 1
        assert con.execute("SELECT xp FROM users WHERE id=1").fetchone()[0] == initial_xp + 25
        assert float(con.execute("SELECT pending_activity_boost FROM wallets WHERE user_id=1").fetchone()[0]) == initial_boost + 20


def test_next_day_continues_streak_and_missed_day_resets_it(tmp_path):
    prepare(tmp_path)

    with main.db() as con:
        day_one = main.claim_streak_reward(con, at=at(19))
    with main.db() as con:
        day_two = main.claim_streak_reward(con, at=at(20))
    with main.db() as con:
        after_gap = main.claim_streak_reward(con, at=at(22))

    assert day_one["streak_count"] == 5
    assert day_two["streak_count"] == 6
    assert after_gap["streak_count"] == 1
    assert after_gap["total_rewards"]["days"] == 3
    assert after_gap["next_claim_at"] == "2026-08-23T00:00:00+03:00"
    assert after_gap["seconds_until_next_claim"] == 13 * 60 * 60 + 45 * 60


def test_reading_streak_does_not_change_database(tmp_path):
    prepare(tmp_path, last_active="2026-08-15", streak=12)

    with main.db() as con:
        state = main.get_streak_state(con, at=at(19))
        stored = con.execute("SELECT streak_count,last_active_date FROM users WHERE id=1").fetchone()

    assert state["streak_count"] == 0
    assert state["can_claim"] is True
    assert stored["streak_count"] == 12
    assert stored["last_active_date"] == "2026-08-15"
