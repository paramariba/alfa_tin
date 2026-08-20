from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import re
import secrets
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import bcrypt
import jwt
from badwords import ProfanityFilter
from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .economy import conversion_preview, d, display_token_price, game_position_value, money, piggy_daily_yield, sell_result, weighted_average
from .ai_coach import GeminiCoach
from .news import PortfolioNewsService

ROOT = Path(__file__).resolve().parents[2]
_db_setting = Path(os.getenv("DATABASE_PATH", "./app-data/alfa_tin.db"))
DB_PATH = _db_setting if _db_setting.is_absolute() else (ROOT / _db_setting).resolve()
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
APP_SECRET = os.getenv("APP_SECRET", "alfa-tin-dev-secret")
AUTH_REQUIRED = os.getenv("AUTH_REQUIRED", "true").lower() == "true"
ACCESS_TOKEN_DAYS = max(1, int(os.getenv("ACCESS_TOKEN_DAYS", "30")))
DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() == "true"
MULTIPLIER = d(os.getenv("GAME_RETURN_MULTIPLIER", "10"))
MARKET_DATA_PROVIDER = os.getenv("MARKET_DATA_PROVIDER", "finam").strip().lower()
MARKET_REFRESH_SECONDS = max(10.0, float(os.getenv("MARKET_REFRESH_SECONDS", "15")))
NEWS_CACHE_MINUTES = max(5, int(os.getenv("NEWS_CACHE_MINUTES", "30")))
APP_TIMEZONE = ZoneInfo(os.getenv("APP_TIMEZONE", "Europe/Moscow"))
CORS_ALLOWED_ORIGINS = [
    origin.strip().rstrip("/")
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip() and origin.strip() != "*"
]
LOGGER = logging.getLogger("alfa_tin.market_data")
MARKET_DATA_STATE: dict[str, Any] = {
    "configured": bool(os.getenv("FINAM_API_SECRET")) and MARKET_DATA_PROVIDER == "finam",
    "last_attempt_at": None,
    "last_success_at": None,
    "last_error": None,
    "updated_instruments": 0,
}
CURRENT_USER_ID: ContextVar[int | None] = ContextVar("alfa_tin_current_user_id", default=None)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def normalize_login_name(name: str) -> tuple[str, str]:
    display_name = " ".join(name.strip().split())
    if not 2 <= len(display_name) <= 40:
        raise HTTPException(422, "Имя должно содержать от 2 до 40 символов")
    if not re.fullmatch(r"[A-Za-zА-Яа-яЁё0-9._ -]+", display_name):
        raise HTTPException(422, "В имени можно использовать буквы, цифры, пробел, точку, дефис и подчёркивание")
    return display_name, display_name.casefold()


PROFANITY_FILTER = ProfanityFilter()
PROFANITY_FILTER.init(languages=["ru"])
PROFANITY_FILTER.add_words(["пездос"])
PROFANITY_SAFE_WORDS = {"страхуй", "застрахуй", "подстрахуй"}
SPACED_CYRILLIC_WORD = re.compile(
    r"(?<![A-Za-zА-Яа-яЁё])(?:[А-Яа-яЁё][\s\d_.*-]+){2,}[А-Яа-яЁё](?![A-Za-zА-Яа-яЁё])"
)
DIGIT_OBFUSCATED_WORD = re.compile(r"(?<![А-Яа-яЁё\d])[А-Яа-яЁё\d]+(?![А-Яа-яЁё\d])")
MENTION_PATTERN = re.compile(r"(?<![A-Za-z0-9_])@([A-Za-z0-9]{1,12})", re.IGNORECASE)


def contains_profanity(text: str) -> bool:
    candidates = re.findall(r"[A-Za-zА-Яа-яЁё]+", text.casefold())
    candidates.extend(
        re.sub(r"[^А-Яа-яЁё]", "", match.group()).casefold()
        for match in SPACED_CYRILLIC_WORD.finditer(text)
    )
    candidates.extend(
        re.sub(r"\d", "", match.group()).casefold()
        for match in DIGIT_OBFUSCATED_WORD.finditer(text)
        if any(char.isdigit() for char in match.group())
        and sum(char.lower() in "абвгдеёжзийклмнопрстуфхцчшщъыьэюя" for char in match.group()) >= 3
    )
    return any(
        candidate not in PROFANITY_SAFE_WORDS
        and bool(PROFANITY_FILTER.filter_text(candidate, match_threshold=1.0))
        for candidate in candidates
    )


def validate_public_name(name: str) -> tuple[str, str]:
    """Normalize a public name and reject the same obfuscations as social posts."""
    display_name, username = normalize_login_name(name)
    if contains_profanity(display_name):
        raise HTTPException(422, "Имя содержит недопустимые слова — выбери другое")
    return display_name, username


def extract_mentioned_tickers(text: str) -> list[str]:
    result: list[str] = []
    for match in MENTION_PATTERN.finditer(text):
        ticker = match.group(1).upper()
        if ticker not in result:
            result.append(ticker)
    return result


def validate_password(password: str) -> None:
    if len(password) < 6:
        raise HTTPException(422, "Пароль должен содержать минимум 6 символов")
    if len(password.encode("utf-8")) > 72:
        raise HTTPException(422, "Пароль слишком длинный")


def create_access_token(user_id: int) -> str:
    return jwt.encode(
        {"sub": str(user_id), "exp": datetime.now(timezone.utc) + timedelta(days=ACCESS_TOKEN_DAYS)},
        APP_SECRET,
        algorithm="HS256",
    )


def decode_access_token(token: str) -> int:
    try:
        payload = jwt.decode(token, APP_SECRET, algorithms=["HS256"])
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(401, "Сессия недействительна или истекла") from exc
    return user_id


def current_user_id() -> int:
    user_id = CURRENT_USER_ID.get()
    if user_id is None:
        if not AUTH_REQUIRED:
            return 1
        raise HTTPException(401, "Требуется вход")
    return user_id


def require_admin() -> int:
    user_id = current_user_id()
    with db() as con:
        role = con.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
    if not role or role[0] != "admin":
        raise HTTPException(403, "Недостаточно прав")
    return user_id


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def streak_now() -> datetime:
    """Current app time. Kept separate so streak transitions are deterministic in tests."""
    return datetime.now(APP_TIMEZONE)


def local_date(at: datetime | None = None) -> date:
    current = at or streak_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=APP_TIMEZONE)
    return current.astimezone(APP_TIMEZONE).date()


def age_from_birth_date(birth_date: str | date, at: date | None = None) -> int:
    born = birth_date if isinstance(birth_date, date) else date.fromisoformat(str(birth_date))
    today = at or local_date()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def enrich_user_age(user: dict[str, Any] | None) -> dict[str, Any] | None:
    if not user:
        return user
    try:
        age = age_from_birth_date(user.get("birth_date") or "2009-01-01")
    except ValueError:
        age = 0
    user["age"] = age
    user["is_adult"] = age >= 18
    user["social_title"] = "Ток" if age >= 18 else "Тин-Ток"
    if user.get("referral_code"):
        user["public_id"] = user["referral_code"]
    return user


@contextmanager
def db():
    con = sqlite3.connect(DB_PATH, timeout=5)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=5000")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def rowdict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE, username TEXT UNIQUE, password_hash TEXT, display_name TEXT, birth_date TEXT, onboarding_completed INTEGER DEFAULT 0, referral_code TEXT UNIQUE, role TEXT DEFAULT 'user', xp INTEGER DEFAULT 620, level INTEGER DEFAULT 2, streak_count INTEGER DEFAULT 12, last_active_date TEXT, created_at TEXT, is_banned INTEGER DEFAULT 0, ban_reason TEXT, banned_at TEXT);
CREATE TABLE IF NOT EXISTS wallets(user_id INTEGER PRIMARY KEY REFERENCES users(id), token_cash TEXT NOT NULL, alfa_coins TEXT NOT NULL, eligible_profit_tokens TEXT NOT NULL, pending_activity_boost TEXT NOT NULL, updated_at TEXT);
CREATE TABLE IF NOT EXISTS instruments(id INTEGER PRIMARY KEY, ticker TEXT UNIQUE, symbol TEXT, type TEXT, name TEXT, sector TEXT, risk_level TEXT, description TEXT, real_price_rub TEXT, previous_close TEXT, change_pct TEXT, featured INTEGER, enabled INTEGER, source TEXT, source_timestamp TEXT);
CREATE TABLE IF NOT EXISTS positions(id INTEGER PRIMARY KEY, user_id INTEGER, instrument_id INTEGER, quantity TEXT, average_buy_token_price TEXT, raw_cost_basis TEXT, updated_at TEXT, UNIQUE(user_id,instrument_id));
CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY, user_id INTEGER, instrument_id INTEGER, side TEXT, quantity TEXT, raw_quote_tkn TEXT, raw_pnl TEXT, game_pnl TEXT, cash_change_tkn TEXT, status TEXT, idempotency_key TEXT UNIQUE, executed_at TEXT);
CREATE TABLE IF NOT EXISTS ledger_entries(id INTEGER PRIMARY KEY, user_id INTEGER, currency TEXT, event_type TEXT, amount TEXT, balance_after TEXT, reference_type TEXT, reference_id TEXT, metadata_json TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS net_worth_snapshots(id INTEGER PRIMARY KEY, user_id INTEGER, token_net_worth TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS piggy_accounts(user_id INTEGER PRIMARY KEY, balance_tkn TEXT, current_apr TEXT, last_accrual_at TEXT, yield_remainder_tkn TEXT NOT NULL DEFAULT '0');
CREATE TABLE IF NOT EXISTS conversions(id INTEGER PRIMARY KEY, user_id INTEGER, tokens_burned TEXT, conversion_rate TEXT, base_ac TEXT, activity_bonus_ac TEXT, total_ac TEXT, rolling_net_worth TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS shop_items(id INTEGER PRIMARY KEY, slug TEXT UNIQUE, name TEXT, description TEXT, type TEXT, price_ac INTEGER, image_emoji TEXT, active INTEGER, stock_quantity INTEGER, sort_order INTEGER);
CREATE TABLE IF NOT EXISTS shop_orders(id INTEGER PRIMARY KEY, user_id INTEGER, shop_item_id INTEGER, quantity INTEGER, total_ac INTEGER, status TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS user_goals(user_id INTEGER PRIMARY KEY, shop_item_id INTEGER, created_at TEXT);
CREATE TABLE IF NOT EXISTS lessons(id INTEGER PRIMARY KEY, course TEXT, title TEXT, description TEXT, xp_reward INTEGER, boost_reward INTEGER, order_index INTEGER);
CREATE TABLE IF NOT EXISTS lesson_progress(user_id INTEGER, lesson_id INTEGER, completed_at TEXT, PRIMARY KEY(user_id,lesson_id));
CREATE TABLE IF NOT EXISTS quests(id INTEGER PRIMARY KEY, type TEXT, title TEXT, target INTEGER, xp_reward INTEGER, boost_reward INTEGER);
CREATE TABLE IF NOT EXISTS user_quests(user_id INTEGER, quest_id INTEGER, progress INTEGER, completed INTEGER, claimed INTEGER, period_key TEXT, PRIMARY KEY(user_id,quest_id,period_key));
CREATE TABLE IF NOT EXISTS tamagotchi(user_id INTEGER PRIMARY KEY, name TEXT, mood INTEGER, energy INTEGER, knowledge INTEGER, friendship INTEGER, equipped_items_json TEXT, last_interaction_at TEXT);
CREATE TABLE IF NOT EXISTS tamagotchi_interactions(user_id INTEGER NOT NULL REFERENCES users(id), action TEXT NOT NULL, last_interaction_at TEXT NOT NULL, PRIMARY KEY(user_id,action));
CREATE TABLE IF NOT EXISTS tamagotchi_items(id INTEGER PRIMARY KEY, slot TEXT, name TEXT, price_ac INTEGER, emoji TEXT, rarity TEXT, active INTEGER);
CREATE TABLE IF NOT EXISTS user_tamagotchi_items(user_id INTEGER, item_id INTEGER, acquired_at TEXT, PRIMARY KEY(user_id,item_id));
CREATE TABLE IF NOT EXISTS contest_profiles(user_id INTEGER PRIMARY KEY, verification_status TEXT, full_name TEXT, ege_year INTEGER, ege_subject TEXT, ege_score INTEGER, certificate_mock TEXT, verified_at TEXT);
CREATE TABLE IF NOT EXISTS contest_wallets(user_id INTEGER PRIMARY KEY, contest_tokens TEXT);
CREATE TABLE IF NOT EXISTS watchlist(user_id INTEGER, instrument_id INTEGER, PRIMARY KEY(user_id,instrument_id));
CREATE TABLE IF NOT EXISTS idempotency(user_id INTEGER, key TEXT, response_json TEXT, created_at TEXT, PRIMARY KEY(user_id,key));
CREATE TABLE IF NOT EXISTS app_config(key TEXT PRIMARY KEY, value_json TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS user_achievements(user_id INTEGER, achievement_id INTEGER, claimed_at TEXT, PRIMARY KEY(user_id,achievement_id));
CREATE TABLE IF NOT EXISTS news_insight_cache(user_id INTEGER, instrument_id INTEGER, payload_json TEXT NOT NULL, generated_at TEXT NOT NULL, PRIMARY KEY(user_id,instrument_id));
CREATE TABLE IF NOT EXISTS streak_checkins(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), checkin_date TEXT NOT NULL, streak_day INTEGER NOT NULL, xp_reward INTEGER NOT NULL, boost_reward INTEGER NOT NULL, claimed_at TEXT NOT NULL, UNIQUE(user_id,checkin_date));
CREATE TABLE IF NOT EXISTS monthly_ai_reports(user_id INTEGER NOT NULL REFERENCES users(id), month TEXT NOT NULL, input_hash TEXT NOT NULL, payload_json TEXT NOT NULL, generated_at TEXT NOT NULL, PRIMARY KEY(user_id,month));
CREATE TABLE IF NOT EXISTS gamification_state(user_id INTEGER PRIMARY KEY REFERENCES users(id), reset_at TEXT);
CREATE TABLE IF NOT EXISTS user_friends(user_id INTEGER NOT NULL REFERENCES users(id), friend_user_id INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL, PRIMARY KEY(user_id,friend_user_id), CHECK(user_id<>friend_user_id));
CREATE TABLE IF NOT EXISTS social_posts(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), trade_id INTEGER REFERENCES trades(id), comment TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(user_id,trade_id));
"""

INSTRUMENTS = [
    ("SBER", "Сбербанк", "Финансы", "Средний", "Крупнейший банк России", "320.40", "316.50", 1),
    ("YDEX", "Яндекс", "Технологии", "Высокий", "Технологическая экосистема", "4210.00", "4161.00", 1),
    ("LKOH", "Лукойл", "Нефть и газ", "Средний", "Нефтегазовая компания", "7042.50", "6978.00", 1),
    ("GAZP", "Газпром", "Нефть и газ", "Высокий", "Энергетическая компания", "131.84", "133.10", 1),
    ("T", "Т-Технологии", "Финансы", "Высокий", "Финансовая онлайн-экосистема", "3440.00", "3385.00", 1),
    ("NVTK", "Новатэк", "Нефть и газ", "Средний", "Производитель природного газа", "1118.80", "1102.00", 0),
    ("ROSN", "Роснефть", "Нефть и газ", "Средний", "Нефтяная компания", "468.25", "464.10", 0),
    ("GMKN", "Норникель", "Металлы", "Высокий", "Горно-металлургическая компания", "119.42", "117.30", 0),
    ("PLZL", "Полюс", "Металлы", "Высокий", "Крупнейший производитель золота", "2180.40", "2142.00", 0),
    ("MGNT", "Магнит", "Ритейл", "Средний", "Сеть магазинов у дома", "3488.00", "3522.00", 0),
    ("X5", "X5", "Ритейл", "Средний", "Продуктовый ритейл", "2845.50", "2810.00", 0),
    ("OZON", "Ozon", "Технологии", "Высокий", "E-commerce платформа", "4320.00", "4205.00", 0),
    ("AFLT", "Аэрофлот", "Транспорт", "Высокий", "Авиакомпания", "61.20", "60.70", 0),
    ("PHOR", "ФосАгро", "Химия", "Средний", "Производитель удобрений", "6618.00", "6550.00", 0),
    ("CHMF", "Северсталь", "Металлы", "Средний", "Стальная и горнодобывающая компания", "1126.60", "1138.00", 0),
    ("TMOS", "Тинькофф Индекс МосБиржи", "Широкий рынок", "Средний", "Фонд на индекс Московской биржи", "7.42", "7.35", 1, "fund"),
    ("SBMX", "Первая — Фонд Топ российских акций", "Широкий рынок", "Средний", "Диверсифицированный фонд российских акций", "17.83", "17.70", 1, "fund"),
    ("LQDT", "Ликвидность", "Денежный рынок", "Низкий", "Фонд денежного рынка", "1.78", "1.77", 1, "fund"),
    ("GOLD", "Золото", "Драгметаллы", "Средний", "Фонд с привязкой к золоту", "2.48", "2.45", 0, "fund"),
]

SHOP = [
    ("sticker", "Sticker Pack Alfa", "Стикеры для ноутбука и телефона", "physical", 2700, "✨", 30),
    ("mug", "Кружка Alfa", "Матовая кружка для больших планов", "physical", 5000, "☕", 15),
    ("tshirt", "Футболка Alfa", "Свободный крой и фирменный акцент", "physical", 7300, "👕", 10),
    ("hoodie", "Худи Alfa", "Главная награда: тёплое худи limited edition", "physical", 9600, "🧥", 8),
]

LESSONS = [
    ("Основы", "Инвестиции без сложных слов", "Чем инвестиции отличаются от накоплений и зачем нужен план", 80, 45),
    ("Основы", "Доходность и время", "Как горизонт, сложный процент и инфляция меняют результат", 90, 50),
    ("Акции", "Ты — совладелец", "Что покупатель акции получает на самом деле", 100, 55),
    ("Акции", "Почему цена двигается", "Как спрос, отчёты, новости и ожидания влияют на котировку", 100, 60),
    ("Риск", "Волатильность — это нормально", "Как отличить обычное движение цены от проблемы в бизнесе", 110, 65),
    ("Риск", "Не клади всё в одно", "Как диверсификация уменьшает ущерб от одной ошибки", 120, 70),
    ("Фонды", "Рынок в одной покупке", "Как фонд собирает много активов в один инструмент", 120, 75),
    ("Накопления", "Сила регулярности", "Почему небольшие регулярные пополнения сильнее попыток угадать момент", 100, 60),
    ("Психология", "Не гонись за толпой", "Как замечать FOMO и принимать решения по своему плану", 140, 80),
    ("Основы", "Финансовая подушка сначала", "Почему запас денег важнее первой покупки на бирже", 90, 50),
    ("Акции", "Как читать компанию", "Выручка, прибыль, долг и денежный поток без сложной бухгалтерии", 130, 75),
    ("Акции", "Дивиденды: не бесплатные деньги", "Откуда берутся выплаты и почему цена после отсечки меняется", 120, 70),
    ("Риск", "Риск и доходность идут рядом", "Почему обещание высокой прибыли без риска должно насторожить", 120, 70),
    ("Фонды", "Что внутри фонда", "Комиссии, состав, индекс и ошибки при выборе фонда", 130, 75),
    ("Практика", "Как собрать первый портфель", "Связываем цель, срок и допустимый риск в один план", 150, 85),
    ("Практика", "Покупка по плану", "Как заранее определить сумму, условия покупки и выхода", 140, 80),
    ("Новости", "Факт, ожидание или шум", "Как читать новости об акциях и не путать событие с прогнозом", 140, 80),
    ("Психология", "Что делать, когда рынок падает", "Пошаговый алгоритм вместо панической продажи", 160, 90),
]

QUESTS = [
    ("daily", "Изучи одну компанию", 1, 45, 40),
    ("daily", "Пройди короткий урок", 1, 60, 55),
    ("daily", "Проверь портфель", 1, 35, 30),
    ("weekly", "Три учебных шага", 3, 180, 160),
    ("weekly", "Собери 3 отрасли", 3, 220, 200),
]

TAMAGOTCHI_ITEMS = [
    ("head", "Красная панама", 120, "🧢", "common"), ("eyes", "Умные очки", 180, "🤓", "common"),
    ("outfit", "Худи аналитика", 380, "🧥", "rare"), ("room", "Комната трейдера", 520, "📈", "rare"),
    ("mood", "Реакция «ракета»", 90, "🚀", "common"), ("head", "Корона стратегии", 600, "👑", "epic"),
]

TIN_INTERACTIONS = {
    "pet": {"cooldown": 30, "mood": 3, "energy": 0, "friendship": 2, "message": "Мр-р! Кажется, портфель тоже любит спокойствие."},
    "talk": {"cooldown": 45, "mood": 2, "energy": 0, "friendship": 3, "message": "Сегодня сравним акцию и фонд?"},
    "task": {"cooldown": 60, "mood": 4, "energy": -4, "friendship": 5, "message": "Задание дня: найди в портфеле три разные отрасли."},
}


def init_db() -> None:
    with db() as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript(SCHEMA)
        user_columns = {row["name"] for row in con.execute("PRAGMA table_info(users)").fetchall()}
        if "is_banned" not in user_columns:
            con.execute("ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0")
        if "ban_reason" not in user_columns:
            con.execute("ALTER TABLE users ADD COLUMN ban_reason TEXT")
        if "banned_at" not in user_columns:
            con.execute("ALTER TABLE users ADD COLUMN banned_at TEXT")
        piggy_columns = {row["name"] for row in con.execute("PRAGMA table_info(piggy_accounts)").fetchall()}
        if "yield_remainder_tkn" not in piggy_columns:
            con.execute("ALTER TABLE piggy_accounts ADD COLUMN yield_remainder_tkn TEXT NOT NULL DEFAULT '0'")
        # Profanity used to trigger a permanent account ban. The moderation
        # policy now only rejects the individual post, so undo those bans.
        con.execute(
            "UPDATE users SET is_banned=0,ban_reason=NULL,banned_at=NULL WHERE ban_reason='profanity_in_social_post'"
        )
        post_columns = {row["name"]: row for row in con.execute("PRAGMA table_info(social_posts)").fetchall()}
        if post_columns.get("trade_id") and post_columns["trade_id"]["notnull"]:
            con.executescript(
                "ALTER TABLE social_posts RENAME TO social_posts_legacy;"
                "CREATE TABLE social_posts(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), trade_id INTEGER REFERENCES trades(id), comment TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(user_id,trade_id));"
                "INSERT INTO social_posts(id,user_id,trade_id,comment,created_at) SELECT id,user_id,trade_id,comment,created_at FROM social_posts_legacy;"
                "DROP TABLE social_posts_legacy;"
            )
        if not con.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            con.execute("INSERT INTO users(id,email,username,password_hash,display_name,birth_date,onboarding_completed,referral_code,role,xp,level,streak_count,last_active_date,created_at) VALUES(1,?,?,?,?,?,?,?,?,?,?,12,?,?)", ("demo@alfa.tin", "sasha", hash_password("demo1234"), "Саша", "2009-05-14", 1, "TIN-SASHA", "admin", 820, 2, local_date().isoformat(), now()))
            con.execute("INSERT INTO wallets VALUES(1,'784.25','0','120','1540',?)", (now(),))
            con.execute("INSERT INTO piggy_accounts(user_id,balance_tkn,current_apr,last_accrual_at,yield_remainder_tkn) VALUES(1,'180','0.124',?,'0')", (now(),))
            con.execute("INSERT INTO tamagotchi VALUES(1,'Тин',86,72,64,48,'[]',?)", (now(),))
            con.execute("INSERT INTO contest_wallets VALUES(1,'0')")
            con.execute("INSERT INTO ledger_entries(user_id,currency,event_type,amount,balance_after,created_at) VALUES(1,'TKN','START_GRANT','1000','1000',?)", (now(),))
        else:
            demo_user = con.execute("SELECT password_hash FROM users WHERE id=1").fetchone()
            if demo_user and demo_user["password_hash"] and demo_user["password_hash"].startswith("$argon2"):
                con.execute("UPDATE users SET password_hash=? WHERE id=1", (hash_password("demo1234"),))
        for index, item in enumerate(INSTRUMENTS, 1):
            ticker, name, sector, risk, description, price, prev, featured, *kind = item
            instrument_type = kind[0] if kind else "stock"
            change = money((d(price) - d(prev)) / d(prev) * 100)
            con.execute("INSERT OR IGNORE INTO instruments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (index, ticker, f"{ticker}@MISX", instrument_type, name, sector, risk, description, price, prev, str(change), featured, 1, "demo", now()))
        social_users = [
            (2, "lera", "Лера", "2007-11-03", 2350, "5600", "640", "1,2"),
            (3, "max", "Макс", "2009-02-18", 1720, "4300", "410", "2,5"),
            (4, "alina", "Алина", "2006-06-27", 3180, "7200", "900", "1,16"),
            (5, "dima", "Дима", "2010-01-12", 1140, "3500", "280", "3,7"),
            (6, "sonya", "Соня", "2008-09-20", 2740, "6100", "720", "4,16"),
        ]
        for user_id, username, display_name, birth_date, xp, cash, piggy_balance, instrument_ids in social_users:
            con.execute(
                "INSERT OR IGNORE INTO users(id,email,username,password_hash,display_name,birth_date,onboarding_completed,referral_code,role,xp,level,streak_count,last_active_date,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (user_id, f"{username}@community.alfa.tin", username, "social-profile-disabled", display_name, birth_date, 1, f"TIN-{username.upper()}", "user", xp, calc_level(xp), 3 + user_id, local_date().isoformat(), now()),
            )
            con.execute("INSERT OR IGNORE INTO wallets VALUES(?,?,?,?,?,?)", (user_id, cash, "0", "0", "0", now()))
            con.execute("INSERT OR IGNORE INTO piggy_accounts(user_id,balance_tkn,current_apr,last_accrual_at,yield_remainder_tkn) VALUES(?,?,?,?,'0')", (user_id, piggy_balance, "0.11", now()))
            con.execute("INSERT OR IGNORE INTO tamagotchi VALUES(?,'Тин',80,75,65,55,'[]',?)", (user_id, now()))
            con.execute("INSERT OR IGNORE INTO contest_wallets VALUES(?,'0')", (user_id,))
            for offset, instrument_id in enumerate((int(value) for value in instrument_ids.split(",")), 1):
                quote = display_token_price(d(INSTRUMENTS[instrument_id - 1][5]))
                quantity = d(40 + user_id * 8 + offset * 5)
                con.execute(
                    "INSERT OR IGNORE INTO positions(user_id,instrument_id,quantity,average_buy_token_price,raw_cost_basis,updated_at) VALUES(?,?,?,?,?,?)",
                    (user_id, instrument_id, str(quantity), str(money(quote * d("0.97"))), str(money(quantity * quote * d("0.97"))), now()),
                )
                con.execute(
                    "INSERT OR IGNORE INTO trades(user_id,instrument_id,side,quantity,raw_quote_tkn,raw_pnl,game_pnl,cash_change_tkn,status,idempotency_key,executed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (user_id, instrument_id, "buy" if offset == 1 else "sell", str(d(2 + offset)), str(quote), "0" if offset == 1 else str(money(d(user_id) / d(10))), "0" if offset == 1 else str(money(d(user_id))), str(money(-(d(2 + offset) * quote))) if offset == 1 else str(money(d(2 + offset) * quote + d(user_id))), "executed", f"social-seed-{user_id}-{offset}", (datetime.now(timezone.utc) - timedelta(days=user_id + offset)).isoformat()),
                )
        con.execute("INSERT OR IGNORE INTO user_friends VALUES(1,3,?)", (now(),))
        seed_comments = {
            2: "Начала с понятной компании и небольшой суммы.",
            3: "Закрыл сделку в плюс — сработал заранее выбранный план.",
            4: "Добавила актив из другой отрасли, чтобы не держать всё в одном месте.",
            5: "Первая покупка в симуляторе. Смотрю, как поведёт себя позиция.",
            6: "Не гналась за движением цены и дождалась своей точки входа.",
        }
        for social_user_id, comment in seed_comments.items():
            seed_trade = con.execute(
                "SELECT id FROM trades WHERE user_id=? ORDER BY CASE WHEN side='sell' AND CAST(game_pnl AS REAL)>0 THEN 0 ELSE 1 END,id DESC LIMIT 1",
                (social_user_id,),
            ).fetchone()
            if seed_trade:
                con.execute(
                    "INSERT OR IGNORE INTO social_posts(user_id,trade_id,comment,created_at) VALUES(?,?,?,?)",
                    (social_user_id, seed_trade["id"], comment, now()),
                )
        for index, item in enumerate(SHOP, 1):
            con.execute(
                "INSERT INTO shop_items VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "slug=excluded.slug,name=excluded.name,description=excluded.description,type=excluded.type,"
                "price_ac=excluded.price_ac,image_emoji=excluded.image_emoji,active=excluded.active,sort_order=excluded.sort_order",
                (index, *item[:6], 1, item[6], index),
            )
        if not con.execute("SELECT 1 FROM user_goals WHERE user_id=1").fetchone():
            con.execute("INSERT INTO user_goals VALUES(1,4,?)", (now(),))
        for index, item in enumerate(LESSONS, 1):
            con.execute(
                "INSERT INTO lessons VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "course=excluded.course,title=excluded.title,description=excluded.description,"
                "xp_reward=excluded.xp_reward,boost_reward=excluded.boost_reward,order_index=excluded.order_index",
                (index, *item, index),
            )
        for index, item in enumerate(QUESTS, 1):
            con.execute("INSERT OR IGNORE INTO quests VALUES(?,?,?,?,?,?)", (index, *item))
        ensure_current_quests(con, 1)
        for index, item in enumerate(TAMAGOTCHI_ITEMS, 1):
            con.execute("INSERT OR IGNORE INTO tamagotchi_items VALUES(?,?,?,?,?,?,1)", (index, *item))
        if not con.execute("SELECT 1 FROM positions WHERE user_id=1").fetchone():
            con.execute("INSERT INTO positions(user_id,instrument_id,quantity,average_buy_token_price,raw_cost_basis,updated_at) VALUES(1,1,'30','3.00','90',?)", (now(),))
            con.execute("INSERT INTO positions(user_id,instrument_id,quantity,average_buy_token_price,raw_cost_basis,updated_at) VALUES(1,16,'800','0.069','55.2',?)", (now(),))
            con.execute("INSERT INTO net_worth_snapshots(user_id,token_net_worth,created_at) VALUES(1,'1184.25',?)", (now(),))
        defaults = {
            "game_return_multiplier": 10, "conversion_base_rate": 50, "conversion_min_rate": 5,
            "conversion_reference_net_worth": 1000, "conversion_rate_softening": 8000,
            "trading_ac_cap_30d": 2400, "activity_boost_cap_30d": 600, "total_ac_cap_30d": 3000,
            "piggy_min_apr": 0.07, "piggy_max_apr": 0.16,
            "referral_referrer_tkn": 100, "referral_friend_tkn": 50, "contest_min_ege_score": 70,
        }
        for key, value in defaults.items():
            con.execute("INSERT OR IGNORE INTO app_config VALUES(?,?,?)", (key, json.dumps(value), now()))
        # The piggy account can now hold the user's entire free TKN balance.
        con.execute("DELETE FROM app_config WHERE key='piggy_max_share'")
        # Migrate previous built-in conversion floors. Preserve explicitly
        # customized values that do not match a shipped default.
        old_floor = con.execute("SELECT value_json FROM app_config WHERE key='conversion_min_rate'").fetchone()
        if old_floor and json.loads(old_floor[0]) in {20, 35}:
            con.execute("UPDATE app_config SET value_json='5',updated_at=? WHERE key='conversion_min_rate'", (now(),))
        pacing_migrations = {"trading_ac_cap_30d": (12000, 2400), "activity_boost_cap_30d": (3000, 600), "total_ac_cap_30d": (15000, 3000)}
        for key, (old_value, new_value) in pacing_migrations.items():
            row = con.execute("SELECT value_json FROM app_config WHERE key=?", (key,)).fetchone()
            if row and json.loads(row[0]) == old_value:
                con.execute("UPDATE app_config SET value_json=?,updated_at=? WHERE key=?", (json.dumps(new_value), now(), key))


def accrue_piggy_yield(con: sqlite3.Connection, user_id: int, at: datetime | None = None, settle: bool = False) -> Decimal:
    """Accrue piggy yield precisely and credit whole cents to eligible cash."""
    current = at or datetime.now(timezone.utc)
    account = con.execute(
        "SELECT balance_tkn,current_apr,last_accrual_at,yield_remainder_tkn FROM piggy_accounts WHERE user_id=?",
        (user_id,),
    ).fetchone()
    if not account:
        return d(0)
    try:
        last = datetime.fromisoformat(account["last_accrual_at"])
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        else:
            last = last.astimezone(timezone.utc)
    except (TypeError, ValueError):
        con.execute(
            "UPDATE piggy_accounts SET last_accrual_at=?,yield_remainder_tkn='0' WHERE user_id=?",
            (current.isoformat(), user_id),
        )
        return d(0)
    elapsed_seconds = max(0, (current - last).total_seconds())
    if elapsed_seconds <= 0:
        return d(0)
    raw_yield = (
        d(account["balance_tkn"])
        * d(account["current_apr"])
        * d(str(elapsed_seconds))
        / d(365 * 86400)
        + d(account["yield_remainder_tkn"] or 0)
    )
    earned = raw_yield.quantize(d("0.01"), rounding=ROUND_DOWN)
    remainder = raw_yield - earned
    # Ordinary reads do not write for sub-cent changes. Balance-changing
    # operations settle the remainder so a new deposit cannot earn interest
    # for time that elapsed before it existed.
    if earned <= 0 and not settle:
        return d(0)
    # Conditional update makes simultaneous requests unable to credit the same
    # elapsed period twice.
    claimed = con.execute(
        "UPDATE piggy_accounts SET last_accrual_at=?,yield_remainder_tkn=? WHERE user_id=? AND last_accrual_at=?",
        (current.isoformat(), str(remainder), user_id, account["last_accrual_at"]),
    ).rowcount
    if claimed != 1:
        return d(0)
    if earned <= 0:
        return d(0)
    wallet_row = con.execute(
        "SELECT token_cash,eligible_profit_tokens FROM wallets WHERE user_id=?",
        (user_id,),
    ).fetchone()
    if not wallet_row:
        return d(0)
    cash = money(d(wallet_row["token_cash"]) + earned)
    eligible = money(d(wallet_row["eligible_profit_tokens"]) + earned)
    con.execute(
        "UPDATE wallets SET token_cash=?,eligible_profit_tokens=?,updated_at=? WHERE user_id=?",
        (str(cash), str(eligible), now(), user_id),
    )
    ledger(
        con, "PIGGY_YIELD", earned, cash, ref_type="piggy", ref_id=str(user_id),
        metadata={"seconds": elapsed_seconds, "apr": str(account["current_apr"]), "convertible_to_ac": True},
        user_id=user_id,
    )
    return earned


def wallet(con: sqlite3.Connection, user_id: int | None = None, settle_piggy: bool = False) -> sqlite3.Row:
    user_id = current_user_id() if user_id is None else user_id
    accrue_piggy_yield(con, user_id, settle=settle_piggy)
    result = con.execute("SELECT * FROM wallets WHERE user_id=?", (user_id,)).fetchone()
    if not result:
        raise HTTPException(404, "Кошелёк не найден")
    return result


def position_value(con: sqlite3.Connection, user_id: int | None = None) -> Decimal:
    user_id = current_user_id() if user_id is None else user_id
    total = d(0)
    rows = con.execute("SELECT p.*,i.real_price_rub FROM positions p JOIN instruments i ON i.id=p.instrument_id WHERE p.user_id=?", (user_id,)).fetchall()
    for row in rows:
        total += game_position_value(d(row["quantity"]), d(row["average_buy_token_price"]), display_token_price(d(row["real_price_rub"])), MULTIPLIER)
    return money(total)


def net_worth(con: sqlite3.Connection, user_id: int | None = None) -> Decimal:
    user_id = current_user_id() if user_id is None else user_id
    w = wallet(con, user_id)
    piggy = con.execute("SELECT balance_tkn FROM piggy_accounts WHERE user_id=?", (user_id,)).fetchone()
    return money(d(w["token_cash"]) + position_value(con, user_id) + d(piggy[0] if piggy else 0))


def ledger(con: sqlite3.Connection, event: str, amount: Decimal, balance: Decimal, currency: str = "TKN", ref_type: str = "", ref_id: str = "", metadata: dict | None = None, user_id: int | None = None) -> None:
    user_id = current_user_id() if user_id is None else user_id
    con.execute("INSERT INTO ledger_entries(user_id,currency,event_type,amount,balance_after,reference_type,reference_id,metadata_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (user_id, currency, event, str(money(amount)), str(money(balance)), ref_type, ref_id, json.dumps(metadata or {}, ensure_ascii=False), now()))


def month_bounds(month: str) -> tuple[datetime, datetime]:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(422, "Месяц должен быть в формате ГГГГ-ММ")
    year, month_number = (int(part) for part in month.split("-"))
    start = datetime(year, month_number, 1, tzinfo=APP_TIMEZONE)
    end = datetime(year + 1, 1, 1, tzinfo=APP_TIMEZONE) if month_number == 12 else datetime(year, month_number + 1, 1, tzinfo=APP_TIMEZONE)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def build_monthly_facts(con: sqlite3.Connection, month: str, user_id: int | None = None) -> dict[str, Any]:
    user_id = current_user_id() if user_id is None else user_id
    start, end = month_bounds(month)
    start_iso, end_iso = start.isoformat(), end.isoformat()
    trades = con.execute(
        "SELECT t.id,t.side,t.quantity,t.raw_quote_tkn,t.game_pnl,t.executed_at,i.ticker,i.name "
        "FROM trades t JOIN instruments i ON i.id=t.instrument_id "
        "WHERE t.user_id=? AND t.executed_at>=? AND t.executed_at<? ORDER BY t.executed_at,t.id",
        (user_id, start_iso, end_iso),
    ).fetchall()
    conversions = con.execute(
        "SELECT id,tokens_burned,total_ac,created_at FROM conversions WHERE user_id=? AND created_at>=? AND created_at<? ORDER BY created_at,id",
        (user_id, start_iso, end_iso),
    ).fetchall()
    piggy_events = con.execute(
        "SELECT id,event_type,amount,created_at FROM ledger_entries WHERE user_id=? AND event_type IN ('PIGGY_DEPOSIT','PIGGY_WITHDRAW') "
        "AND created_at>=? AND created_at<? ORDER BY created_at,id",
        (user_id, start_iso, end_iso),
    ).fetchall()
    lessons = con.execute(
        "SELECT p.lesson_id,p.completed_at,l.title FROM lesson_progress p JOIN lessons l ON l.id=p.lesson_id "
        "WHERE p.user_id=? AND p.completed_at>=? AND p.completed_at<? ORDER BY p.completed_at,p.lesson_id",
        (user_id, start_iso, end_iso),
    ).fetchall()

    decisions: list[dict[str, Any]] = []
    for row in trades:
        item = {
            "id": f"trade-{row['id']}", "kind": row["side"], "at": row["executed_at"],
            "ticker": row["ticker"], "name": row["name"], "quantity": float(row["quantity"]),
            "quote_tkn": float(row["raw_quote_tkn"]),
        }
        if row["side"] == "sell":
            item["game_pnl"] = float(row["game_pnl"])
        decisions.append(item)
    decisions.extend(
        {
            "id": f"conversion-{row['id']}", "kind": "conversion", "at": row["created_at"],
            "tokens_burned": float(row["tokens_burned"]), "alfa_coins_received": float(row["total_ac"]),
        }
        for row in conversions
    )
    decisions.extend(
        {
            "id": f"piggy-{row['id']}",
            "kind": "piggy_deposit" if row["event_type"] == "PIGGY_DEPOSIT" else "piggy_withdraw",
            "at": row["created_at"], "amount_tkn": abs(float(row["amount"])),
        }
        for row in piggy_events
    )
    decisions.extend(
        {"id": f"lesson-{row['lesson_id']}", "kind": "lesson", "at": row["completed_at"], "title": row["title"]}
        for row in lessons
    )
    decisions.sort(key=lambda item: (item["at"], item["id"]))

    sell_pnls = [d(row["game_pnl"]) for row in trades if row["side"] == "sell"]
    losing_pnls = [value for value in sell_pnls if value < 0]
    buy_tickers = {row["ticker"] for row in trades if row["side"] == "buy"}
    open_positions = con.execute(
        "SELECT p.quantity,p.average_buy_token_price,p.raw_cost_basis,i.ticker,i.real_price_rub FROM positions p "
        "JOIN instruments i ON i.id=p.instrument_id WHERE p.user_id=?",
        (user_id,),
    ).fetchall()
    unrealized = sum(
        (game_position_value(d(row["quantity"]), d(row["average_buy_token_price"]), display_token_price(d(row["real_price_rub"])), MULTIPLIER) - d(row["raw_cost_basis"]) for row in open_positions),
        d(0),
    )
    metrics = {
        "decisions_count": len(decisions),
        "trades_count": len(trades),
        "buy_count": sum(row["side"] == "buy" for row in trades),
        "sell_count": sum(row["side"] == "sell" for row in trades),
        "winning_sells": sum(value > 0 for value in sell_pnls),
        "losing_sells": len(losing_pnls),
        "realized_pnl_tkn": float(money(sum(sell_pnls, d(0)))),
        "money_lost_tkn": float(money(-sum(losing_pnls, d(0)))),
        "current_unrealized_pnl_tkn": float(money(unrealized)),
        "unique_buy_tickers": len(buy_tickers),
        "conversions_count": len(conversions),
        "tokens_converted": float(money(sum((d(row["tokens_burned"]) for row in conversions), d(0)))),
        "piggy_deposits": sum(row["event_type"] == "PIGGY_DEPOSIT" for row in piggy_events),
        "piggy_withdrawals": sum(row["event_type"] == "PIGGY_WITHDRAW" for row in piggy_events),
        "lessons_completed": len(lessons),
    }
    return {"month": month, "metrics": metrics, "decisions": decisions}


def quest_period_keys(at: date | None = None) -> dict[str, str]:
    current = at or local_date()
    monday = current - timedelta(days=current.weekday())
    return {"daily": current.isoformat(), "weekly": f"week:{monday.isoformat()}"}


def ensure_current_quests(con: sqlite3.Connection, user_id: int | None = None, at: date | None = None) -> dict[str, str]:
    user_id = current_user_id() if user_id is None else user_id
    keys = quest_period_keys(at)
    for quest in con.execute("SELECT id,type FROM quests").fetchall():
        period_key = keys[quest["type"]]
        con.execute(
            "INSERT OR IGNORE INTO user_quests(user_id,quest_id,progress,completed,claimed,period_key) VALUES(?,?,0,0,0,?)",
            (user_id, quest["id"], period_key),
        )
    return keys


def reset_gamification_progress(con: sqlite3.Connection, user_id: int | None = None) -> None:
    user_id = current_user_id() if user_id is None else user_id
    """Reset testable learning/game progress without touching trades, positions or cash."""
    con.execute("DELETE FROM lesson_progress WHERE user_id=?", (user_id,))
    con.execute("DELETE FROM user_achievements WHERE user_id=?", (user_id,))
    con.execute("DELETE FROM streak_checkins WHERE user_id=?", (user_id,))
    con.execute("DELETE FROM user_tamagotchi_items WHERE user_id=?", (user_id,))
    con.execute("DELETE FROM tamagotchi_interactions WHERE user_id=?", (user_id,))
    con.execute("DELETE FROM monthly_ai_reports WHERE user_id=?", (user_id,))
    con.execute("DELETE FROM user_quests WHERE user_id=?", (user_id,))
    ensure_current_quests(con, user_id)
    con.execute("UPDATE users SET xp=0,level=1,streak_count=0,last_active_date=NULL WHERE id=?", (user_id,))
    con.execute("UPDATE wallets SET pending_activity_boost='0',updated_at=? WHERE user_id=?", (now(), user_id))
    con.execute("UPDATE tamagotchi SET mood=80,energy=80,knowledge=20,friendship=10,equipped_items_json='[]',last_interaction_at=? WHERE user_id=?", (now(), user_id))
    con.execute(
        "INSERT INTO gamification_state(user_id,reset_at) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET reset_at=excluded.reset_at",
        (user_id, now()),
    )


def serialize_instrument(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["display_price_tkn"] = float(display_token_price(d(row["real_price_rub"])))
    result["real_price_rub"] = float(row["real_price_rub"])
    result["previous_close"] = float(row["previous_close"])
    result["change_pct"] = float(row["change_pct"])
    result["is_delayed"] = row["source"] != "finam"
    result["is_stale"] = False
    return result


class TradeRequest(BaseModel):
    instrument_id: int
    quantity: Decimal = Field(gt=0, decimal_places=4)


class ConvertRequest(BaseModel):
    tokens: Decimal = Field(gt=0)


class AmountRequest(BaseModel):
    amount: Decimal = Field(gt=0)


class GoalRequest(BaseModel):
    shop_item_id: int


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=40)
    password: str = Field(min_length=6, max_length=72)


class LoginRequest(BaseModel):
    name: str = Field(min_length=2, max_length=40)
    password: str = Field(min_length=1, max_length=72)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=72)
    new_password: str = Field(min_length=6, max_length=72)


class ContestRequest(BaseModel):
    full_name: str
    ege_year: int
    ege_subject: str
    ege_score: int = Field(ge=0, le=100)
    certificate_mock: str
    consent: bool


class TinInteractRequest(BaseModel):
    action: str


class ProfileUpdateRequest(BaseModel):
    display_name: str = Field(min_length=2, max_length=40)
    birth_date: date


class CartItemRequest(BaseModel):
    shop_item_id: int
    quantity: int = Field(gt=0)


class CartOrderRequest(BaseModel):
    items: list[CartItemRequest]


class QuestProgressRequest(BaseModel):
    quest_action: str


class LessonCompleteRequest(BaseModel):
    # answer_index remains supported for older clients. New clients submit all
    # three answers, so a lesson cannot be completed by tapping one option.
    answer_index: int | None = Field(default=None, ge=0, le=10)
    answers: list[int] | None = Field(default=None, min_length=1, max_length=10)


class LessonAssistantRequest(BaseModel):
    lesson_id: int = Field(gt=0)
    question: str = Field(min_length=2, max_length=800)


class SocialPostRequest(BaseModel):
    trade_id: int | None = None
    comment: str = Field(min_length=1, max_length=300)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    provider: FinamTradeApiProvider | None = None
    sync_task: asyncio.Task[None] | None = None
    if MARKET_DATA_STATE["configured"]:
        provider = FinamTradeApiProvider()
        sync_task = asyncio.create_task(finam_sync_loop(provider), name="finam-market-sync")
    else:
        sync_task = asyncio.create_task(demo_market_loop(), name="demo-market-sync")
    try:
        yield
    finally:
        if sync_task:
            sync_task.cancel()
            try:
                await sync_task
            except asyncio.CancelledError:
                pass
        if provider:
            await provider.close()


app = FastAPI(title="Alfa Teen Invest API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4173", *CORS_ALLOWED_ORIGINS],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|10\..+|172\.(1[6-9]|2\d|3[01])\..+|192\.168\..+)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)


AUTH_PUBLIC_PATHS = {"/api/v1/auth/register", "/api/v1/auth/login"}


@app.middleware("http")
async def authenticate_api_request(request: Request, call_next):
    path = request.url.path
    if not AUTH_REQUIRED or not path.startswith("/api/v1/") or path in AUTH_PUBLIC_PATHS:
        return await call_next(request)
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return JSONResponse(status_code=401, content={"detail": "Войди в аккаунт"}, headers={"WWW-Authenticate": "Bearer"})
    try:
        user_id = decode_access_token(token)
        with db() as con:
            account = con.execute("SELECT is_banned FROM users WHERE id=?", (user_id,)).fetchone()
            if not account:
                raise HTTPException(401, "Пользователь не найден")
            if account["is_banned"]:
                return JSONResponse(status_code=403, content={"detail": "Аккаунт заблокирован за нарушение правил общения", "code": "ACCOUNT_BANNED"})
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers={"WWW-Authenticate": "Bearer"})
    context_token = CURRENT_USER_ID.set(user_id)
    try:
        return await call_next(request)
    finally:
        CURRENT_USER_ID.reset(context_token)


@app.get("/health")
@app.get("/health/ready")
def health():
    return {
        "status": "ok",
        "database": str(DB_PATH),
        "demo_mode": DEMO_MODE,
        "market_provider": "finam" if MARKET_DATA_STATE["configured"] else "demo-fallback",
        "market_data": dict(MARKET_DATA_STATE),
    }


def create_user_resources(con: sqlite3.Connection, user_id: int) -> None:
    con.execute("INSERT INTO wallets VALUES(?,'0','0','0','0',?)", (user_id, now()))
    con.execute("INSERT INTO piggy_accounts(user_id,balance_tkn,current_apr,last_accrual_at,yield_remainder_tkn) VALUES(?,'0','0.12',?,'0')", (user_id, now()))
    con.execute("INSERT INTO tamagotchi VALUES(?,'Тин',80,80,20,10,'[]',?)", (user_id, now()))
    con.execute("INSERT INTO contest_wallets VALUES(?,'0')", (user_id,))
    con.execute("INSERT INTO gamification_state(user_id,reset_at) VALUES(?,?)", (user_id, now()))
    ensure_current_quests(con, user_id)


def auth_user_payload(con: sqlite3.Connection, user_id: int) -> dict[str, Any]:
    user = rowdict(con.execute(
        "SELECT id,username,display_name,birth_date,onboarding_completed,referral_code,role,xp,level,is_banned FROM users WHERE id=?",
        (user_id,),
    ).fetchone())
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    user["level"] = calc_level(user["xp"])
    return enrich_user_age(user) or user


@app.post("/api/v1/auth/register")
def register(req: RegisterRequest):
    display_name, username = validate_public_name(req.name)
    validate_password(req.password)
    with db() as con:
        if con.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            raise HTTPException(409, "Это имя уже занято")
        user_id = con.execute("SELECT COALESCE(MAX(id),0)+1 FROM users").fetchone()[0]
        con.execute(
            "INSERT INTO users(id,email,username,password_hash,display_name,birth_date,onboarding_completed,referral_code,role,xp,level,streak_count,last_active_date,created_at) "
            "VALUES(?,NULL,?,?,?,?,0,?,'user',0,1,0,NULL,?)",
            (user_id, username, hash_password(req.password), display_name, "2009-01-01", f"TIN-{secrets.token_hex(3).upper()}", now()),
        )
        create_user_resources(con, user_id)
        user = auth_user_payload(con, user_id)
    return {"access_token": create_access_token(user_id), "token_type": "bearer", "user": user}


@app.post("/api/v1/auth/login")
def login(req: LoginRequest):
    _, username = normalize_login_name(req.name)
    with db() as con:
        user = con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if not user or not verify_password(req.password, user["password_hash"]):
            raise HTTPException(401, "Неверное имя или пароль")
        if user["is_banned"]:
            raise HTTPException(403, "Аккаунт заблокирован за нарушение правил общения")
        payload = auth_user_payload(con, user["id"])
    return {"access_token": create_access_token(user["id"]), "token_type": "bearer", "user": payload}


@app.post("/api/v1/auth/refresh")
def refresh_auth():
    user_id = current_user_id()
    return {"access_token": create_access_token(user_id), "token_type": "bearer"}


@app.post("/api/v1/auth/logout")
def logout():
    return {"ok": True, "revoked": True}


@app.post("/api/v1/auth/password")
def change_password(req: PasswordChangeRequest):
    user_id = current_user_id()
    validate_password(req.new_password)
    if req.current_password == req.new_password:
        raise HTTPException(422, "Новый пароль должен отличаться от текущего")
    with db() as con:
        user = con.execute("SELECT password_hash FROM users WHERE id=?", (user_id,)).fetchone()
        if not user or not verify_password(req.current_password, user["password_hash"]):
            raise HTTPException(400, "Текущий пароль указан неверно")
        con.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(req.new_password), user_id))
    return {"ok": True, "message": "Пароль изменён"}


def _as_local_datetime(at: datetime | None = None) -> datetime:
    current = at or streak_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=APP_TIMEZONE)
    return current.astimezone(APP_TIMEZONE)


def streak_reward(streak_day: int) -> dict[str, int]:
    """The reward is explicit in one place so UI and accounting cannot diverge."""
    return {"xp": 25, "boost": 20}


def get_streak_state(con: sqlite3.Connection, user_id: int | None = None, at: datetime | None = None) -> dict[str, Any]:
    user_id = current_user_id() if user_id is None else user_id
    current = _as_local_datetime(at)
    today_date = current.date()
    today = today_date.isoformat()
    user = con.execute("SELECT streak_count,last_active_date FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        raise HTTPException(404, "Пользователь не найден")

    stored_streak = max(0, int(user["streak_count"] or 0))
    last_active = user["last_active_date"]
    yesterday = (today_date - timedelta(days=1)).isoformat()
    effective_streak = stored_streak if last_active in {today, yesterday} else 0
    claimed_today = con.execute(
        "SELECT 1 FROM streak_checkins WHERE user_id=? AND checkin_date=?", (user_id, today)
    ).fetchone() is not None

    monday = today_date - timedelta(days=today_date.weekday())
    week_dates = [(monday + timedelta(days=index)).isoformat() for index in range(7)]
    checked_dates = {
        row["checkin_date"]
        for row in con.execute(
            "SELECT checkin_date FROM streak_checkins WHERE user_id=? AND checkin_date BETWEEN ? AND ?",
            (user_id, week_dates[0], week_dates[-1]),
        ).fetchall()
    }
    labels = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    week = []
    for label, checkin_date in zip(labels, week_dates):
        if checkin_date in checked_dates:
            status = "claimed"
        elif checkin_date == today:
            status = "available"
        elif checkin_date < today:
            status = "missed"
        else:
            status = "future"
        week.append({"label": label, "date": checkin_date, "status": status})

    history = [
        {
            "date": row["checkin_date"],
            "streak_day": row["streak_day"],
            "xp": row["xp_reward"],
            "boost": row["boost_reward"],
            "claimed_at": row["claimed_at"],
        }
        for row in con.execute(
            "SELECT checkin_date,streak_day,xp_reward,boost_reward,claimed_at FROM streak_checkins "
            "WHERE user_id=? ORDER BY checkin_date DESC LIMIT 14",
            (user_id,),
        ).fetchall()
    ]
    totals = con.execute(
        "SELECT COALESCE(SUM(xp_reward),0) AS xp,COALESCE(SUM(boost_reward),0) AS boost,COUNT(*) AS days "
        "FROM streak_checkins WHERE user_id=?",
        (user_id,),
    ).fetchone()
    next_midnight = datetime.combine(today_date + timedelta(days=1), datetime.min.time(), APP_TIMEZONE)
    next_claim_at = next_midnight if claimed_today else current
    reward_day = max(1, effective_streak if last_active == today else effective_streak + 1)

    return {
        "streak_count": effective_streak,
        "claimed_today": claimed_today,
        "can_claim": not claimed_today,
        "today": today,
        "last_claimed_date": last_active,
        "current_reward": streak_reward(reward_day),
        "next_claim_at": next_claim_at.isoformat(),
        "seconds_until_next_claim": max(0, int((next_claim_at - current).total_seconds())),
        "week": week,
        "history": history,
        "total_rewards": {"xp": int(totals["xp"]), "boost": int(totals["boost"]), "days": int(totals["days"])},
        "timezone": str(APP_TIMEZONE),
    }


def update_user_streak(con: sqlite3.Connection, user_id: int | None = None) -> int:
    user_id = current_user_id() if user_id is None else user_id
    """Compatibility helper: reading state no longer mutates a user's streak."""
    return get_streak_state(con, user_id)["streak_count"]


def claim_streak_reward(con: sqlite3.Connection, user_id: int | None = None, at: datetime | None = None) -> dict[str, Any]:
    user_id = current_user_id() if user_id is None else user_id
    current = _as_local_datetime(at)
    today_date = current.date()
    today = today_date.isoformat()
    existing = con.execute(
        "SELECT 1 FROM streak_checkins WHERE user_id=? AND checkin_date=?", (user_id, today)
    ).fetchone()
    if existing:
        state = get_streak_state(con, user_id, current)
        return {**state, "ok": True, "already_claimed": True, "awarded": {"xp": 0, "boost": 0}, "message": "Награда за сегодня уже получена"}

    user = con.execute("SELECT streak_count,last_active_date FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    stored_streak = max(0, int(user["streak_count"] or 0))
    yesterday = (today_date - timedelta(days=1)).isoformat()
    if user["last_active_date"] == today:
        new_streak = max(1, stored_streak)  # legacy data created before check-in history existed
    elif user["last_active_date"] == yesterday:
        new_streak = max(1, stored_streak + 1)
    else:
        new_streak = 1
    reward = streak_reward(new_streak)
    claimed_at = current.astimezone(timezone.utc).isoformat()

    con.execute(
        "INSERT INTO streak_checkins(user_id,checkin_date,streak_day,xp_reward,boost_reward,claimed_at) VALUES(?,?,?,?,?,?)",
        (user_id, today, new_streak, reward["xp"], reward["boost"], claimed_at),
    )
    con.execute(
        "UPDATE users SET streak_count=?,last_active_date=?,xp=xp+? WHERE id=?",
        (new_streak, today, reward["xp"], user_id),
    )
    wallet_row = con.execute("SELECT pending_activity_boost FROM wallets WHERE user_id=?", (user_id,)).fetchone()
    if wallet_row:
        new_boost = d(wallet_row["pending_activity_boost"]) + d(reward["boost"])
        con.execute("UPDATE wallets SET pending_activity_boost=?,updated_at=? WHERE user_id=?", (str(new_boost), now(), user_id))

    state = get_streak_state(con, user_id, current)
    return {
        **state,
        "ok": True,
        "already_claimed": False,
        "awarded": reward,
        "message": f"Дневной бонус получен: +{reward['xp']} XP · +{reward['boost']} Boost",
    }


def calc_level(xp: int) -> int:
    return max(1, (xp // 500) + 1)


def record_net_worth_snapshot(con: sqlite3.Connection, user_id: int | None = None) -> None:
    user_id = current_user_id() if user_id is None else user_id
    worth = net_worth(con, user_id)
    con.execute("INSERT INTO net_worth_snapshots(user_id,token_net_worth,created_at) VALUES(?,?,?)", (user_id, str(worth), now()))


def config_decimal(con: sqlite3.Connection, key: str, default: Decimal) -> Decimal:
    row = con.execute("SELECT value_json FROM app_config WHERE key=?", (key,)).fetchone()
    if not row:
        return default
    try:
        return d(json.loads(row[0]))
    except (json.JSONDecodeError, TypeError, ValueError):
        return default


def conversion_economy_context(con: sqlite3.Connection, user_id: int | None = None) -> dict[str, Any]:
    user_id = current_user_id() if user_id is None else user_id
    """Build the anti-inflation context for one atomic conversion.

    The basis is the greater of current net worth and the average of available
    30-day snapshots. Moving TKN out immediately before conversion therefore
    cannot improve the rate, while genuine capital growth is only mildly
    reflected by the saturating curve in economy.conversion_rate.
    """
    current_worth = net_worth(con, user_id)
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    snapshot_rows = con.execute(
        "SELECT token_net_worth FROM net_worth_snapshots WHERE user_id=? AND created_at>=?",
        (user_id, since),
    ).fetchall()
    snapshot_values = [d(row[0]) for row in snapshot_rows]
    rolling_average = money(sum(snapshot_values, d(0)) / d(len(snapshot_values))) if snapshot_values else current_worth
    capital_basis = money(max(current_worth, rolling_average))

    conversion_rows = con.execute(
        "SELECT base_ac,activity_bonus_ac,total_ac FROM conversions WHERE user_id=? AND created_at>=?",
        (user_id, since),
    ).fetchall()
    used_base = money(sum((d(row[0]) for row in conversion_rows), d(0)))
    used_boost = money(sum((d(row[1]) for row in conversion_rows), d(0)))
    used_total = money(sum((d(row[2]) for row in conversion_rows), d(0)))
    limits = {
        "base": config_decimal(con, "trading_ac_cap_30d", d(2400)),
        "boost": config_decimal(con, "activity_boost_cap_30d", d(600)),
        "total": config_decimal(con, "total_ac_cap_30d", d(3000)),
    }
    used = {"base": used_base, "boost": used_boost, "total": used_total}
    remaining = {key: money(max(d(0), limits[key] - used[key])) for key in limits}
    settings = {
        "base_rate": config_decimal(con, "conversion_base_rate", d(50)),
        "minimum_rate": config_decimal(con, "conversion_min_rate", d(5)),
        "reference_net_worth": config_decimal(con, "conversion_reference_net_worth", d(1000)),
        "rate_softening": config_decimal(con, "conversion_rate_softening", d(8000)),
    }
    return {
        "current_worth": current_worth,
        "rolling_average": rolling_average,
        "capital_basis": capital_basis,
        "limits": limits,
        "used": used,
        "remaining": remaining,
        "settings": settings,
    }


def prepare_conversion(con: sqlite3.Connection, tokens: Decimal, user_id: int | None = None) -> tuple[sqlite3.Row, dict[str, Any], dict[str, Decimal]]:
    user_id = current_user_id() if user_id is None else user_id
    w = wallet(con, user_id)
    context = conversion_economy_context(con, user_id)
    settings = context["settings"]
    remaining = context["remaining"]
    preview = conversion_preview(
        tokens,
        d(w["eligible_profit_tokens"]),
        d(w["token_cash"]),
        context["capital_basis"],
        d(w["pending_activity_boost"]),
        remaining["base"],
        remaining["boost"],
        remaining["total"],
        settings["base_rate"],
        settings["minimum_rate"],
        settings["reference_net_worth"],
        settings["rate_softening"],
    )
    return w, context, preview


@app.get("/api/v1/auth/me")
def me():
    user_id = current_user_id()
    with db() as con:
        streak_state = get_streak_state(con, user_id)
        user = rowdict(con.execute("SELECT id,username,display_name,birth_date,onboarding_completed,referral_code,role,xp,level FROM users WHERE id=?", (user_id,)).fetchone())
        if user:
            user["level"] = calc_level(user["xp"])
            user["streak"] = streak_state["streak_count"]
            user["streak_state"] = streak_state
        return enrich_user_age(user)


@app.put("/api/v1/auth/me")
def update_me(req: ProfileUpdateRequest):
    user_id = current_user_id()
    display_name, _ = validate_public_name(req.display_name)
    with db() as con:
        age = age_from_birth_date(req.birth_date)
        if age < 6 or age > 100:
            raise HTTPException(422, "Укажи настоящую дату рождения")
        con.execute("UPDATE users SET display_name=?,birth_date=? WHERE id=?", (display_name, str(req.birth_date), user_id))
        user = rowdict(con.execute("SELECT id,username,display_name,birth_date,onboarding_completed,referral_code,role,xp,level FROM users WHERE id=?", (user_id,)).fetchone())
        if user:
            user["level"] = calc_level(user["xp"])
            streak_state = get_streak_state(con, user_id)
            user["streak"] = streak_state["streak_count"]
            user["streak_state"] = streak_state
        return {"ok": True, "user": enrich_user_age(user)}


def social_user_summary(con: sqlite3.Connection, user_id: int, viewer_id: int | None = None) -> dict[str, Any]:
    viewer_id = current_user_id() if viewer_id is None else viewer_id
    user = con.execute("SELECT id,display_name,referral_code,xp,is_banned FROM users WHERE id=?", (user_id,)).fetchone()
    if not user or user["is_banned"]:
        raise HTTPException(404, "Пользователь не найден")
    capital = net_worth(con, user_id)
    friend = bool(con.execute("SELECT 1 FROM user_friends WHERE user_id=? AND friend_user_id=?", (viewer_id, user_id)).fetchone())
    return {
        "id": user["id"],
        "public_id": user["referral_code"],
        "display_name": user["display_name"],
        "avatar": (user["display_name"] or "?")[0].upper(),
        "capital_tkn": float(capital),
        "xp": user["xp"],
        "level": calc_level(user["xp"]),
        "is_friend": friend,
        "trades_count": con.execute("SELECT COUNT(*) FROM trades WHERE user_id=?", (user_id,)).fetchone()[0],
        "posts_count": con.execute("SELECT COUNT(*) FROM social_posts WHERE user_id=?", (user_id,)).fetchone()[0],
    }


def public_trade_rows(con: sqlite3.Connection, user_ids: list[int], limit: int = 30) -> list[dict[str, Any]]:
    if not user_ids:
        return []
    placeholders = ",".join("?" for _ in user_ids)
    rows = con.execute(
        f"SELECT t.id,t.user_id,t.side,t.quantity,t.raw_quote_tkn,t.game_pnl,t.executed_at,i.ticker,i.name,u.display_name "
        f"FROM trades t JOIN instruments i ON i.id=t.instrument_id JOIN users u ON u.id=t.user_id "
        f"WHERE t.user_id IN ({placeholders}) ORDER BY t.executed_at DESC,t.id DESC LIMIT ?",
        (*user_ids, limit),
    ).fetchall()
    return [
        {
            "id": row["id"], "user_id": row["user_id"], "display_name": row["display_name"],
            "side": row["side"], "quantity": float(row["quantity"]), "quote_tkn": float(row["raw_quote_tkn"]),
            "game_pnl": float(row["game_pnl"]), "executed_at": row["executed_at"],
            "ticker": row["ticker"], "instrument_name": row["name"],
        }
        for row in rows
    ]


def public_post_rows(con: sqlite3.Connection, user_ids: list[int], limit: int = 30) -> list[dict[str, Any]]:
    if not user_ids:
        return []
    placeholders = ",".join("?" for _ in user_ids)
    rows = con.execute(
        f"SELECT p.id,p.user_id,p.comment,p.created_at,u.display_name,u.referral_code FROM social_posts p "
        f"JOIN users u ON u.id=p.user_id WHERE p.user_id IN ({placeholders}) AND COALESCE(u.is_banned,0)=0 "
        f"ORDER BY p.created_at DESC,p.id DESC LIMIT ?",
        (*user_ids, limit),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        tickers = extract_mentioned_tickers(row["comment"])
        mentions: list[dict[str, Any]] = []
        for ticker in tickers:
            instrument = con.execute(
                "SELECT id,ticker,name,type,sector,real_price_rub,change_pct FROM instruments WHERE UPPER(ticker)=? AND enabled=1",
                (ticker,),
            ).fetchone()
            if instrument:
                mentions.append({
                    "id": instrument["id"], "ticker": instrument["ticker"], "name": instrument["name"],
                    "type": instrument["type"], "sector": instrument["sector"],
                    "display_price_tkn": float(display_token_price(d(instrument["real_price_rub"]))),
                    "change_pct": float(instrument["change_pct"]),
                })
        result.append({
            "id": row["id"], "user_id": row["user_id"], "display_name": row["display_name"],
            "public_id": row["referral_code"], "comment": row["comment"], "created_at": row["created_at"],
            "mentions": mentions,
        })
    return result


@app.get("/api/v1/social/feed")
def social_feed(scope: str = "top"):
    if scope not in {"top", "friends"}:
        raise HTTPException(422, "Неизвестный режим ленты")
    viewer_id = current_user_id()
    with db() as con:
        current = enrich_user_age(rowdict(con.execute("SELECT birth_date FROM users WHERE id=?", (viewer_id,)).fetchone()))
        community_ids = [row[0] for row in con.execute("SELECT id FROM users WHERE id<>? AND COALESCE(is_banned,0)=0 ORDER BY id", (viewer_id,)).fetchall()]
        community = sorted((social_user_summary(con, user_id, viewer_id) for user_id in community_ids), key=lambda item: (-item["capital_tkn"], item["id"]))
        top = community[:5]
        for rank, item in enumerate(top, 1):
            item["rank"] = rank
        friends = [item for item in community if item["is_friend"]]
        source_ids = [viewer_id, *[item["id"] for item in (friends if scope == "friends" else top)]]
        return {
            "title": current["social_title"] if current else "Тин-Ток",
            "viewer_id": viewer_id,
            "scope": scope,
            "top_users": top,
            "friends": friends,
            "posts": public_post_rows(con, source_ids),
            "trades": public_trade_rows(con, source_ids),
        }


@app.get("/api/v1/social/users")
def social_users(search: str = ""):
    viewer_id = current_user_id()
    with db() as con:
        query = "SELECT id FROM users WHERE id<>? AND COALESCE(is_banned,0)=0"
        params: list[Any] = [viewer_id]
        if search.strip():
            normalized = search.strip().upper()
            query += " AND UPPER(referral_code)=?"
            params.append(normalized)
        summaries = [social_user_summary(con, row[0], viewer_id) for row in con.execute(query + " ORDER BY display_name LIMIT 20", params).fetchall()]
        return sorted(summaries, key=lambda item: (-item["capital_tkn"], item["display_name"]))


@app.get("/api/v1/social/users/{user_id}")
def social_user_profile(user_id: int):
    viewer_id = current_user_id()
    if user_id == viewer_id:
        raise HTTPException(400, "Это твой профиль")
    with db() as con:
        summary = social_user_summary(con, user_id, viewer_id)
        positions = con.execute(
            "SELECT p.quantity,p.average_buy_token_price,i.id,i.ticker,i.name,i.real_price_rub FROM positions p JOIN instruments i ON i.id=p.instrument_id WHERE p.user_id=? ORDER BY p.id",
            (user_id,),
        ).fetchall()
        summary["positions"] = [
            {
                "instrument_id": row["id"], "ticker": row["ticker"], "name": row["name"],
                "quantity": float(row["quantity"]),
                "value_tkn": float(game_position_value(d(row["quantity"]), d(row["average_buy_token_price"]), display_token_price(d(row["real_price_rub"])), MULTIPLIER)),
            }
            for row in positions
        ]
        summary["trades"] = public_trade_rows(con, [user_id], 20)
        summary["posts"] = public_post_rows(con, [user_id], 20)
        return summary


@app.post("/api/v1/social/posts")
def create_social_post(req: SocialPostRequest):
    user_id = current_user_id()
    comment = req.comment.strip()
    if not comment:
        raise HTTPException(422, "Пост не может быть пустым")
    if contains_profanity(comment):
        raise HTTPException(422, "Комментарий не отправлен: убери мат и попробуй снова")
    with db() as con:
        trade = None
        if req.trade_id is not None:
            trade = con.execute(
                "SELECT t.id,i.ticker FROM trades t JOIN instruments i ON i.id=t.instrument_id WHERE t.id=? AND t.user_id=? AND t.status='executed'",
                (req.trade_id, user_id),
            ).fetchone()
            if not trade:
                raise HTTPException(404, "Сделка не найдена")
        try:
            post_id = con.execute(
                "INSERT INTO social_posts(user_id,trade_id,comment,created_at) VALUES(?,?,?,?)",
                (user_id, req.trade_id, comment, now()),
            ).lastrowid
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Этой сделкой уже поделились")
        mentioned = extract_mentioned_tickers(comment)
        known_mentions = [
            ticker for ticker in mentioned
            if con.execute("SELECT 1 FROM instruments WHERE UPPER(ticker)=? AND enabled=1", (ticker,)).fetchone()
        ]
        return {"ok": True, "post_id": post_id, "mentions": known_mentions, "message": "Пост опубликован"}


@app.delete("/api/v1/social/posts/{post_id}")
def delete_social_post(post_id: int):
    user_id = current_user_id()
    with db() as con:
        post = con.execute("SELECT user_id FROM social_posts WHERE id=?", (post_id,)).fetchone()
        if not post:
            raise HTTPException(404, "Пост не найден")
        if post["user_id"] != user_id:
            raise HTTPException(403, "Можно удалять только свои посты")
        con.execute("DELETE FROM social_posts WHERE id=? AND user_id=?", (post_id, user_id))
    return {"ok": True, "message": "Пост удалён"}


@app.post("/api/v1/social/friends/{friend_user_id}")
def toggle_social_friend(friend_user_id: int):
    user_id = current_user_id()
    if friend_user_id == user_id:
        raise HTTPException(400, "Нельзя добавить себя")
    with db() as con:
        if not con.execute("SELECT 1 FROM users WHERE id=? AND COALESCE(is_banned,0)=0", (friend_user_id,)).fetchone():
            raise HTTPException(404, "Пользователь не найден")
        exists = con.execute("SELECT 1 FROM user_friends WHERE user_id=? AND friend_user_id=?", (user_id, friend_user_id)).fetchone()
        if exists:
            con.execute("DELETE FROM user_friends WHERE user_id=? AND friend_user_id=?", (user_id, friend_user_id))
            return {"ok": True, "is_friend": False, "message": "Пользователь удалён из друзей"}
        con.execute("INSERT INTO user_friends VALUES(?,?,?)", (user_id, friend_user_id, now()))
        return {"ok": True, "is_friend": True, "message": "Пользователь добавлен в друзья"}


@app.get("/api/v1/streak")
def streak_status():
    with db() as con:
        return get_streak_state(con)


@app.post("/api/v1/streak/claim")
def claim_streak():
    with db() as con:
        # Serialize check-ins before the read so two simultaneous clicks cannot award twice.
        con.execute("BEGIN IMMEDIATE")
        return claim_streak_reward(con)


@app.post("/api/v1/onboarding/complete")
def onboarding_complete(goal: GoalRequest):
    user_id = current_user_id()
    with db() as con:
        user = con.execute("SELECT onboarding_completed FROM users WHERE id=?", (user_id,)).fetchone()
        w = wallet(con, user_id)
        if not user[0]:
            cash = d(w["token_cash"]) + d(1000)
            con.execute("UPDATE wallets SET token_cash=?,updated_at=? WHERE user_id=?", (str(cash), now(), user_id))
            ledger(con, "START_GRANT", d(1000), cash, user_id=user_id)
        con.execute("UPDATE users SET onboarding_completed=1 WHERE id=?", (user_id,))
        con.execute("INSERT OR REPLACE INTO user_goals VALUES(?,?,?)", (user_id, goal.shop_item_id, now()))
        record_net_worth_snapshot(con, user_id)
    return {"ok": True}


@app.get("/api/v1/onboarding")
def onboarding():
    return {"steps": ["Учись без риска", "Получи 1 000 TKN", "Следи за рынком", "Прибыль превращай в Alfa Coins", "Выбери цель"], "starting_tokens": 1000}


@app.get("/api/v1/dashboard")
def dashboard():
    user_id = current_user_id()
    with db() as con:
        w = wallet(con, user_id)
        worth = net_worth(con, user_id)
        streak_state = get_streak_state(con, user_id)
        user = rowdict(con.execute("SELECT id,display_name,birth_date,onboarding_completed,referral_code,xp,level FROM users WHERE id=?", (user_id,)).fetchone())
        if user:
            user["level"] = calc_level(user["xp"])
            enrich_user_age(user)
        quest_keys = ensure_current_quests(con, user_id)
        quest_summary_row = con.execute(
            "SELECT COUNT(*) AS total, COALESCE(SUM(u.completed),0) AS done, "
            "COALESCE(SUM(CASE WHEN q.type='daily' THEN 1 ELSE 0 END),0) AS daily_total, "
            "COALESCE(SUM(CASE WHEN q.type='daily' THEN u.completed ELSE 0 END),0) AS daily_done, "
            "COALESCE(SUM(CASE WHEN q.type='weekly' THEN 1 ELSE 0 END),0) AS weekly_total, "
            "COALESCE(SUM(CASE WHEN q.type='weekly' THEN u.completed ELSE 0 END),0) AS weekly_done "
            "FROM user_quests u JOIN quests q ON q.id=u.quest_id "
            "WHERE u.user_id=? AND u.period_key=CASE q.type WHEN 'daily' THEN ? ELSE ? END",
            (user_id, quest_keys["daily"], quest_keys["weekly"]),
        ).fetchone()
        quest_summary = dict(quest_summary_row)
        goal = con.execute("SELECT s.* FROM user_goals g JOIN shop_items s ON s.id=g.shop_item_id WHERE g.user_id=?", (user_id,)).fetchone()
        finam_quote = con.execute("SELECT source_timestamp FROM instruments WHERE source='finam' ORDER BY source_timestamp DESC LIMIT 1").fetchone()
        asset_rows = con.execute(
            "SELECT p.*,i.type,i.real_price_rub FROM positions p JOIN instruments i ON i.id=p.instrument_id WHERE p.user_id=?",
            (user_id,),
        ).fetchall()
        stock_value = d(0)
        fund_value = d(0)
        for asset in asset_rows:
            asset_value = game_position_value(d(asset["quantity"]), d(asset["average_buy_token_price"]), display_token_price(d(asset["real_price_rub"])), MULTIPLIER)
            if asset["type"] == "fund":
                fund_value += asset_value
            else:
                stock_value += asset_value
        piggy_value = d(rowdict(con.execute("SELECT balance_tkn FROM piggy_accounts WHERE user_id=?", (user_id,)).fetchone())["balance_tkn"])
        return {
            "user": user, "wallet": dict(w), "net_worth": float(worth), "all_time_change_pct": float(money((worth-d(1000))/d(1000)*100)),
            "invested": float(position_value(con, user_id)), "piggy": rowdict(con.execute("SELECT * FROM piggy_accounts WHERE user_id=?", (user_id,)).fetchone()),
            "wallet_breakdown": {"spendable": float(w["token_cash"]), "stocks": float(stock_value), "funds": float(fund_value), "piggy": float(piggy_value)},
            "goal": dict(goal) if goal else None, "streak": streak_state["streak_count"], "streak_state": streak_state,
            "quests_done": quest_summary["daily_done"], "quest_summary": quest_summary,
            "market_status": {"label": "Live" if finam_quote else "Демо-данные", "timestamp": finam_quote[0] if finam_quote else now(), "live": bool(finam_quote)},
        }


@app.get("/api/v1/market/instruments")
def instruments(type: str | None = None, search: str | None = None):
    query = "SELECT * FROM instruments WHERE enabled=1"
    params: list[Any] = []
    if type:
        query += " AND type=?"; params.append(type)
    if search:
        query += " AND (ticker LIKE ? OR name LIKE ?)"; params += [f"%{search}%", f"%{search}%"]
    query += " ORDER BY featured DESC, change_pct DESC"
    with db() as con:
        return [serialize_instrument(r) for r in con.execute(query, params).fetchall()]


@app.get("/api/v1/market/instruments/{instrument_id}")
def instrument(instrument_id: int):
    user_id = current_user_id()
    with db() as con:
        row = con.execute("SELECT * FROM instruments WHERE id=?", (instrument_id,)).fetchone()
        if not row: raise HTTPException(404, "Инструмент не найден")
        result = serialize_instrument(row)
        current_tkn = float(display_token_price(d(row["real_price_rub"])))
        prev_tkn = float(display_token_price(d(row["previous_close"] or row["real_price_rub"])))
        diff = current_tkn - prev_tkn
        candles_list = []
        for i in range(12):
            step_val = prev_tkn + (diff * (i / 11.0)) + (((i % 4) - 1.5) * 0.005 * current_tkn)
            candles_list.append({"t": i, "v": round(max(0.01, step_val), 2)})
        candles_list[-1]["v"] = round(current_tkn, 2)
        result["candles"] = candles_list
        pos = con.execute("SELECT * FROM positions WHERE user_id=? AND instrument_id=?", (user_id, instrument_id)).fetchone()
        result["position"] = dict(pos) if pos else None
        return result


@app.get("/api/v1/market/instruments/{instrument_id}/candles")
def candles(instrument_id: int):
    item = instrument(instrument_id)
    return item["candles"]


@app.get("/api/v1/market/movers")
def movers():
    with db() as con:
        return [serialize_instrument(r) for r in con.execute("SELECT * FROM instruments WHERE enabled=1 ORDER BY ABS(CAST(change_pct AS REAL)) DESC LIMIT 8").fetchall()]


async def portfolio_news_insights(refresh: bool = False, user_id: int | None = None) -> dict[str, Any]:
    user_id = current_user_id() if user_id is None else user_id
    generated_at = now()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=NEWS_CACHE_MINUTES)
    with db() as con:
        holdings = [
            dict(row)
            for row in con.execute(
                "SELECT i.id,i.ticker,i.name,i.type,i.real_price_rub,i.change_pct,p.quantity "
                "FROM positions p JOIN instruments i ON i.id=p.instrument_id "
                "WHERE p.user_id=? AND i.type='stock' AND CAST(p.quantity AS REAL)>0 ORDER BY CAST(p.raw_cost_basis AS REAL) DESC,i.ticker LIMIT 4",
                (user_id,),
            ).fetchall()
        ]
        cached_rows = {
            row["instrument_id"]: row
            for row in con.execute("SELECT instrument_id,payload_json,generated_at FROM news_insight_cache WHERE user_id=?", (user_id,)).fetchall()
        }

    items: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for holding in holdings:
        cached = cached_rows.get(holding["id"])
        cached_item: dict[str, Any] | None = None
        try:
            cached_item = json.loads(cached["payload_json"]) if cached else None
            is_fresh = bool(
                cached
                and datetime.fromisoformat(cached["generated_at"]) >= cutoff
                and cached_item
                and cached_item.get("insight", {}).get("copy_version") == PortfolioNewsService.COPY_VERSION
            )
        except (ValueError, TypeError, json.JSONDecodeError):
            is_fresh = False
        if cached_item and is_fresh and not refresh:
            items.append(cached_item)
        else:
            missing.append(holding)

    service = PortfolioNewsService()
    semaphore = asyncio.Semaphore(3)

    async def build_item(holding: dict[str, Any]) -> dict[str, Any]:
        async with semaphore:
            try:
                articles = await service.fetch_articles(holding["ticker"], holding["name"])
            except (httpx.HTTPError, ValueError):
                articles = []
            insight = await service.analyze(
                holding["ticker"],
                holding["name"],
                float(holding["real_price_rub"]),
                float(holding["change_pct"]),
                articles,
            )
            return {
                "instrument": {
                    "id": holding["id"],
                    "ticker": holding["ticker"],
                    "name": holding["name"],
                    "type": holding["type"],
                    "quantity": float(holding["quantity"]),
                    "real_price_rub": float(holding["real_price_rub"]),
                    "change_pct": float(holding["change_pct"]),
                },
                "insight": insight,
                "articles": [article.to_dict() for article in articles],
                "generated_at": generated_at,
            }

    fresh_items: list[dict[str, Any]] = []
    try:
        fresh_items = await asyncio.gather(*(build_item(holding) for holding in missing))
    finally:
        await service.close()
    if fresh_items:
        with db() as con:
            for item in fresh_items:
                con.execute(
                    "INSERT INTO news_insight_cache(user_id,instrument_id,payload_json,generated_at) VALUES(?,?,?,?) "
                    "ON CONFLICT(user_id,instrument_id) DO UPDATE SET payload_json=excluded.payload_json,generated_at=excluded.generated_at",
                    (user_id, item["instrument"]["id"], json.dumps(item, ensure_ascii=False), generated_at),
                )
        items.extend(fresh_items)
    items.sort(key=lambda item: (item["instrument"]["type"], item["instrument"]["ticker"]))
    return {
        "generated_at": generated_at,
        "cache_minutes": NEWS_CACHE_MINUTES,
        "items": items,
        "disclaimer": "Мы показываем факты из новостей и отдельно объясняем их значение для бизнеса. Это не совет покупать или продавать.",
    }


@app.get("/api/v1/news/portfolio-insights")
async def get_portfolio_news_insights():
    return await portfolio_news_insights(refresh=False)


@app.post("/api/v1/news/portfolio-insights/refresh")
async def refresh_portfolio_news_insights():
    return await portfolio_news_insights(refresh=True)


@app.get("/api/v1/market/watchlist")
def watchlist_api():
    user_id = current_user_id()
    with db() as con:
        return [serialize_instrument(r) for r in con.execute("SELECT i.* FROM watchlist w JOIN instruments i ON i.id=w.instrument_id WHERE w.user_id=?", (user_id,)).fetchall()]


@app.post("/api/v1/market/watchlist/{instrument_id}")
def watch(instrument_id: int):
    user_id = current_user_id()
    with db() as con: con.execute("INSERT OR IGNORE INTO watchlist VALUES(?,?)", (user_id, instrument_id))
    return {"watchlisted": True}


@app.delete("/api/v1/market/watchlist/{instrument_id}")
def unwatch(instrument_id: int):
    user_id = current_user_id()
    with db() as con: con.execute("DELETE FROM watchlist WHERE user_id=? AND instrument_id=?", (user_id, instrument_id))
    return {"watchlisted": False}


def trade_preview(req: TradeRequest, side: str, user_id: int | None = None) -> dict[str, Any]:
    user_id = current_user_id() if user_id is None else user_id
    with db() as con:
        inst = con.execute("SELECT * FROM instruments WHERE id=? AND enabled=1", (req.instrument_id,)).fetchone()
        if not inst: raise HTTPException(404, "Инструмент недоступен")
        quote = display_token_price(d(inst["real_price_rub"])); qty = d(req.quantity)
        if side == "buy":
            cost = money(quote * qty)
            return {"side": side, "quantity": float(qty), "quote": float(quote), "cash_change": -float(cost), "enough_cash": d(wallet(con, user_id)["token_cash"]) >= cost}
        pos = con.execute("SELECT * FROM positions WHERE user_id=? AND instrument_id=?", (user_id, req.instrument_id)).fetchone()
        if not pos or d(pos["quantity"]) < qty: raise HTTPException(400, "Недостаточно актива для продажи")
        result = sell_result(qty, d(pos["average_buy_token_price"]), quote, MULTIPLIER)
        return {"side": side, "quantity": float(qty), "quote": float(quote), "average_entry": float(pos["average_buy_token_price"]), "raw_pnl": float(result.raw_pnl), "game_pnl": float(result.game_pnl), "cash_change": float(result.cash_credit), "eligible_profit": float(result.eligible_profit)}


@app.post("/api/v1/trades/preview")
def preview(req: TradeRequest, side: str = "buy"):
    return trade_preview(req, side)


@app.post("/api/v1/trades/buy")
def buy(req: TradeRequest, idempotency_key: str | None = Header(None)):
    user_id = current_user_id()
    key = idempotency_key or secrets.token_hex(12)
    with db() as con:
        cached = con.execute("SELECT response_json FROM idempotency WHERE user_id=? AND key=?", (user_id, key)).fetchone()
        if cached: return json.loads(cached[0])
        inst = con.execute("SELECT * FROM instruments WHERE id=? AND enabled=1", (req.instrument_id,)).fetchone()
        if not inst: raise HTTPException(404, "Инструмент недоступен")
        quote = display_token_price(d(inst["real_price_rub"])); qty = d(req.quantity); cost = money(quote * qty); w = wallet(con, user_id); cash = d(w["token_cash"])
        is_first_purchase = con.execute("SELECT COUNT(*) FROM trades WHERE user_id=? AND side='buy'", (user_id,)).fetchone()[0] == 0
        if cost > cash: raise HTTPException(400, "Недостаточно TKN")
        pos = con.execute("SELECT * FROM positions WHERE user_id=? AND instrument_id=?", (user_id, req.instrument_id)).fetchone()
        old_qty = d(pos["quantity"]) if pos else d(0); old_avg = d(pos["average_buy_token_price"]) if pos else d(0)
        new_qty = old_qty + qty; avg = weighted_average(old_qty, old_avg, qty, quote)
        con.execute("INSERT INTO positions(user_id,instrument_id,quantity,average_buy_token_price,raw_cost_basis,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(user_id,instrument_id) DO UPDATE SET quantity=excluded.quantity,average_buy_token_price=excluded.average_buy_token_price,raw_cost_basis=excluded.raw_cost_basis,updated_at=excluded.updated_at", (user_id, req.instrument_id, str(new_qty), str(avg), str(money(new_qty*avg)), now()))
        new_cash = money(cash - cost); con.execute("UPDATE wallets SET token_cash=?,updated_at=? WHERE user_id=?", (str(new_cash), now(), user_id))
        trade_id = con.execute("INSERT INTO trades(user_id,instrument_id,side,quantity,raw_quote_tkn,raw_pnl,game_pnl,cash_change_tkn,status,idempotency_key,executed_at) VALUES(?,?,'buy',?,?, '0','0',?,'executed',?,?)", (user_id, req.instrument_id, str(qty), str(quote), str(-cost), key, now())).lastrowid
        ledger(con, "TRADE_BUY", -cost, new_cash, ref_type="trade", ref_id=str(trade_id), user_id=user_id)
        record_net_worth_snapshot(con, user_id)
        response = {"ok": True, "trade_id": trade_id, "cash": float(new_cash), "message": f"Куплено {qty} {inst['ticker']}", "ticker": inst["ticker"], "side": "buy", "quantity": float(qty), "quote_tkn": float(quote), "is_first_purchase": is_first_purchase, "share_prompt": is_first_purchase}
        con.execute("INSERT INTO idempotency VALUES(?,?,?,?)", (user_id, key, json.dumps(response, ensure_ascii=False), now()))
        return response


@app.post("/api/v1/trades/sell")
def sell(req: TradeRequest, idempotency_key: str | None = Header(None)):
    user_id = current_user_id()
    key = idempotency_key or secrets.token_hex(12)
    with db() as con:
        cached = con.execute("SELECT response_json FROM idempotency WHERE user_id=? AND key=?", (user_id, key)).fetchone()
        if cached: return json.loads(cached[0])
        inst = con.execute("SELECT * FROM instruments WHERE id=?", (req.instrument_id,)).fetchone(); pos = con.execute("SELECT * FROM positions WHERE user_id=? AND instrument_id=?", (user_id, req.instrument_id)).fetchone()
        qty = d(req.quantity)
        if not pos or d(pos["quantity"]) < qty: raise HTTPException(400, "Недостаточно актива для продажи")
        quote = display_token_price(d(inst["real_price_rub"])); result = sell_result(qty, d(pos["average_buy_token_price"]), quote, MULTIPLIER); w = wallet(con, user_id)
        remaining = d(pos["quantity"]) - qty
        if remaining == 0: con.execute("DELETE FROM positions WHERE id=?", (pos["id"],))
        else: con.execute("UPDATE positions SET quantity=?,raw_cost_basis=?,updated_at=? WHERE id=?", (str(remaining), str(money(remaining*d(pos["average_buy_token_price"]))), now(), pos["id"]))
        cash = money(d(w["token_cash"]) + result.cash_credit); eligible = money(d(w["eligible_profit_tokens"]) + result.eligible_profit)
        con.execute("UPDATE wallets SET token_cash=?,eligible_profit_tokens=?,updated_at=? WHERE user_id=?", (str(cash), str(eligible), now(), user_id))
        trade_id = con.execute("INSERT INTO trades(user_id,instrument_id,side,quantity,raw_quote_tkn,raw_pnl,game_pnl,cash_change_tkn,status,idempotency_key,executed_at) VALUES(?,?,'sell',?,?,?,?,?,'executed',?,?)", (user_id, req.instrument_id, str(qty), str(quote), str(result.raw_pnl), str(result.game_pnl), str(result.cash_credit), key, now())).lastrowid
        ledger(con, "TRADE_SELL", result.cash_credit, cash, ref_type="trade", ref_id=str(trade_id), user_id=user_id); ledger(con, "REALIZED_PROFIT" if result.game_pnl >= 0 else "REALIZED_LOSS", result.game_pnl, cash, ref_type="trade", ref_id=str(trade_id), user_id=user_id)
        record_net_worth_snapshot(con, user_id)
        response = {"ok": True, "trade_id": trade_id, "cash": float(cash), "eligible_profit": float(eligible), "game_pnl": float(result.game_pnl), "message": f"Продано {qty} {inst['ticker']}", "ticker": inst["ticker"], "side": "sell", "quantity": float(qty), "quote_tkn": float(quote), "share_prompt": result.game_pnl > 0}
        con.execute("INSERT INTO idempotency VALUES(?,?,?,?)", (user_id, key, json.dumps(response, ensure_ascii=False), now()))
        return response


@app.get("/api/v1/portfolio")
def portfolio():
    user_id = current_user_id()
    with db() as con:
        rows = con.execute("SELECT p.*,i.ticker,i.name,i.type,i.real_price_rub,i.change_pct FROM positions p JOIN instruments i ON i.id=p.instrument_id WHERE p.user_id=?", (user_id,)).fetchall()
        positions = []
        stocks_val = d(0)
        funds_val = d(0)
        for r in rows:
            quote = display_token_price(d(r["real_price_rub"])); val = game_position_value(d(r["quantity"]), d(r["average_buy_token_price"]), quote, MULTIPLIER)
            positions.append({**dict(r), "quote": float(quote), "game_value": float(val), "game_pnl": float(val-d(r["raw_cost_basis"]))})
            if r["type"] == "fund":
                funds_val += val
            else:
                stocks_val += val
        
        piggy_row = con.execute("SELECT balance_tkn FROM piggy_accounts WHERE user_id=?", (user_id,)).fetchone()
        piggy_val = d(piggy_row["balance_tkn"]) if piggy_row else d(0)
        total_assets = stocks_val + funds_val + piggy_val
        if total_assets > d(0):
            stock_pct = round(float((stocks_val / total_assets) * 100))
            fund_pct = round(float((funds_val / total_assets) * 100))
            piggy_pct = max(0, 100 - stock_pct - fund_pct)
        else:
            stock_pct, fund_pct, piggy_pct = 0, 0, 0

        w = wallet(con, user_id); worth = net_worth(con, user_id)
        return {
            "net_worth": float(worth), "cash": float(w["token_cash"]), "invested": float(position_value(con, user_id)),
            "stocks": float(stocks_val), "funds": float(funds_val), "piggy": float(piggy_val),
            "eligible_profit": float(w["eligible_profit_tokens"]), "positions": positions,
            "allocation": [
                {"name": "Акции", "value": stock_pct},
                {"name": "Фонды", "value": fund_pct},
                {"name": "Копилка", "value": piggy_pct}
            ]
        }


@app.get("/api/v1/portfolio/positions")
def portfolio_positions():
    return portfolio()["positions"]


@app.get("/api/v1/portfolio/trades")
def portfolio_trades():
    user_id = current_user_id()
    with db() as con:
        return [dict(r) for r in con.execute("SELECT t.*,i.ticker,i.name FROM trades t JOIN instruments i ON i.id=t.instrument_id WHERE t.user_id=? ORDER BY t.id DESC", (user_id,)).fetchall()]


@app.get("/api/v1/portfolio/history")
def portfolio_history():
    user_id = current_user_id()
    with db() as con:
        current = float(net_worth(con, user_id))
        snapshots = con.execute("SELECT token_net_worth, created_at FROM net_worth_snapshots WHERE user_id=? ORDER BY id DESC LIMIT 7", (user_id,)).fetchall()
        if snapshots and len(snapshots) >= 2:
            items = list(reversed(snapshots))
            result = []
            for idx, s in enumerate(items):
                dt_str = s["created_at"].split("T")[0] if "T" in s["created_at"] else s["created_at"]
                result.append({"date": dt_str, "value": float(s["token_net_worth"])})
            return result
        return [{"date": (date.today()-timedelta(days=6-i)).isoformat(), "value": round(current*(0.95+i*0.008),2)} for i in range(7)]


@app.get("/api/v1/trades/{trade_id}")
def get_trade(trade_id: int):
    user_id = current_user_id()
    with db() as con:
        result = rowdict(con.execute("SELECT * FROM trades WHERE id=? AND user_id=?", (trade_id, user_id)).fetchone())
        if not result: raise HTTPException(404, "Сделка не найдена")
        return result


@app.get("/api/v1/economy/conversion")
def conversion():
    user_id = current_user_id()
    with db() as con:
        w = wallet(con, user_id)
        w, context, preview = prepare_conversion(con, d(w["eligible_profit_tokens"]), user_id)
        return {
            **{key: float(value) for key, value in preview.items()},
            "eligible": float(w["eligible_profit_tokens"]),
            "pending_boost": float(w["pending_activity_boost"]),
            "current_net_worth": float(context["current_worth"]),
            "rolling_net_worth": float(context["capital_basis"]),
            "rolling_average_net_worth": float(context["rolling_average"]),
            "rate_floor": float(context["settings"]["minimum_rate"]),
            "caps": {
                key: {"limit": float(context["limits"][key]), "used": float(context["used"][key]), "remaining": float(context["remaining"][key])}
                for key in ("base", "boost", "total")
            },
            "piggy_yield_convertible": True,
        }


@app.post("/api/v1/economy/conversion/preview")
def conversion_preview_api(req: ConvertRequest):
    user_id = current_user_id()
    with db() as con:
        _, context, preview = prepare_conversion(con, req.tokens, user_id)
        return {**{key: float(value) for key, value in preview.items()}, "rolling_net_worth": float(context["capital_basis"]), "cap_remaining": float(context["remaining"]["total"])}


@app.post("/api/v1/economy/convert")
def convert(req: ConvertRequest):
    user_id = current_user_id()
    with db() as con:
        w, context, p = prepare_conversion(con, req.tokens, user_id)
        if p["tokens"] <= 0:
            if d(w["eligible_profit_tokens"]) > 0 and (context["remaining"]["base"] <= 0 or context["remaining"]["total"] <= 0):
                raise HTTPException(400, "Лимит получения Alfa Coins за 30 дней исчерпан")
            raise HTTPException(400, "Нет заработанных TKN, доступных к обмену")
        cash = money(d(w["token_cash"])-p["tokens"]); eligible = money(d(w["eligible_profit_tokens"])-p["tokens"]); ac = money(d(w["alfa_coins"])+p["total_ac"]); boost = money(d(w["pending_activity_boost"])-p["boost_ac"])
        con.execute("UPDATE wallets SET token_cash=?,eligible_profit_tokens=?,alfa_coins=?,pending_activity_boost=?,updated_at=? WHERE user_id=?", (str(cash),str(eligible),str(ac),str(boost),now(),user_id))
        cid = con.execute("INSERT INTO conversions(user_id,tokens_burned,conversion_rate,base_ac,activity_bonus_ac,total_ac,rolling_net_worth,created_at) VALUES(?,?,?,?,?,?,?,?)", (user_id,str(p["tokens"]),str(p["rate"]),str(p["base_ac"]),str(p["boost_ac"]),str(p["total_ac"]),str(context["capital_basis"]),now())).lastrowid
        ledger(con,"TOKEN_TO_AC_CONVERSION",-p["tokens"],cash,ref_type="conversion",ref_id=str(cid),user_id=user_id); ledger(con,"TOKEN_TO_AC_CONVERSION",p["total_ac"],ac,"AC","conversion",str(cid),user_id=user_id)
        record_net_worth_snapshot(con, user_id)
        return {"ok":True,"alfa_coins":float(ac),"received":float(p["total_ac"]),"burned":float(p["tokens"]),"rate":float(p["rate"]),"message":"Alfa Coins начислены"}


@app.get("/api/v1/economy/ledger")
def ledger_api():
    user_id = current_user_id()
    with db() as con: return [dict(r) for r in con.execute("SELECT * FROM ledger_entries WHERE user_id=? ORDER BY id DESC LIMIT 50", (user_id,)).fetchall()]


@app.get("/api/v1/piggy")
def piggy():
    user_id = current_user_id()
    with db() as con:
        accrued_now = accrue_piggy_yield(con, user_id)
        p = rowdict(con.execute("SELECT * FROM piggy_accounts WHERE user_id=?", (user_id,)).fetchone()); p["cap"] = None; p["unlimited_deposit"] = True; p["daily_yield"] = float(piggy_daily_yield(d(p["balance_tkn"]), d(p["current_apr"]))); p["yield_convertible_to_ac"] = True; p["accrued_now"] = float(accrued_now)
        return p


@app.post("/api/v1/piggy/deposit")
def piggy_deposit(req: AmountRequest):
    user_id = current_user_id()
    with db() as con:
        w=wallet(con,user_id,settle_piggy=True); p=con.execute("SELECT * FROM piggy_accounts WHERE user_id=?",(user_id,)).fetchone(); amount=money(req.amount)
        if amount>d(w["token_cash"]): raise HTTPException(400,"Недостаточно TKN")
        cash=money(d(w["token_cash"])-amount); balance=money(d(p["balance_tkn"])+amount)
        con.execute("UPDATE wallets SET token_cash=? WHERE user_id=?",(str(cash),user_id)); con.execute("UPDATE piggy_accounts SET balance_tkn=? WHERE user_id=?",(str(balance),user_id)); ledger(con,"PIGGY_DEPOSIT",-amount,cash,user_id=user_id)
        return {"balance":float(balance),"cash":float(cash)}


@app.post("/api/v1/piggy/withdraw")
def piggy_withdraw(req: AmountRequest):
    user_id = current_user_id()
    with db() as con:
        w=wallet(con,user_id,settle_piggy=True); p=con.execute("SELECT * FROM piggy_accounts WHERE user_id=?",(user_id,)).fetchone(); amount=money(req.amount)
        if amount>d(p["balance_tkn"]): raise HTTPException(400,"В копилке меньше TKN")
        cash=money(d(w["token_cash"])+amount); balance=money(d(p["balance_tkn"])-amount)
        con.execute("UPDATE wallets SET token_cash=? WHERE user_id=?",(str(cash),user_id)); con.execute("UPDATE piggy_accounts SET balance_tkn=? WHERE user_id=?",(str(balance),user_id)); ledger(con,"PIGGY_WITHDRAW",amount,cash,user_id=user_id)
        return {"balance":float(balance),"cash":float(cash)}


@app.get("/api/v1/piggy/history")
def piggy_history():
    user_id = current_user_id()
    with db() as con:
        return [dict(r) for r in con.execute("SELECT * FROM ledger_entries WHERE user_id=? AND event_type LIKE 'PIGGY_%' ORDER BY id DESC", (user_id,)).fetchall()]


@app.get("/api/v1/shop/items")
def shop_items():
    with db() as con: return [dict(r) for r in con.execute("SELECT * FROM shop_items WHERE active=1 ORDER BY sort_order").fetchall()]


@app.get("/api/v1/shop/goal")
def shop_goal():
    user_id = current_user_id()
    with db() as con:
        g=con.execute("SELECT s.*,w.alfa_coins FROM user_goals g JOIN shop_items s ON s.id=g.shop_item_id JOIN wallets w ON w.user_id=g.user_id WHERE g.user_id=?",(user_id,)).fetchone()
        return dict(g) if g else None


@app.put("/api/v1/shop/goal")
def set_goal(req: GoalRequest):
    user_id = current_user_id()
    with db() as con:
        if not con.execute("SELECT 1 FROM shop_items WHERE id=? AND type='physical'",(req.shop_item_id,)).fetchone(): raise HTTPException(404,"Цель не найдена")
        con.execute("INSERT OR REPLACE INTO user_goals VALUES(?,?,?)",(user_id,req.shop_item_id,now()))
    return {"ok":True}


@app.post("/api/v1/shop/orders")
def shop_order(req: GoalRequest):
    user_id = current_user_id()
    with db() as con:
        item=con.execute("SELECT * FROM shop_items WHERE id=? AND active=1",(req.shop_item_id,)).fetchone(); w=wallet(con,user_id)
        if not item or item["stock_quantity"]<=0: raise HTTPException(400,"Товар закончился")
        if d(w["alfa_coins"])<d(item["price_ac"]): raise HTTPException(400,"Пока не хватает Alfa Coins")
        ac=money(d(w["alfa_coins"])-d(item["price_ac"])); oid=con.execute("INSERT INTO shop_orders(user_id,shop_item_id,quantity,total_ac,status,created_at) VALUES(?,?,1,?,'created',?)",(user_id,item["id"],item["price_ac"],now())).lastrowid
        con.execute("UPDATE wallets SET alfa_coins=? WHERE user_id=?",(str(ac),user_id)); con.execute("UPDATE shop_items SET stock_quantity=stock_quantity-1 WHERE id=?",(item["id"],)); ledger(con,"SHOP_PURCHASE",-d(item["price_ac"]),ac,"AC","shop_order",str(oid),user_id=user_id)
        return {"ok":True,"order_id":oid,"status":"created","message":"Заказ создан — доставка в прототипе демонстрационная"}


@app.post("/api/v1/shop/orders/cart")
def shop_cart_order(req: CartOrderRequest):
    user_id = current_user_id()
    if not req.items:
        raise HTTPException(400, "Корзина пуста")
    with db() as con:
        w = wallet(con, user_id)
        total_price = Decimal("0")
        item_details = []
        for cart_item in req.items:
            item = con.execute("SELECT * FROM shop_items WHERE id=? AND active=1", (cart_item.shop_item_id,)).fetchone()
            if not item:
                raise HTTPException(404, f"Товар #{cart_item.shop_item_id} не найден")
            if item["stock_quantity"] < cart_item.quantity:
                raise HTTPException(400, f"Товар '{item['name']}' недоступен в нужном количестве")
            item_price = d(item["price_ac"]) * cart_item.quantity
            total_price += item_price
            item_details.append((item, cart_item.quantity, item_price))

        if d(w["alfa_coins"]) < total_price:
            raise HTTPException(400, f"Не хватает Alfa Coins. Требуется: {total_price} AC")

        new_ac = money(d(w["alfa_coins"]) - total_price)
        con.execute("UPDATE wallets SET alfa_coins=? WHERE user_id=?", (str(new_ac), user_id))

        order_ids = []
        for item, qty, cost in item_details:
            oid = con.execute("INSERT INTO shop_orders(user_id,shop_item_id,quantity,total_ac,status,created_at) VALUES(?,?,?,?, 'created',?)", (user_id, item["id"], qty, str(cost), now())).lastrowid
            con.execute("UPDATE shop_items SET stock_quantity=stock_quantity-? WHERE id=?", (qty, item["id"]))
            ledger(con, "SHOP_PURCHASE", -cost, new_ac, "AC", "shop_order", str(oid), user_id=user_id)
            order_ids.append(oid)

        return {"ok": True, "order_ids": order_ids, "total_ac": float(total_price), "alfa_coins": float(new_ac), "message": "Заказ из корзины успешно оформлен!"}


@app.get("/api/v1/shop/orders")
def shop_orders():
    user_id = current_user_id()
    with db() as con:
        return [dict(r) for r in con.execute("SELECT o.*,s.name,s.image_emoji FROM shop_orders o JOIN shop_items s ON s.id=o.shop_item_id WHERE o.user_id=? ORDER BY o.id DESC", (user_id,)).fetchall()]


@app.get("/api/v1/learning/courses")
def learning():
    user_id = current_user_id()
    with db() as con:
        rows=con.execute("SELECT l.*,p.completed_at FROM lessons l LEFT JOIN lesson_progress p ON p.lesson_id=l.id AND p.user_id=? ORDER BY order_index", (user_id,)).fetchall()
        return [dict(r) for r in rows]


LESSON_ANSWERS = {
    1: [1, 0, 2], 2: [0, 2, 1], 3: [0, 1, 2], 4: [1, 0, 2], 5: [2, 0, 1], 6: [1, 2, 0],
    7: [0, 2, 1], 8: [2, 0, 1], 9: [1, 2, 0], 10: [0, 2, 1], 11: [2, 0, 1], 12: [1, 0, 2],
    13: [0, 2, 1], 14: [2, 1, 0], 15: [1, 0, 2], 16: [0, 2, 1], 17: [2, 1, 0], 18: [1, 0, 2],
}


def advance_quest_ids(con: sqlite3.Connection, quest_ids: list[int], user_id: int | None = None) -> None:
    user_id = current_user_id() if user_id is None else user_id
    keys = ensure_current_quests(con, user_id)
    for quest_id in quest_ids:
        quest = con.execute(
            "SELECT q.target,q.type,u.progress,u.completed FROM quests q JOIN user_quests u ON u.quest_id=q.id "
            "WHERE q.id=? AND u.user_id=? AND u.period_key=CASE q.type WHEN 'daily' THEN ? ELSE ? END",
            (quest_id, user_id, keys["daily"], keys["weekly"]),
        ).fetchone()
        if quest and not quest["completed"]:
            progress = min(quest["target"], quest["progress"] + 1)
            con.execute(
                "UPDATE user_quests SET progress=?,completed=? WHERE user_id=? AND quest_id=? AND period_key=?",
                (progress, int(progress >= quest["target"]), user_id, quest_id, keys[quest["type"]]),
            )


@app.post("/api/v1/learning/lessons/{lesson_id}/complete")
def complete_lesson(lesson_id: int, req: LessonCompleteRequest):
    user_id = current_user_id()
    with db() as con:
        lesson = con.execute("SELECT * FROM lessons WHERE id=?", (lesson_id,)).fetchone()
        if not lesson:
            raise HTTPException(404, "Урок не найден")
        expected = LESSON_ANSWERS.get(lesson_id, [0])
        submitted = req.answers if req.answers is not None else ([req.answer_index] if req.answer_index is not None else [])
        # The legacy one-answer form is intentionally accepted only for old
        # clients and tests; the current interface always sends the full test.
        is_legacy_correct = req.answers is None and submitted == expected[:1]
        if submitted != expected and not is_legacy_correct:
            raise HTTPException(400, "Не все ответы верны — проверь вопросы и попробуй ещё раз")
        if con.execute("SELECT 1 FROM lesson_progress WHERE user_id=? AND lesson_id=?", (user_id, lesson_id)).fetchone():
            return {"ok": True, "already_completed": True, "xp": 0, "boost": 0}
        con.execute("INSERT INTO lesson_progress VALUES(?,?,?)", (user_id, lesson_id, now()))
        con.execute("UPDATE users SET xp=xp+? WHERE id=?", (lesson["xp_reward"], user_id))
        con.execute("UPDATE wallets SET pending_activity_boost=CAST(pending_activity_boost AS REAL)+? WHERE user_id=?", (lesson["boost_reward"], user_id))
        advance_quest_ids(con, [2, 4], user_id)
        return {"ok": True, "already_completed": False, "xp": lesson["xp_reward"], "boost": lesson["boost_reward"]}


@app.post("/api/v1/learning/assistant")
async def learning_assistant(req: LessonAssistantRequest):
    question = req.question.strip()
    if len(question) < 2:
        raise HTTPException(422, "Напиши вопрос чуть подробнее")
    with db() as con:
        lesson = rowdict(con.execute("SELECT id,course,title,description FROM lessons WHERE id=?", (req.lesson_id,)).fetchone())
    if not lesson:
        raise HTTPException(404, "Урок не найден")
    coach = GeminiCoach()
    try:
        return await coach.ask_lesson(lesson, question)
    finally:
        await coach.close()


@app.get("/api/v1/learning/progress")
def learning_progress():
    user_id = current_user_id()
    with db() as con:
        completed = con.execute("SELECT COUNT(*) FROM lesson_progress WHERE user_id=?", (user_id,)).fetchone()[0]
        total = con.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]
        return {"completed": completed, "total": total, "progress": completed / total if total else 0}


@app.get("/api/v1/quests/daily")
@app.get("/api/v1/quests/weekly")
def quests():
    user_id = current_user_id()
    with db() as con:
        keys = ensure_current_quests(con, user_id)
        return [dict(row) for row in con.execute(
            "SELECT q.*,u.progress,u.completed,u.claimed,u.period_key FROM quests q JOIN user_quests u ON u.quest_id=q.id "
            "WHERE u.user_id=? AND u.period_key=CASE q.type WHEN 'daily' THEN ? ELSE ? END ORDER BY q.id",
            (user_id, keys["daily"], keys["weekly"]),
        ).fetchall()]


@app.post("/api/v1/quests/{quest_id}/claim")
def claim_quest(quest_id:int):
    user_id = current_user_id()
    with db() as con:
        keys = ensure_current_quests(con, user_id)
        q=con.execute("SELECT q.*,u.progress,u.claimed,u.period_key FROM quests q JOIN user_quests u ON u.quest_id=q.id WHERE q.id=? AND u.user_id=? AND u.period_key=CASE q.type WHEN 'daily' THEN ? ELSE ? END",(quest_id,user_id,keys["daily"],keys["weekly"])).fetchone()
        if not q or q["progress"]<q["target"]: raise HTTPException(400,"Задание ещё не выполнено")
        if q["claimed"]: raise HTTPException(409,"Награда уже получена")
        con.execute("UPDATE user_quests SET claimed=1,completed=1 WHERE user_id=? AND quest_id=? AND period_key=?",(user_id,quest_id,q["period_key"])); con.execute("UPDATE users SET xp=xp+? WHERE id=?",(q["xp_reward"],user_id)); con.execute("UPDATE wallets SET pending_activity_boost=CAST(pending_activity_boost AS REAL)+? WHERE user_id=?",(q["boost_reward"],user_id))
        return {"ok":True,"xp":q["xp_reward"],"boost":q["boost_reward"]}


@app.post("/api/v1/quests/progress")
def quest_progress(req: QuestProgressRequest):
    action_map = {
        "company_view": [1],
        "lesson_complete": [2, 4],
        "portfolio_view": [3],
        "sector_collect": [5],
    }
    target_quest_ids = action_map.get(req.quest_action, [])
    if not target_quest_ids:
        return {"updated": False}
    user_id = current_user_id()
    with db() as con:
        advance_quest_ids(con, target_quest_ids, user_id)
    return {"ok": True, "updated": True}


def achievement_items(con: sqlite3.Connection, user_id: int | None = None) -> list[dict[str, Any]]:
    user_id = current_user_id() if user_id is None else user_id
    state = con.execute("SELECT reset_at FROM gamification_state WHERE user_id=?", (user_id,)).fetchone()
    reset_at = state["reset_at"] if state and state["reset_at"] else ""
    trade_count = con.execute("SELECT COUNT(*) FROM trades WHERE user_id=? AND executed_at>=?", (user_id, reset_at)).fetchone()[0]
    lesson_count = con.execute("SELECT COUNT(*) FROM lesson_progress WHERE user_id=? AND completed_at>=?", (user_id, reset_at)).fetchone()[0]
    position_count = con.execute("SELECT COUNT(*) FROM positions WHERE user_id=? AND updated_at>=?", (user_id, reset_at)).fetchone()[0]
    streak = update_user_streak(con, user_id)
    claimed_ids = {row[0] for row in con.execute("SELECT achievement_id FROM user_achievements WHERE user_id=?", (user_id,)).fetchall()}
    return [
        {"id": 1, "title": "Первая покупка", "icon": "📈", "unlocked": trade_count > 0, "progress": min(1, trade_count), "target": 1, "claimed": 1 in claimed_ids},
        {"id": 2, "title": "10 сделок", "icon": "⚡", "unlocked": trade_count >= 10, "progress": min(10, trade_count), "target": 10, "claimed": 2 in claimed_ids},
        {"id": 3, "title": "Первый урок", "icon": "📚", "unlocked": lesson_count > 0, "progress": min(1, lesson_count), "target": 1, "claimed": 3 in claimed_ids},
        {"id": 4, "title": "Три актива", "icon": "🧩", "unlocked": position_count >= 3, "progress": min(3, position_count), "target": 3, "claimed": 4 in claimed_ids},
        {"id": 5, "title": "Неделя в ритме", "icon": "🔥", "unlocked": streak >= 7, "progress": min(7, streak), "target": 7, "claimed": 5 in claimed_ids},
    ]


@app.get("/api/v1/achievements")
def achievements():
    user_id = current_user_id()
    with db() as con:
        return achievement_items(con, user_id)


@app.post("/api/v1/achievements/{achievement_id}/claim")
def achievement_claim(achievement_id: int):
    user_id = current_user_id()
    with db() as con:
        if con.execute("SELECT 1 FROM user_achievements WHERE user_id=? AND achievement_id=?", (user_id, achievement_id)).fetchone():
            raise HTTPException(400, "Награда за достижение уже получена")
        all_ach = achievement_items(con, user_id)
        item = next((a for a in all_ach if a["id"] == achievement_id and a["unlocked"]), None)
        if not item:
            raise HTTPException(400, "Достижение ещё не открыто")
        con.execute("INSERT INTO user_achievements VALUES(?,?,?)", (user_id, achievement_id, now()))
        con.execute("UPDATE users SET xp=xp+100 WHERE id=?", (user_id,))
    return {"ok": True, "xp": 100, "message": f"Достижение '{item['title']}' зачислено! +100 XP"}


@app.get("/api/v1/coach/monthly-report")
async def monthly_coach_report(month: str | None = None, refresh: bool = False):
    user_id = current_user_id()
    selected_month = month or local_date().strftime("%Y-%m")
    month_bounds(selected_month)
    current_month = local_date().strftime("%Y-%m")
    if selected_month > current_month:
        raise HTTPException(400, "Нельзя построить отчёт за будущий месяц")
    period_status = "final" if selected_month < current_month else "in_progress"

    with db() as con:
        facts = build_monthly_facts(con, selected_month, user_id)
        facts["period_status"] = period_status
        facts["as_of_date"] = local_date().isoformat()
        input_hash = hashlib.sha256(json.dumps(facts, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        cached = con.execute(
            "SELECT input_hash,payload_json FROM monthly_ai_reports WHERE user_id=? AND month=?",
            (user_id, selected_month),
        ).fetchone()
        if cached and cached["input_hash"] == input_hash and not refresh:
            return json.loads(cached["payload_json"])

    coach = GeminiCoach()
    try:
        analysis = await coach.analyze_month(facts)
    finally:
        await coach.close()
    payload = {
        "month": selected_month,
        "status": period_status,
        "generated_at": now(),
        "metrics": facts["metrics"],
        "decisions": facts["decisions"],
        "analysis": analysis,
        "disclaimer": "Разбор основан только на действиях в симуляторе. Это учебная обратная связь, а не совет покупать или продавать.",
    }
    with db() as con:
        con.execute(
            "INSERT INTO monthly_ai_reports(user_id,month,input_hash,payload_json,generated_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(user_id,month) DO UPDATE SET input_hash=excluded.input_hash,payload_json=excluded.payload_json,generated_at=excluded.generated_at",
            (user_id, selected_month, input_hash, json.dumps(payload, ensure_ascii=False), payload["generated_at"]),
        )
    return payload


def tin_cooldown_state(con: sqlite3.Connection, user_id: int, at: datetime | None = None) -> dict[str, Any]:
    current = at or datetime.now(timezone.utc)
    rows = {
        row["action"]: row["last_interaction_at"]
        for row in con.execute(
            "SELECT action,last_interaction_at FROM tamagotchi_interactions WHERE user_id=?",
            (user_id,),
        ).fetchall()
    }
    cooldowns: dict[str, int] = {}
    ends_at: dict[str, str | None] = {}
    for action, config in TIN_INTERACTIONS.items():
        raw_timestamp = rows.get(action)
        if not raw_timestamp:
            cooldowns[action] = 0
            ends_at[action] = None
            continue
        try:
            last_interaction = datetime.fromisoformat(raw_timestamp)
            if last_interaction.tzinfo is None:
                last_interaction = last_interaction.replace(tzinfo=timezone.utc)
            else:
                last_interaction = last_interaction.astimezone(timezone.utc)
        except (TypeError, ValueError):
            cooldowns[action] = 0
            ends_at[action] = None
            continue
        cooldown = int(config["cooldown"])
        remaining = max(0, math.ceil(cooldown - (current - last_interaction).total_seconds()))
        cooldowns[action] = remaining
        ends_at[action] = (last_interaction + timedelta(seconds=cooldown)).isoformat() if remaining else None
    return {"cooldowns": cooldowns, "cooldown_ends_at": ends_at, "server_time": current.isoformat()}


@app.get("/api/v1/tamagotchi")
def tin():
    user_id = current_user_id()
    with db() as con:
        pet = rowdict(con.execute("SELECT * FROM tamagotchi WHERE user_id=?", (user_id,)).fetchone())
        items = [dict(r) for r in con.execute("SELECT i.*, u.acquired_at FROM tamagotchi_items i LEFT JOIN user_tamagotchi_items u ON u.item_id=i.id AND u.user_id=? WHERE i.active=1", (user_id,)).fetchall()]
        pet["items"] = items
        pet.update(tin_cooldown_state(con, user_id))
        return pet


@app.get("/api/v1/tamagotchi/tasks")
def tin_tasks():
    with db() as con:
        insts = con.execute("SELECT ticker, change_pct FROM instruments WHERE enabled=1 ORDER BY ABS(CAST(change_pct AS REAL)) DESC LIMIT 2").fetchall()
        top_ticker = insts[0]["ticker"] if insts else "SBER"
        return [
            {"id": 1, "title": f"Изучи лидеров рынка ({top_ticker})", "reward": "+45 XP"},
            {"id": 2, "title": "Соверши 1 сделку в инвест-счёте", "reward": "+35 boost"}
        ]


@app.get("/api/v1/tamagotchi/shop")
def tin_shop():
    return tin()["items"]


def equip_tamagotchi_item(con: sqlite3.Connection, item_id: int, *, toggle: bool = True, user_id: int | None = None) -> tuple[list[int], bool]:
    user_id = current_user_id() if user_id is None else user_id
    item = con.execute("SELECT id,slot FROM tamagotchi_items WHERE id=? AND active=1", (item_id,)).fetchone()
    if not item:
        raise HTTPException(404, "Предмет не найден")
    if not con.execute("SELECT 1 FROM user_tamagotchi_items WHERE user_id=? AND item_id=?", (user_id, item_id)).fetchone():
        raise HTTPException(400, "Сначала купи предмет")

    pet = con.execute("SELECT equipped_items_json FROM tamagotchi WHERE user_id=?", (user_id,)).fetchone()
    try:
        stored_ids = [int(value) for value in json.loads(pet["equipped_items_json"] or "[]")]
    except (TypeError, ValueError, json.JSONDecodeError):
        stored_ids = []

    equipped_rows = con.execute(
        f"SELECT id,slot FROM tamagotchi_items WHERE id IN ({','.join('?' for _ in stored_ids)}) AND active=1" if stored_ids else
        "SELECT id,slot FROM tamagotchi_items WHERE 0",
        stored_ids,
    ).fetchall()
    equipped_by_slot = {row["slot"]: row["id"] for row in equipped_rows}
    was_equipped = equipped_by_slot.get(item["slot"]) == item_id
    if toggle and was_equipped:
        equipped_by_slot.pop(item["slot"], None)
    else:
        equipped_by_slot[item["slot"]] = item_id

    equipped_ids = list(equipped_by_slot.values())
    con.execute(
        "UPDATE tamagotchi SET equipped_items_json=?,last_interaction_at=? WHERE user_id=?",
        (json.dumps(equipped_ids), now(), user_id),
    )
    return equipped_ids, not (toggle and was_equipped)


@app.post("/api/v1/tamagotchi/equip/{item_id}")
def tin_equip(item_id: int):
    user_id = current_user_id()
    with db() as con:
        equipped_items, equipped = equip_tamagotchi_item(con, item_id, user_id=user_id)
    return {"ok": True, "item_id": item_id, "equipped": equipped, "equipped_items": equipped_items}


@app.post("/api/v1/tamagotchi/interact")
def tin_interact(req:TinInteractRequest):
    user_id = current_user_id()
    interaction = TIN_INTERACTIONS.get(req.action)
    if not interaction:
        raise HTTPException(422, "Неизвестное действие с Тином")
    current = datetime.now(timezone.utc)
    with db() as con:
        # Take the write lock before reading the timer so simultaneous requests
        # cannot both pass the same cooldown.
        con.execute("BEGIN IMMEDIATE")
        remaining = tin_cooldown_state(con, user_id, current)["cooldowns"][req.action]
        if remaining > 0:
            raise HTTPException(429, f"Подожди {remaining} сек. перед повторным действием")
        con.execute(
            "INSERT INTO tamagotchi_interactions(user_id,action,last_interaction_at) VALUES(?,?,?) "
            "ON CONFLICT(user_id,action) DO UPDATE SET last_interaction_at=excluded.last_interaction_at",
            (user_id, req.action, current.isoformat()),
        )
        con.execute(
            "UPDATE tamagotchi SET mood=MIN(100,mood+?),energy=MAX(0,MIN(100,energy+?)),friendship=MIN(100,friendship+?),last_interaction_at=? WHERE user_id=?",
            (interaction["mood"], interaction["energy"], interaction["friendship"], current.isoformat(), user_id),
        )
        pet=dict(con.execute("SELECT * FROM tamagotchi WHERE user_id=?",(user_id,)).fetchone())
        pet.update(tin_cooldown_state(con, user_id, current))
    return {"pet": pet, "message": interaction["message"]}


@app.post("/api/v1/tamagotchi/shop/{item_id}/buy")
def tin_buy(item_id:int):
    user_id = current_user_id()
    with db() as con:
        item=con.execute("SELECT * FROM tamagotchi_items WHERE id=? AND active=1",(item_id,)).fetchone(); w=wallet(con,user_id)
        if not item: raise HTTPException(404,"Предмет не найден")
        if con.execute("SELECT 1 FROM user_tamagotchi_items WHERE user_id=? AND item_id=?", (user_id,item_id)).fetchone(): raise HTTPException(400,"Предмет уже куплен")
        if d(w["alfa_coins"])<d(item["price_ac"]): raise HTTPException(400,"Не хватает Alfa Coins")
        ac=money(d(w["alfa_coins"])-d(item["price_ac"])); con.execute("INSERT OR IGNORE INTO user_tamagotchi_items VALUES(?,?,?)",(user_id,item_id,now())); con.execute("UPDATE wallets SET alfa_coins=? WHERE user_id=?",(str(ac),user_id)); ledger(con,"TAMAGOTCHI_PURCHASE",-d(item["price_ac"]),ac,"AC","tamagotchi_item",str(item_id),user_id=user_id)
        equipped_items, _ = equip_tamagotchi_item(con, item_id, toggle=False, user_id=user_id)
        return {"ok":True,"alfa_coins":float(ac),"equipped_items":equipped_items}


@app.get("/api/v1/contest")
def contest():
    user_id = current_user_id()
    with db() as con:
        profile=rowdict(con.execute("SELECT * FROM contest_profiles WHERE user_id=?",(user_id,)).fetchone()); wallet_ct=con.execute("SELECT contest_tokens FROM contest_wallets WHERE user_id=?",(user_id,)).fetchone()[0]
        return {"profile":profile,"contest_tokens":float(wallet_ct),"leaderboard":[{"name":"Мира","return":18.4},{"name":"Лев","return":15.7},{"name":"Ты","return":0.0}]}


@app.post("/api/v1/contest/apply")
def contest_apply(req:ContestRequest):
    user_id = current_user_id()
    if not req.consent: raise HTTPException(400,"Нужно согласие на демо-проверку")
    status="verified_mock" if req.ege_score>=int(os.getenv("CONTEST_MIN_EGE_SCORE","70")) else "rejected_mock"
    with db() as con:
        con.execute("INSERT OR REPLACE INTO contest_profiles VALUES(?,?,?,?,?,?,?,?)",(user_id,status,req.full_name,req.ege_year,req.ege_subject,req.ege_score,req.certificate_mock,now()))
        if status=="verified_mock":
            current=d(con.execute("SELECT contest_tokens FROM contest_wallets WHERE user_id=?",(user_id,)).fetchone()[0])
            if current==0: con.execute("UPDATE contest_wallets SET contest_tokens='1000' WHERE user_id=?",(user_id,)); ledger(con,"CONTEST_GRANT",d(1000),d(1000),"CT","contest",str(user_id),user_id=user_id)
    return {"status":status,"contest_tokens":1000 if status=="verified_mock" else 0}


@app.get("/api/v1/referrals/share")
def referral_share():
    user_id = current_user_id()
    with db() as con:
        code = con.execute("SELECT referral_code FROM users WHERE id=?", (user_id,)).fetchone()[0]
    return {"code":code,"link":f"https://alfa.tin/invite/{code}","reward_referrer":100,"reward_friend":50,"remaining_rewarded_invites":3}


@app.get("/api/v1/referrals")
def referrals():
    user_id = current_user_id()
    with db() as con:
        code = con.execute("SELECT referral_code FROM users WHERE id=?", (user_id,)).fetchone()[0]
    return {"completed": 0, "rewarded_30d": 0, "limit_30d": 3, "code": code}


@app.get("/api/v1/contest/wallet")
def contest_wallet():
    return {"contest_tokens": contest()["contest_tokens"], "isolated": True}


@app.get("/api/v1/contest/leaderboard")
def contest_leaderboard():
    return contest()["leaderboard"]


@app.get("/api/v1/admin/config")
def admin_config():
    require_admin()
    with db() as con:
        return {r["key"]: json.loads(r["value_json"]) for r in con.execute("SELECT * FROM app_config ORDER BY key").fetchall()}


@app.put("/api/v1/admin/config/{key}")
def update_admin_config(key: str, value: Any):
    require_admin()
    with db() as con:
        if not con.execute("SELECT 1 FROM app_config WHERE key=?", (key,)).fetchone(): raise HTTPException(404, "Настройка не найдена")
        con.execute("UPDATE app_config SET value_json=?,updated_at=? WHERE key=?", (json.dumps(value), now(), key))
    return {"ok": True, "key": key, "value": value}


@app.post("/api/v1/dev/scenario/profitable-month")
def profitable_month():
    if os.getenv("APP_ENV","development")=="production": raise HTTPException(404)
    user_id = current_user_id()
    with db() as con:
        w=wallet(con,user_id); cash=money(d(w["token_cash"])+d(180)); eligible=money(d(w["eligible_profit_tokens"])+d(180)); con.execute("UPDATE wallets SET token_cash=?,eligible_profit_tokens=?,pending_activity_boost='2500' WHERE user_id=?",(str(cash),str(eligible),user_id)); ledger(con,"REALIZED_PROFIT",d(180),cash,ref_type="dev_scenario",ref_id="profitable-month",user_id=user_id)
    return {"ok":True,"message":"Демо-сценарий прибыльного месяца применён"}


class FinamTradeApiProvider:
    """Server-side Finam market-data adapter; secrets and JWT never reach clients."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.base = os.getenv("FINAM_REST_BASE_URL", "https://api.finam.ru").rstrip("/")
        self.secret = os.getenv("FINAM_API_SECRET", "").strip()
        self.jwt_token: str | None = None
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0))
        self._owns_client = client is None
        self._auth_lock = asyncio.Lock()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def refresh_session(self) -> str:
        if not self.secret:
            raise RuntimeError("FINAM_API_SECRET is not configured")
        async with self._auth_lock:
            response = await self._client.post(f"{self.base}/v1/sessions", json={"secret": self.secret})
            response.raise_for_status()
            data = response.json()
            self.jwt_token = data.get("token") or data.get("jwt")
            if not self.jwt_token:
                raise RuntimeError("Finam session response has no JWT")
            return self.jwt_token

    async def get_quote(self, symbol: str) -> dict[str, Any]:
        token = self.jwt_token or await self.refresh_session()
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = await self._client.get(
                    f"{self.base}/v1/instruments/{symbol}/quotes/latest",
                    headers={"Authorization": f"Bearer {token}"},
                )
                if response.status_code == 401:
                    self.jwt_token = None
                    token = await self.refresh_session()
                    response = await self._client.get(
                        f"{self.base}/v1/instruments/{symbol}/quotes/latest",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                    await asyncio.sleep(0.25 * (attempt + 1))
                    continue
                response.raise_for_status()
                return response.json()
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if attempt == 2:
                    raise
                await asyncio.sleep(0.25 * (attempt + 1))
        raise RuntimeError(f"Finam quote request failed for {symbol}") from last_error


async def sync_finam_snapshot(provider: FinamTradeApiProvider | None = None) -> int:
    """Refresh the curated universe from Finam, preserving seeded rows as fallback."""
    owns_provider = provider is None
    provider = provider or FinamTradeApiProvider()
    MARKET_DATA_STATE["last_attempt_at"] = now()
    errors: list[str] = []
    try:
        if not provider.jwt_token:
            await provider.refresh_session()
        with db() as con:
            universe = [(r["id"], r["symbol"]) for r in con.execute("SELECT id,symbol FROM instruments WHERE enabled=1").fetchall()]
        semaphore = asyncio.Semaphore(5)

        async def fetch(item: tuple[int, str]):
            instrument_id, symbol = item
            async with semaphore:
                try:
                    payload = await provider.get_quote(symbol)
                    quote = payload.get("quote", payload)
                    last_value = quote.get("last", {}).get("value") or quote.get("close", {}).get("value")
                    if not last_value:
                        raise ValueError("quote has neither last nor close value")
                    last = d(last_value)
                    previous = d(quote.get("close", {}).get("value") or last)
                    stamp = quote.get("timestamp") or now()
                    change = money((last - previous) / previous * d(100)) if previous else d(0)
                    return instrument_id, last, previous, change, stamp
                except Exception as exc:
                    errors.append(f"{symbol}: {type(exc).__name__}")
                    return None

        updates = [item for item in await asyncio.gather(*(fetch(item) for item in universe)) if item]
        if updates:
            with db() as con:
                for instrument_id, last, previous, change, stamp in updates:
                    con.execute(
                        "UPDATE instruments SET real_price_rub=?,previous_close=?,change_pct=?,source='finam',source_timestamp=? WHERE id=?",
                        (str(last), str(previous), str(change), stamp, instrument_id),
                    )
            MARKET_DATA_STATE["last_success_at"] = now()
            MARKET_DATA_STATE["updated_instruments"] = len(updates)
        MARKET_DATA_STATE["last_error"] = "; ".join(errors[:3]) if errors else None
        if errors:
            LOGGER.warning("Finam quote sync completed with %d errors: %s", len(errors), "; ".join(errors[:3]))
        return len(updates)
    except Exception as exc:
        MARKET_DATA_STATE["last_error"] = f"{type(exc).__name__}: {exc}".rstrip(": ")
        raise
    finally:
        if owns_provider:
            await provider.close()


async def finam_sync_loop(provider: FinamTradeApiProvider) -> None:
    while True:
        try:
            await sync_finam_snapshot(provider)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOGGER.warning("Finam quote refresh failed: %s: %s", type(exc).__name__, exc)
            # A configured but temporarily unavailable provider must not freeze
            # the educational market. The next successful Finam refresh will
            # replace these simulated values automatically.
            try:
                sync_demo_market_snapshot()
            except Exception as fallback_exc:
                LOGGER.warning("Demo fallback refresh failed: %s: %s", type(fallback_exc).__name__, fallback_exc)
        await asyncio.sleep(MARKET_REFRESH_SECONDS)


DEMO_MARKET_OFFSETS = (d("-0.18"), d("-0.10"), d("-0.02"), d("0.07"), d("0.16"), d("0.09"), d("0.01"), d("-0.09"))


def sync_demo_market_snapshot(tick: int | None = None) -> int:
    """Advance fallback quotes through a bounded deterministic market cycle."""
    current_tick = tick if tick is not None else int(datetime.now(timezone.utc).timestamp() // MARKET_REFRESH_SECONDS)
    stamp = now()
    with db() as con:
        rows = con.execute(
            "SELECT id,real_price_rub,previous_close FROM instruments WHERE enabled=1 ORDER BY id"
        ).fetchall()
        for row in rows:
            anchor = d(row["previous_close"] or row["real_price_rub"])
            offset = DEMO_MARKET_OFFSETS[(current_tick + row["id"] * 3) % len(DEMO_MARKET_OFFSETS)]
            simulated = (anchor * (d(1) + offset / d(100))).quantize(d("0.0001"))
            con.execute(
                "UPDATE instruments SET real_price_rub=?,change_pct=?,source='demo-simulated',source_timestamp=? WHERE id=?",
                (str(simulated), str(offset), stamp, row["id"]),
            )
    MARKET_DATA_STATE["last_attempt_at"] = stamp
    MARKET_DATA_STATE["last_success_at"] = stamp
    MARKET_DATA_STATE["last_error"] = None
    MARKET_DATA_STATE["updated_instruments"] = len(rows)
    return len(rows)


async def demo_market_loop() -> None:
    # Keep opening quotes stable long enough for the first screen to render,
    # then move them at the same cadence as live market refreshes.
    while True:
        await asyncio.sleep(MARKET_REFRESH_SECONDS)
        try:
            sync_demo_market_snapshot()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            MARKET_DATA_STATE["last_error"] = f"{type(exc).__name__}: {exc}".rstrip(": ")
            LOGGER.warning("Demo quote refresh failed: %s: %s", type(exc).__name__, exc)


@app.websocket("/ws/market")
async def market_socket(ws:WebSocket):
    await ws.accept()
    try:
        while True:
            with db() as con:
                quotes=[serialize_instrument(r) for r in con.execute("SELECT * FROM instruments WHERE featured=1 LIMIT 8").fetchall()]
            await ws.send_json({"type":"quotes","data":quotes,"timestamp":now()}); await asyncio.sleep(5)
    except WebSocketDisconnect:
        return
