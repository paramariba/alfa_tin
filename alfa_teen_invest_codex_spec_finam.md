# Техническое задание: Alfa Teen Invest Game
## Полнофункциональное PWA-веб-приложение для подростков 14–18 лет

**Версия:** 1.0  
**Дата:** 19.08.2026  
**Назначение:** implementation-ready ТЗ для Codex  
**Формат продукта:** отдельное mobile-first PWA-веб-приложение, визуально совместимое с актуальной айдентикой Альфа-Банка и потенциально открываемое из основного приложения Альфа-Банка через deep link / WebView.

---

# 0. Главная инструкция для Codex

Нужно реализовать **реально работающее приложение**, а не набор статичных экранов.

Codex должен:

1. создать frontend, backend, SQLite-БД, Redis-интеграцию, PWA, API и игровую экономику;
2. интегрировать backend с Finam Trade API как основным real-time market-data provider для инструментов Московской биржи;
3. реализовать fallback на Redis/SQLite/seed-данные, если Finam Trade API временно недоступен;
4. реализовать регистрацию, onboarding, портфель, акции, фонды, Инвесткопилку, торговлю, конвертацию, магазин, цели, обучение, streak, quests, achievements, Tamagotchi, referrals и Contest;
5. сделать все основные CTA функциональными;
6. покрыть критическую экономику и торговый engine тестами;
7. сделать интерфейс mobile-first, но полноценным на desktop;
8. сделать приложение устанавливаемым как PWA на iOS, Android и desktop;
9. вынести ключевые параметры экономики в конфигурацию;
10. после появления визуального референса Альфа-Банка адаптировать design tokens, spacing, typography, cards и navigation под него.

Не строить копию всего банковского приложения. Это отдельный teen-invest experience внутри экосистемы Альфа-Банка.

---

# 1. Идея продукта

Alfa Teen Invest Game — безопасный инвестиционный симулятор для подростков 14–18 лет.

Пользователь получает **1 000 игровых токенов** и распоряжается ими через три инвестиционных сценария:

- акции российских компаний;
- реальные биржевые фонды / БПИФ Московской биржи;
- игровая «Инвесткопилка».

Рыночное поведение акций и фондов привязано к реальным котировкам Московской биржи, получаемым через Finam Trade API. Игровой финансовый результат ускорен, чтобы эффект решений был заметен за недели, а не годы.

Основной loop:

```text
получил TKN
→ инвестировал
→ рынок изменился
→ получил прибыль или убыток
→ зафиксировал прибыль продажей
→ конвертировал часть заработанной прибыли в Alfa Coins
→ приблизился к цели
→ купил merch
```

Retention loop:

```text
рынок + личная merch-цель + streak + learning + quests + Tamagotchi
```

---

# 2. Принципы и ограничения

В приложении нет:

- реальных денег;
- пополнения за рубли;
- вывода в рубли;
- настоящего брокерского счёта;
- реальной покупки ценных бумаг;
- P2P-переводов токенов;
- шортов;
- кредитного плеча;
- платных loot boxes;
- случайных материальных выигрышей.

Это игровой симулятор. Все финансовые действия выполняются только с виртуальными единицами.

Экономика не должна позволять:

- обменять стартовые 1 000 TKN напрямую на merch;
- получить худи за один случайный рыночный скачок;
- фармить merch простым ежедневным входом;
- положить всё в пассивный инструмент и бесконечно получать награды;
- использовать Contest Tokens в обычной экономике.

---

# 3. Валюты

## 3.1. Tokens — TKN

Основная игровая инвестиционная валюта.

Используется для:

- покупки акций;
- покупки фондов;
- Инвесткопилки;
- свободного cash balance.

Старт:

```text
STARTING_TOKENS = 1000
```

TKN нельзя купить за реальные деньги.

## 3.2. Alfa Coins — AC

Reward-валюта магазина.

Используется для:

- физического merch;
- digital cosmetics для Tamagotchi;
- purely cosmetic игровых предметов.

Основной способ получения:

```text
положительная реализованная торговая прибыль TKN
→ eligible profit
→ conversion
→ AC
```

Стартовый капитал, referral grants и обычные token-grants напрямую в AC не конвертируются.

## 3.3. Contest Tokens — CT

Полностью отдельная валюта Contest.

CT:

- живут в отдельном wallet;
- не смешиваются с TKN;
- не конвертируются в AC;
- не используются в Shop;
- предназначены для будущих соревнований.

---

# 4. Стартовая экономика

После onboarding:

```text
1000 TKN
0 AC
0 CT
```

## Цены физического магазина

| Товар | Цена |
|---|---:|
| Sticker Pack Alfa | 3 500 AC |
| Кружка Alfa | 6 500 AC |
| Футболка Alfa | 9 500 AC |
| Худи Alfa | 12 500 AC |

Худи — самый дорогой и самый желанный physical reward.

Все цены хранятся в БД и доступны для изменения через admin/config.

---

# 5. Finam Trade API — основной real-time market-data provider

Для MVP и демонстрации использовать **Finam Trade API** как основной источник котировок российских акций и фондов Московской биржи.

Официальные источники:

- https://api.finam.ru/
- https://api.finam.ru/getting-started/
- https://api.finam.ru/docs/rest/
- https://api.finam.ru/docs/async-api/

Finam Trade API предоставляет:

- real-time market data по отдельным инструментам;
- последнюю котировку;
- последние сделки;
- исторические свечи;
- стакан;
- список доступных инструментов;
- REST;
- WebSocket;
- gRPC.

Для этого проекта использовать:

```text
REST:      https://api.finam.ru
WebSocket: wss://api.finam.ru/ws
```

Основной symbol format Finam:

```text
ticker@MIC
```

Пример:

```text
SBER@MISX
YDEX@MISX
```

> Важно: фактические symbol/MIC каждого инструмента всегда получать/проверять через Assets API, а не предполагать вручную.

## 5.1. Авторизация Finam

Выданный на портале Finam ключ вида:

```text
tapi_sk_...
```

является **secret token**.

Его нельзя отправлять во frontend, хранить в git, hardcode-ить в исходниках или записывать в Markdown/README.

Secret должен попадать в backend только через environment variable / secret storage:

```env
FINAM_API_SECRET=<local-secret>
```

Backend должен обменивать secret на короткоживущий JWT:

```http
POST https://api.finam.ru/v1/sessions
Content-Type: application/json

{
  "secret": "<FINAM_API_SECRET>"
}
```

Полученный JWT используется в REST-запросах:

```http
Authorization: <JWT>
```

и для WebSocket-аутентификации.

По текущей документации Finam JWT живёт около **15 минут**. Поэтому реализовать `FinamAuthManager`:

1. при первом market-data request получить JWT;
2. хранить JWT только server-side;
3. кэшировать JWT в Redis с TTL немного меньше фактического срока жизни;
4. обновлять JWT заранее, например за 60–120 секунд до expiration;
5. при `401` выполнить один controlled refresh + retry;
6. не логировать secret или полный JWT;
7. использовать lock, чтобы несколько workers одновременно не создавали десятки JWT.

Пример Redis keys:

```text
finam:auth:jwt
finam:auth:refresh_lock
```

## 5.2. REST endpoints, нужные MVP

Минимально использовать:

```text
POST /v1/sessions
GET  /v1/assets
GET  /v1/assets/all
GET  /v1/assets/{symbol}
GET  /v1/assets/{symbol}/schedule
GET  /v1/instruments/{symbol}/quotes/latest
GET  /v1/instruments/{symbol}/trades/latest
```

Для candles использовать официальный Bars endpoint из актуальной Finam OpenAPI-документации; не придумывать path вручную — сгенерировать/сверить client по текущей OpenAPI schema.

В приложении **не использовать Finam для реального исполнения сделок**. Finam — только market-data provider. Все пользовательские buy/sell происходят исключительно внутри нашего игрового Trading Engine.

## 5.3. WebSocket real-time

Backend открывает server-side соединение:

```text
wss://api.finam.ru/ws
```

и подписывается минимум на `QUOTES` для активного curated universe.

Finam WebSocket поддерживает subscription types для:

- quotes;
- trades;
- order book;
- bars;
- orders.

Для MVP достаточно:

```text
QUOTES
```

Candles можно получать REST и кэшировать.

Backend нормализует сообщения Finam в собственную доменную модель `QuoteUpdate`, кладёт последние значения в Redis и уже **своим** `/ws/market` раздаёт обновления клиентам.

Архитектура:

```text
Finam WebSocket
      ↓
FinamTradeApiProvider
      ↓
Redis quote cache
      ↓
FastAPI /ws/market
      ↓
React PWA
```

Никогда не проксировать Finam JWT пользователю.

## 5.4. Ограничения и reconnect

По текущей документации Finam:

- лимит REST — до 200 запросов в минуту на конкретный метод;
- WebSocket-соединение может принудительно разрываться примерно через 24 часа;
- есть ежедневное сервисное окно около 05:00–06:15 по московскому времени.

Поэтому:

- не polling-ить LastQuote отдельно для каждого пользователя;
- поддерживать один/few backend market streams;
- кэшировать quotes централизованно;
- при WebSocket disconnect делать exponential backoff;
- после reconnect автоматически восстанавливать подписки;
- во время сервисного окна использовать last-known data и `stale/delayed` badge;
- REST использовать для initial snapshot, recovery и candles, а не как основной high-frequency источник.

## 5.5. Fallback

Если Finam временно недоступен:

1. Redis last-known quote;
2. SQLite `market_quotes`;
3. seeded demo data только в `DEMO_MODE`;
4. пользователь видит timestamp и статус данных.

Frontend не должен падать при недоступности Finam.


# 6. Universe инструментов

## 6.1. Акции

В MVP доступны только российские акции Московской биржи.

Не включать:

- США;
- иностранные акции;
- crypto;
- futures;
- options;
- валюты;
- облигации;
- иностранные ETF.

Использовать curated whitelist:

```text
backend/app/data/instruments/stocks.yml
```

Пример:

```yaml
- ticker: SBER
  mic: MISX
  symbol: SBER@MISX
  enabled: true
  category: stock
  issuer_country: RU
  featured: true
```

На старте — 15–25 ликвидных российских бумаг. Каждый инструмент проверяется через Finam Assets API и хранится в формате `ticker@MIC` (например, `SBER@MISX`).

## 6.2. Фонды

Отдельный curated whitelist:

```text
backend/app/data/instruments/funds.yml
```

Использовать реальные биржевые фонды / БПИФ Московской биржи, доступные через Finam Trade API. Не hardcode торговую площадку: хранить `ticker`, `MIC` и полный `symbol` (`ticker@MIC`) на уровне инструмента.

Для MVP — 3–5 фондов с разными профилями риска.

---

# 7. Игровая цена актива

Пользователь видит цену в TKN, равную **1/100 текущей реальной цены Московской биржи, полученной через Finam Trade API**.

```text
display_token_price = moex_price_rub / 100
```

Пример:

```text
Finam real-time quote (MOEX): 320 ₽
игровая цена: 3.20 TKN
```

Отображение — 2 знака. В расчетах backend использовать `Decimal`, минимум 6 знаков. Не использовать float для ledger/economy.

---

# 8. Ускоренная доходность

В исходных требованиях одновременно звучали «×120» и пример:

```text
реальные +12% в год
→ игровые +120% в год
```

Этот пример соответствует **×10**, поэтому default:

```text
GAME_RETURN_MULTIPLIER = 10.0
```

Параметр конфигурируемый.

## 8.1. Как одновременно сохранить real quote/100 и ×10 P&L

Публичная quote всегда:

```text
Finam real quote RUB / 100
```

Ускоряется не quote, а финансовый результат позиции.

```text
raw_cost = quantity * average_buy_token_price
raw_market_value = quantity * current_display_token_price
raw_pnl = raw_market_value - raw_cost

game_pnl = raw_pnl * GAME_RETURN_MULTIPLIER
game_position_value = max(0, raw_cost + game_pnl)
```

Пример:

```text
Куплено 10 × 3.00 TKN = 30 TKN
Реальная биржевая котировка через Finam выросла на 1%
quote стала 3.03 TKN
raw P&L = +0.30
game P&L = +3.00
game value = 33.00 TKN
```

То есть реальный +1% ≈ игровой +10%.

## 8.2. Sell

Использовать weighted-average cost basis.

```text
raw_proceeds = quantity_to_sell * current_display_token_price
raw_cost_part = quantity_to_sell * average_buy_token_price
raw_realized_pnl = raw_proceeds - raw_cost_part
game_realized_pnl = raw_realized_pnl * GAME_RETURN_MULTIPLIER
cash_credit = max(0, raw_cost_part + game_realized_pnl)
```

Положительный `game_realized_pnl` добавляется в eligible trading profit ledger.

Отрицательный P&L уменьшает капитал.

Wallet не может стать отрицательным.

---

# 9. Торговая механика

Функциональность:

- каталог;
- search;
- filters;
- watchlist;
- карточка инструмента;
- текущая quote;
- изменение за день;
- график;
- краткое описание;
- sector/risk;
- Buy;
- Sell;
- trade preview;
- history;
- position;
- average entry;
- P&L.

Разрешить fractional quantity до 4 знаков.

В MVP — market orders по последней валидной cached quote.

Нет short/margin.

---

# 10. Фонды

Фонды используют ту же торговую архитектуру:

- Finam real-time quote;
- `/100` display price;
- ×10 P&L по default config;
- buy/sell;
- position;
- realized profit;
- conversion eligibility.

Карточка фонда показывает:

- название;
- управляющую компанию, если доступно;
- тип;
- risk label;
- краткое объяснение диверсификации.

Не использовать инвестиционные рекомендации.

---

# 11. Инвесткопилка

Цель — спокойный сценарий регулярного накопления.

## 11.1. Исправление исходной ставки

Буквальные +7–16% **ежедневно с капитализацией** ломают всю экономику: 1 000 TKN при среднем +11.5%/день превращаются примерно в 26 000 TKN за 30 дней.

Поэтому default production-логика:

```text
каждый день случайно выбирается APR от 7% до 16% годовых
```

Начисление:

```text
daily_rate = random_annual_rate / 365
daily_yield = piggy_balance * daily_rate
```

В UI:

```text
Сегодня ставка копилки: 12.4% годовых
```

Config:

```text
INVEST_PIGGY_MIN_APR=0.07
INVEST_PIGGY_MAX_APR=0.16
INVEST_PIGGY_RATE_MODE=annualized
```

Для dev/demo разрешить:

```text
INVEST_PIGGY_RATE_MODE=literal_daily
```

но не включать по умолчанию.

## 11.2. Portfolio cap

В Piggy можно держать не более:

```text
30% текущего token net worth
```

Configurable.

---

# 12. Eligible profit и Alfa Coins

Только **реализованная положительная торговая прибыль** может конвертироваться в AC.

Нельзя конвертировать:

- стартовые 1 000 TKN;
- principal;
- referral grants;
- unrealized P&L;
- CT.

Flow:

```text
buy
→ market move
→ sell
→ calculate realized game P&L
→ positive part becomes eligible_profit_tokens
```

## 12.1. Конвертация сжигает TKN

При conversion:

```text
eligible_profit_tokens -= converted_amount
free_cash_tkn -= converted_amount
alfa_coins += result
```

Это создает выбор:

```text
реинвестировать прибыль
или
забрать часть результата в AC ради цели
```

---

# 13. Динамический коэффициент TKN → AC

Курс зависит от защищённой 30-дневной базы token-капитала, а не только от мгновенного balance.

Это защищает от манипуляции «вывести всё перед конвертацией и получить высокий курс».

```text
V = max(current_token_net_worth, rolling_30d_average_token_net_worth)
```

Net worth включает:

- free TKN;
- game liquidation value stocks;
- game liquidation value funds;
- Piggy.

CT не включаются.

Формула:

```text
excess = max(V - 1000, 0)
conversion_rate = 35 + (50 - 35) / (1 + excess / 8000)
```

Единица:

```text
1 eligible TKN → conversion_rate AC
```

Примеры:

| 30d avg net worth | Курс |
|---:|---:|
| 1 000 TKN | 50 AC/TKN |
| 2 000 | ~48.3 |
| 4 000 | ~45.9 |
| 10 000 | ~42.1 |
| 25 000 | ~38.8 |
| 100 000 | ~36.1 |

Config:

```text
CONVERSION_BASE_RATE=50
CONVERSION_MIN_RATE=35
CONVERSION_REFERENCE_NET_WORTH=1000
CONVERSION_RATE_SOFTENING=8000
```

Мягкая насыщаемая кривая нужна, чтобы сдерживать инфляцию AC, но не создавать
мотивацию искусственно держать капитал маленьким. Основную защиту магазина от
одного сверхприбыльного периода обеспечивают sliding 30-day caps ниже.

---

# 14. Sliding 30-day caps

Чтобы один памп не позволил получить весь магазин:

```text
MAX_BASE_AC_FROM_TRADING_PER_30D=2400
MAX_ACTIVITY_BOOST_AC_PER_30D=600
MAX_TOTAL_AC_EARN_PER_30D=3000
```

Это дает целевой pacing:

- sticker (3 500 AC) — не раньше чем после первого полного 30-дневного окна;
- mug (6 500 AC) — около 2 месяцев активной игры;
- T-shirt (9 500 AC) — около 3 месяцев;
- hoodie (12 500 AC) — около 4 месяцев и не должен легко получаться за один месяц.

---

# 15. Streak / quests / learning в экономике

Activity не должна напрямую раздавать дорогой merch.

Использовать сущность:

```text
Conversion Boost Points
```

Это не отдельная spendable currency. Она активируется только при реальной conversion торговой прибыли.

Пример:

```text
base conversion: 7 000 AC
activity boost: +2 000 AC
итого: 9 000 AC
```

Если пользователь не торговал прибыльно, boost сам по себе не превращается в AC.

## Max activity value

```text
600 AC / rolling 30d
```

Это 30% цены кружки.

## Ограничение на одну conversion

```text
applied_activity_boost = min(
  pending_boost_points,
  base_conversion_ac * 0.35,
  remaining_30d_boost_cap
)
```

---

# 16. Пример экономики

Старт:

```text
1000 TKN
```

Хороший пользователь за месяц реализовал:

```text
+180 eligible TKN
```

При rolling net worth ~1100–1200:

```text
курс ≈ 46–48 AC/TKN
```

Base:

```text
180 × 47 ≈ 8 460 AC
```

Activity boost:

```text
≈ 2 500 AC
```

Итог:

```text
≈ 10 960 AC
```

То есть активный и успешный пользователь может получить кружку примерно за месяц, но не весь магазин.

---

# 17. Shop и goals

Physical shop:

- Sticker Pack;
- Mug;
- T-shirt;
- Hoodie.

Shop item fields:

```text
id
slug
name
description
price_ac
image_url
stock_status
stock_quantity nullable
active
sort_order
```

## Goal tracking

Одна активная physical goal.

Пример:

```text
🎯 Худи Alfa
12 350 / 20 000 AC
61.8%
Осталось: 7 650 AC
```

Показывать progress:

- Home;
- Shop;
- Profile.

Можно показывать estimated pace по последним 14/30 дням:

```text
При текущем темпе: ~23 дня до цели
```

Это estimate, не обещание.

## Purchase flow

При покупке:

1. проверить AC;
2. проверить stock;
3. списать AC транзакционно;
4. создать `shop_order`;
5. показать success.

Physical delivery в prototype mocked.

Статусы:

```text
created
confirmed
processing
shipped
delivered
cancelled
```

---

# 18. Tamagotchi / Invest-pet

Нужен оригинальный милый персонаж. Имя персонажа:

```text
Тин
```

Не копировать Duo.

Статы:

```text
mood 0..100
energy 0..100
knowledge 0..100
friendship 0..100
```

Действия:

- погладить;
- поговорить;
- спросить «что сделать сегодня?»;
- выполнить задание;
- переодеть;
- менять аксессуары;
- менять фон/комнату.

Примеры заданий:

- изучить одну компанию;
- собрать 3 отрасли;
- пройти lesson;
- сравнить stock и fund;
- проверить самую волатильную позицию;
- выполнить portfolio review.

Награды:

- XP;
- streak progress;
- Conversion Boost Points;
- cosmetics.

Нельзя получать AC бесконечным tap по персонажу.

---

# 19. Digital shop Tamagotchi

За AC можно покупать:

- головные уборы;
- очки;
- одежду;
- аксессуары;
- фон комнаты;
- эмоции/анимации.

Цена:

```text
50–600 AC
```

Это soft sink без расходов банка.

Все предметы purely cosmetic.

---

# 20. Learning в стиле Duolingo

Сделать progression path, вдохновленный лучшими принципами Duolingo, но не копировать интерфейс буквально.

Мини-курсы:

1. Что такое инвестиции.
2. Акции.
3. Риск и волатильность.
4. Диверсификация.
5. Фонды.
6. Долгосрочные накопления.
7. Психология инвестора.

Форматы:

- short card;
- swipe cards;
- multiple choice;
- true/false;
- matching;
- scenario;
- investment decision;
- quiz.

Один lesson: 2–5 минут.

---

# 21. Streak

Streak засчитывается не за открытие приложения, а за meaningful action:

- lesson;
- daily quest;
- осмысленную trade action;
- Tamagotchi task;
- portfolio review + ответ.

Хранить:

```text
current_streak
longest_streak
last_streak_date
```

Можно добавить Streak Freeze как digital item/achievement reward.

---

# 22. Daily и Weekly Quests

## Daily

Каждый день генерировать 3 задания из пула.

Примеры:

```text
Изучи 1 компанию
Пройди 1 lesson
Проверь portfolio
Ответь на 3 вопроса
Посмотри 1 fund
Сделай Tamagotchi task
```

## Weekly

```text
5 active days
3 lessons
5 companies
diversified portfolio
compare stock vs fund
```

Награды:

- XP;
- Conversion Boost Points;
- achievement progress.

---

# 23. XP и уровни

XP не имеет денежной стоимости.

Пример levels:

```text
1 Новичок
2 Исследователь
3 Аналитик
4 Инвестор
5 Стратег
6 Портфельный мастер
```

Thresholds:

```text
500
1500
3500
7500
15000 XP
```

Levels открывают cosmetics, badges и новые learning blocks, но не блокируют базовую торговлю.

---

# 24. Achievements

Минимум:

## Trading
- первая покупка;
- первая продажа;
- первый плюс;
- первый минус;
- 10 сделок;
- 50 сделок.

## Learning
- первый lesson;
- 5 lessons;
- первый course;
- все основы.

## Portfolio
- 3 актива;
- 3 отрасли;
- первый fund;
- первая Piggy.

## Retention
- 3-day streak;
- 7-day streak;
- 30-day streak.

## Goals
- выбрал первую goal;
- sticker;
- mug;
- t-shirt;
- hoodie.

## Tamagotchi
- первая вещь;
- friendship 50;
- friendship 100.

Rewards:

- XP;
- cosmetic unlock;
- небольшой Conversion Boost в рамках общего 30-day cap.

---

# 25. Referral

У каждого пользователя:

```text
referral_code
referral_link
```

Flow:

```text
share
→ friend registers
→ onboarding
→ first asset purchase
→ referral complete
```

Награда:

```text
referrer +100 TKN
new user +50 TKN
```

Это principal grant, не eligible profit.

Лимит:

```text
3 token-reward referrals / rolling 30d
```

Дальше — только XP/achievement.

---

# 26. Contest Mode

Отдельная вкладка/entry point `Contest`.

## Locked state

```text
Contest
Соревновательный режим для участников
[Подать заявку]
```

## Fake ЕГЭ verification

Поля:

- ФИО;
- год;
- предмет;
- балл;
- mock certificate id;
- consent checkbox.

Backend не обращается к Госуслугам/ФИС.

Config:

```text
CONTEST_MIN_EGE_SCORE=70
```

Если score >= threshold:

```text
contest_access=verified_mock
```

UI явно пишет:

```text
Демо-проверка для прототипа
```

## Contest wallet

После unlock:

```text
1000 CT
```

CT полностью изолированы.

В MVP:

- Contest balance;
- placeholder leaderboard;
- «соревнования скоро»;
- future-ready contest season API.

---

# 27. Onboarding

2–3 минуты максимум.

Экраны:

1. Учись инвестировать без риска.
2. Получи 1 000 TKN.
3. Котировки Московской биржи поступают через Finam Trade API.
4. Игровой результат ускорен.
5. Прибыль → Alfa Coins.
6. Alfa Coins → merch.
7. Выбери первую goal.

Goal options:

- sticker;
- mug;
- t-shirt;
- hoodie.

После завершения выдать 1 000 TKN **один раз**.

---

# 28. Auth

Prototype auth:

- username/email;
- password;
- birth date;
- display name.

Target age:

```text
14–18
```

Архитектуру сделать заменяемой под Alfa ID в будущем.

Backend:

- JWT access;
- JWT refresh;
- refresh rotation;
- bcrypt password hashing;
- logout/revoke.

---

# 29. Home

Home сразу показывает:

1. token net worth;
2. portfolio change;
3. AC balance;
4. goal progress;
5. next action.

Пример:

```text
Привет 👋
🔥 12 дней

Инвест-счёт
1 184.25 TKN
+14.6% за всё время

Alfa Coins
8 420 AC

🎯 Кружка
8 420 / 10 000
████████████████░░
Осталось 1 580 AC

[Продолжить инвестировать]

Тин:
«Давай посмотрим, какая акция сегодня двигается сильнее всего»

Daily quests 2/3

Рынок сегодня
...
```

---

# 30. Навигация

Mobile bottom navigation:

1. Главная
2. Рынок
3. Тин
4. Учёба
5. Профиль

Contest — отдельная заметная card/entry point. На desktop можно вынести в sidebar.

Shop доступен через:

- AC balance;
- goal widget;
- Profile;
- CTA.

---

# 31. Market UI

Tabs:

```text
Акции | Фонды | Копилка
```

Stocks:

- search;
- featured;
- top movers;
- watchlist;
- sectors.

Карточка:

```text
SBER
Сбербанк
3.21 TKN
+1.2% сегодня
Игровой эффект ×10
```

---

# 32. Instrument screen

Показывать:

- ticker;
- name;
- logo placeholder;
- TKN quote;
- secondary real RUB quote from Finam;
- source timestamp;
- delayed/live badge;
- chart 1D/1W/1M/3M/1Y;
- change;
- short educational context;
- user position;
- Buy/Sell.

Info box:

```text
Почему результат в игре двигается быстрее?
Мы усиливаем относительное движение рынка ×10,
чтобы эффект стратегии был заметен за недели, а не годы.
```

---

# 33. Buy flow

1. Instrument.
2. Buy.
3. Quantity или amount TKN.
4. Preview.
5. Confirm.
6. Transactional execution.
7. Success animation.
8. Portfolio update.

Проверки:

- valid quote;
- enough cash;
- quantity > 0;
- active instrument;
- wallet type correct;
- idempotency.

---

# 34. Sell flow

Preview показывает:

- quantity;
- raw quote;
- average entry;
- raw P&L;
- accelerated P&L;
- expected cash credit;
- eligible profit after sell.

Пример:

```text
Если продать сейчас:
+84.20 TKN игрового результата
станут доступны для конвертации
```

---

# 35. Portfolio

Summary:

```text
Total token net worth
Free cash
Invested
Daily change
All-time game P&L
Eligible profit TKN
```

Breakdown:

- stocks;
- funds;
- Piggy.

Charts:

- value history;
- allocation donut;
- P&L history.

---

# 36. Convert screen

Пример:

```text
Заработано торговлей: 184.20 TKN
Можно конвертировать: 120.00 TKN
Текущий курс: 1 TKN = 46.7 AC
Activity boost: +1 540 AC
```

Slider:

```text
10% / 25% / 50% / MAX
```

Preview:

```text
Ты отдаёшь: 100 TKN
Base: 4 670 AC
Bonus: +1 540 AC
Итого: 6 210 AC
```

После confirm выполнить одну атомарную экономическую транзакцию.

---

# 37. Ledger-first экономика

Все денежные действия должны иметь append-only ledger event.

Event types:

```text
START_GRANT
REFERRAL_GRANT
TRADE_BUY
TRADE_SELL
REALIZED_PROFIT
REALIZED_LOSS
PIGGY_DEPOSIT
PIGGY_WITHDRAW
PIGGY_YIELD
TOKEN_TO_AC_CONVERSION
ACTIVITY_BOOST_EARNED
ACTIVITY_BOOST_USED
SHOP_PURCHASE
TAMAGOTCHI_PURCHASE
CONTEST_GRANT
ADMIN_ADJUSTMENT
```

Balances можно кэшировать/денормализовать, но ledger нужен для audit и reconciliation.

---

# 38. Design direction

После предоставления референса актуального Альфа-Банка использовать его как основной visual reference.

До этого:

- mobile-first;
- premium banking UI;
- фирменный red accent;
- black/white/neutral surfaces;
- bold typography;
- крупные balances;
- мягкие cards;
- clean hierarchy;
- минимум визуального шума;
- expressive micro-interactions;
- Tamagotchi более playful, остальное — не «детское».

Не делать rainbow/neon AI-design.

---

# 39. Design tokens

Создать:

```text
frontend/src/styles/tokens.css
```

Базовая структура:

```css
:root {
  --color-brand-primary: #EF3124;
  --color-bg: #F5F5F7;
  --color-surface: #FFFFFF;
  --color-text-primary: #111111;
  --color-text-secondary: #707070;
  --color-positive: #1F9D63;
  --color-negative: #D94444;

  --radius-sm: 12px;
  --radius-md: 18px;
  --radius-lg: 28px;

  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-6: 24px;
  --space-8: 32px;
}
```

Финальные значения обновить после визуального референса.

---

# 40. Motion

Нужны:

- balance count-up;
- trade success;
- goal progress;
- streak fire;
- achievement unlock;
- Tamagotchi reactions;
- shop purchase;
- chart transitions.

Уважать `prefers-reduced-motion`.

---

# 41. PWA

Обязательно:

- manifest;
- icons;
- standalone display;
- service worker;
- install flow;
- offline shell;
- iOS Add to Home Screen;
- Android install;
- desktop install.

Offline доступны read-only:

- cached lessons;
- profile;
- portfolio;
- last Finam/market-data snapshot.

Trading offline запрещено.

---

# 42. Рекомендуемый стек

## Frontend

```text
React
TypeScript
Vite
React Router
TanStack Query
Zustand
Tailwind CSS + design tokens
Recharts
Framer Motion
vite-plugin-pwa
Zod
React Hook Form
```

TanStack Query — server state. Zustand — local UI/game state. Не дублировать server state в Zustand.

## Backend

```text
Python 3.12+
FastAPI
Pydantic v2
SQLAlchemy 2
Alembic
aiosqlite
Redis
httpx
APScheduler
JWT library
bcrypt password hashing
```

## DB

```text
SQLite
```

Обязательно:

```text
WAL
busy_timeout
foreign_keys=ON
```

Архитектуру repositories/services сделать совместимой с будущей миграцией на PostgreSQL.

---

# 43. Архитектура

```text
[PWA React]
      |
      | REST / WebSocket
      v
[FastAPI modular monolith]
      |
      +-- Auth
      +-- Market
      +-- Trading
      +-- Portfolio
      +-- Economy
      +-- Shop
      +-- Learning
      +-- Quests
      +-- Tamagotchi
      +-- Referral
      +-- Contest
      |
      +-- Redis
      +-- SQLite
      +-- MarketDataProvider -> Finam Trade API (REST + WebSocket)
```

Не использовать микросервисы на MVP.

---

# 44. MarketDataProvider

Интерфейс:

```python
class MarketDataProvider(Protocol):
    async def get_quote(self, instrument_id: str) -> Quote: ...
    async def get_quotes(self, instrument_ids: list[str]) -> list[Quote]: ...
    async def get_candles(
        self,
        instrument_id: str,
        interval: str,
        start: datetime,
        end: datetime,
    ) -> list[Candle]: ...
    async def get_instrument(self, instrument_id: str) -> InstrumentMeta: ...
    async def subscribe_quotes(
        self,
        instrument_ids: list[str],
    ) -> AsyncIterator[QuoteUpdate]: ...
```

Реализации:

```text
FinamTradeApiProvider
CachedMarketDataProvider
MockMarketDataProvider
```

Fallback order:

1. Finam Trade API real-time stream / REST;
2. Redis last-known;
3. SQLite last-known;
4. seeded demo history.

---

# 45. Market sync

Основная доставка quote updates — **Finam WebSocket**, а не REST polling.

Background jobs и recovery tasks:

## Quotes

Во время доступности Finam WebSocket:

```text
continuous QUOTES subscription
```

REST LastQuote использовать:

- при старте приложения;
- после reconnect;
- для инструмента, который ещё не присутствует в stream cache;
- как controlled fallback.

Если stream недоступен — fallback polling:

```text
15–30 sec configurable
```

но только централизованно backend, а не от каждого frontend-клиента.

## Metadata

```text
1 раз в сутки
```

## Candles

```text
5–15 min intraday
+ daily refresh
```

Использовать Redis distributed lock.

---

# 46. Quote model

```text
instrument_id
secid
boardid
real_price_rub
display_price_tkn
change_pct
previous_close
source
source_timestamp
fetched_at
is_delayed
is_stale
```

---

# 47. Database schema

## users

```text
id
email
username
password_hash
display_name
birth_date
onboarding_completed
referral_code
referred_by_user_id
status
created_at
updated_at
```

## wallets

```text
id
user_id
token_cash
alfa_coins
eligible_profit_tokens
pending_activity_boost
updated_at
```

Contest wallet хранить отдельно.

## instruments

```text
id
secid
boardid
type stock|fund
name
short_name
issuer
sector
risk_level
description
currency
enabled
featured
```

## market_quotes

```text
instrument_id
real_price_rub
previous_close
change_pct
source_timestamp
fetched_at
```

## market_candles

```text
id
instrument_id
interval
open
high
low
close
volume
timestamp
```

## positions

```text
id
user_id
instrument_id
quantity
average_buy_token_price
raw_cost_basis
created_at
updated_at
```

Unique `(user_id, instrument_id)`.

## trades

```text
id
user_id
instrument_id
side
quantity
raw_quote_tkn
raw_cost_basis_part
raw_pnl
game_pnl
cash_change_tkn
status
idempotency_key
executed_at
```

## ledger_entries

```text
id
user_id
currency
event_type
amount
balance_after
reference_type
reference_id
metadata_json
created_at
```

## net_worth_snapshots

```text
id
user_id
token_net_worth
cash
stocks_value
funds_value
piggy_value
created_at
```

## piggy_accounts

```text
id
user_id
balance_tkn
current_apr
last_accrual_at
created_at
updated_at
```

## conversions

```text
id
user_id
tokens_burned
conversion_rate
base_ac
activity_bonus_ac
total_ac
rolling_net_worth
created_at
```

## shop_items

```text
id
slug
name
description
type physical|digital_tamagotchi
price_ac
image_url
active
stock_quantity
sort_order
```

## shop_orders

```text
id
user_id
shop_item_id
quantity
total_ac
status
delivery_data_json
created_at
updated_at
```

## user_goals

```text
id
user_id
shop_item_id
active
created_at
completed_at
```

## courses

```text
id
slug
title
description
order_index
active
```

## lessons

```text
id
course_id
title
content_json
xp_reward
boost_reward
order_index
```

## lesson_progress

```text
id
user_id
lesson_id
status
score
completed_at
```

## quests

```text
id
type daily|weekly|tamagotchi
code
title
description
criteria_json
xp_reward
boost_reward
active
```

## user_quests

```text
id
user_id
quest_id
period_key
progress
target
completed
claimed
```

## streaks

```text
user_id
current_streak
longest_streak
last_active_date
freeze_count
```

## achievements

```text
id
code
title
description
criteria_json
xp_reward
boost_reward
cosmetic_reward_id
```

## user_achievements

```text
user_id
achievement_id
progress
unlocked_at
claimed_at
```

## tamagotchi

```text
user_id
name
mood
energy
knowledge
friendship
equipped_items_json
last_interaction_at
```

## tamagotchi_items

```text
id
slot
name
price_ac
asset_url
rarity
active
```

## user_tamagotchi_items

```text
user_id
item_id
acquired_at
```

## referrals

```text
id
referrer_user_id
referred_user_id
status
rewarded_at
created_at
```

## contest_profiles

```text
id
user_id
verification_status
full_name
ege_year
ege_subject
ege_score
certificate_mock
verified_at
```

## contest_wallets

```text
user_id
contest_tokens
```

## app_config

```text
key
value_json
updated_at
```


---

# 48. Redis key strategy

Пример ключей:

```text
market:quote:{secid}:{boardid}
market:candles:{secid}:{interval}
market:instrument:{secid}
market:sync:lock

user:{id}:portfolio_summary
user:{id}:rate_limit
user:{id}:conversion_preview

daily_quests:{date}:{user_id}
leaderboard:contest:{season_id}

idempotency:{user_id}:{key}
```

Рекомендуемые TTL:

- quotes: 1–5 минут;
- candles: 5–30 минут в зависимости от interval;
- portfolio summary: 10–30 секунд;
- idempotency keys: 24 часа;
- daily quests: до конца следующего дня.

Если Redis недоступен, приложение не должно падать целиком: market data и auth должны иметь graceful degradation там, где это возможно.

---

# 49. REST API

Prefix:

```text
/api/v1
```

## Auth

```text
POST /auth/register
POST /auth/login
POST /auth/refresh
POST /auth/logout
GET  /auth/me
```

## Onboarding

```text
GET  /onboarding
POST /onboarding/complete
```

## Market

```text
GET    /market/instruments
GET    /market/instruments/{id}
GET    /market/instruments/{id}/candles
GET    /market/movers
GET    /market/watchlist
POST   /market/watchlist/{id}
DELETE /market/watchlist/{id}
```

## Portfolio

```text
GET /portfolio
GET /portfolio/history
GET /portfolio/positions
GET /portfolio/trades
```

## Trading

```text
POST /trades/preview
POST /trades/buy
POST /trades/sell
GET  /trades/{id}
```

Все write requests поддерживают:

```text
Idempotency-Key
```

## Piggy

```text
GET  /piggy
POST /piggy/deposit
POST /piggy/withdraw
GET  /piggy/history
```

## Economy

```text
GET  /economy/conversion
POST /economy/conversion/preview
POST /economy/convert
GET  /economy/ledger
```

## Shop

```text
GET    /shop/items
GET    /shop/orders
POST   /shop/orders
GET    /shop/goal
PUT    /shop/goal
DELETE /shop/goal
```

## Learning

```text
GET  /learning/courses
GET  /learning/courses/{id}
GET  /learning/lessons/{id}
POST /learning/lessons/{id}/complete
GET  /learning/progress
```

## Quests

```text
GET  /quests/daily
GET  /quests/weekly
POST /quests/{id}/claim
```

## Achievements

```text
GET  /achievements
POST /achievements/{id}/claim
```

## Tamagotchi

```text
GET  /tamagotchi
POST /tamagotchi/interact
GET  /tamagotchi/tasks
GET  /tamagotchi/shop
POST /tamagotchi/shop/{item_id}/buy
POST /tamagotchi/equip/{item_id}
```

## Referral

```text
GET  /referrals
GET  /referrals/share
POST /referrals/apply
```

## Contest

```text
GET  /contest
POST /contest/apply
GET  /contest/wallet
GET  /contest/leaderboard
```

## Health

```text
GET /health
GET /health/ready
```

---

# 50. WebSocket / live updates

Есть два разных WebSocket уровня.

## Upstream

```text
Finam: wss://api.finam.ru/ws
```

Используется только backend.

## Client-facing

Endpoint приложения:

```text
/ws/market
```

Client подписывается на инструменты:

```json
{
  "type": "subscribe",
  "instruments": ["SBER", "YDEX", "LKOH"]
}
```

Backend отправляет нормализованные cached quote updates.

Если WebSocket недоступен — frontend автоматически переходит на TanStack Query polling.

---

# 51. Transaction safety

Все экономические операции выполнять транзакционно:

- buy;
- sell;
- conversion;
- shop purchase;
- referral reward;
- Piggy deposit/withdraw.

Нельзя допускать сценарий:

```text
списали balance
→ process crash
→ запись операции не создана
```

Write endpoints должны быть idempotent.

---

# 52. SQLite settings

При подключении:

```sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;
```

Не держать DB transaction открытой во время сетевого запроса к Finam Trade API.

Правильный flow trade:

```text
получить quote из Redis/provider
→ validate
→ открыть короткую DB transaction
→ провести ledger + position + wallet updates
→ commit
```

---

# 53. Background jobs

APScheduler jobs:

```text
sync_market_quotes
sync_market_candles
sync_instrument_metadata
accrue_piggy_interest
snapshot_user_net_worth
generate_daily_quests
generate_weekly_quests
refresh_tamagotchi_state
expire_stale_cache
reconcile_wallets
```

## Net worth snapshots

Минимум раз в сутки для всех пользователей.

Для активных можно каждый час.

30-day rolling conversion rate рассчитывать из snapshots, а не из текущего мгновенного balance.

---

# 54. Activity economy

Целевой максимум activity layer:

```text
3 000 AC эквивалента Conversion Boost / rolling 30d
```

Пример распределения максимума:

| Источник | Max boost / 30d |
|---|---:|
| Daily quests | 900 |
| Lessons | 750 |
| Streak milestones | 450 |
| Weekly quests | 600 |
| Achievements | 300 |
| **Итого** | **3 000** |

Обычный пользователь должен получать примерно 40–70% этого максимума. 100% — только при высокой активности.

---

# 55. Faucets и sinks

## TKN faucets

- стартовые 1 000;
- рыночная прибыль;
- Piggy yield;
- ограниченный referral grant.

## TKN sinks

- conversion TKN → AC.

## AC faucets

- conversion of eligible realized profit;
- activity boost, применяемый только внутри conversion.

## AC sinks

- physical merch;
- Tamagotchi cosmetics;
- optional cosmetic profile items;
- optional streak freeze.

## CT

- только Contest grant/future contest rewards;
- полностью отдельная экономика.

---

# 56. Anti-exploit rules

Обязательно:

1. Principal нельзя конвертировать.
2. Unrealized P&L нельзя конвертировать.
3. CT нельзя конвертировать.
4. Один idempotent trade нельзя выполнить дважды.
5. Referral reward только после onboarding + first trade друга.
6. Максимум 3 token-reward referrals за rolling 30d.
7. Conversion rate использует rolling average net worth до текущей conversion.
8. AC cap — sliding 30 days, не календарный месяц.
9. Activity boost cap — sliding 30 days.
10. Stale quote блокирует trade или требует explicit demo-mode разрешения.
11. Нельзя купить merch без AC.
12. Нельзя купить inactive/out-of-stock item.
13. Piggy не превышает заданную долю портфеля.
14. Wallet не отрицательный.
15. Нет leverage.
16. Нет short.
17. Нет cash withdrawal.
18. Все economic actions аудируются.
19. При отрицательном P&L нельзя получить positive eligible profit.
20. Все денежные расчеты только backend-side.

---

# 57. Market status

Всегда показывать timestamp:

```text
Последнее обновление: 14:32
```

Badges:

```text
Live
Задержка
Рынок закрыт
Данные устарели
Demo data
```

Не притворяться, что delayed data являются real-time.

В demo mode можно разрешить сделки по last-known quote, но UI должен это обозначать.

---

# 58. Error states

Обязательные UX-состояния:

- Finam Trade API unavailable;
- Redis unavailable;
- stale quote;
- insufficient TKN;
- insufficient AC;
- no eligible profit;
- conversion cap reached;
- Piggy cap reached;
- Contest locked;
- offline;
- expired session;
- merch out of stock;
- duplicate idempotent operation;
- invalid instrument.

Ошибки human-readable, не показывать traceback пользователю.

---

# 59. Accessibility

Минимум:

- WCAG AA contrast;
- keyboard navigation;
- visible focus;
- semantic buttons;
- aria-labels;
- `prefers-reduced-motion`;
- текстовый summary для charts;
- tap targets >= 44px;
- смысл не передается только цветом.

---

# 60. Responsive

Mobile-first target:

```text
360–430 px
```

Tablet:

```text
768+
```

Desktop:

```text
1024+
```

Desktop может иметь centered shell/sidebar и 2-column market/portfolio layouts.

---

# 61. Frontend structure

```text
frontend/
  src/
    app/
      router/
      providers/
    components/
      ui/
      charts/
      market/
      portfolio/
      shop/
      learning/
      tamagotchi/
    features/
      auth/
      onboarding/
      market/
      trading/
      portfolio/
      economy/
      shop/
      learning/
      quests/
      achievements/
      referral/
      contest/
    pages/
    hooks/
    lib/
      api/
      format/
      validation/
    store/
    styles/
      tokens.css
    assets/
  public/
    manifest.webmanifest
```

---

# 62. Backend structure

```text
backend/
  app/
    main.py
    core/
      config.py
      security.py
      logging.py
      redis.py
      db.py
    api/
      v1/
    models/
    schemas/
    repositories/
    services/
      market/
      trading/
      portfolio/
      economy/
      shop/
      learning/
      quests/
      tamagotchi/
      referrals/
      contest/
    integrations/
      finam/
        auth.py
        rest_client.py
        websocket_client.py
        provider.py
        schemas.py
    jobs/
    data/
      instruments/
        stocks.yml
        funds.yml
      seed/
  migrations/
  tests/
```

---

# 63. Environment variables

Создать `.env.example`:

```env
APP_ENV=development
APP_SECRET=change-me
DATABASE_URL=sqlite+aiosqlite:///./data/app.db
REDIS_URL=redis://localhost:6379/0

MARKET_DATA_PROVIDER=finam

FINAM_REST_BASE_URL=https://api.finam.ru
FINAM_WS_URL=wss://api.finam.ru/ws

# NEVER commit a real value. Put the issued tapi_sk_... secret only in local
# .env / deployment secret storage.
FINAM_API_SECRET=

FINAM_JWT_REFRESH_SKEW_SECONDS=90
FINAM_RECONNECT_MIN_SECONDS=1
FINAM_RECONNECT_MAX_SECONDS=60
FINAM_FALLBACK_POLL_SECONDS=30

ALLOW_STALE_TRADING=true

STARTING_TOKENS=1000
GAME_RETURN_MULTIPLIER=10

CONVERSION_BASE_RATE=50
CONVERSION_MIN_RATE=35
CONVERSION_REFERENCE_NET_WORTH=1000
CONVERSION_RATE_SOFTENING=8000
MAX_BASE_AC_FROM_TRADING_PER_30D=2400
MAX_ACTIVITY_BOOST_AC_PER_30D=600
MAX_TOTAL_AC_EARN_PER_30D=3000

INVEST_PIGGY_MIN_APR=0.07
INVEST_PIGGY_MAX_APR=0.16
INVEST_PIGGY_RATE_MODE=annualized
INVEST_PIGGY_MAX_PORTFOLIO_SHARE=0.30

REFERRAL_REFERRER_REWARD_TKN=100
REFERRAL_NEW_USER_REWARD_TKN=50
REFERRAL_REWARD_LIMIT_30D=3

CONTEST_MIN_EGE_SCORE=70

SHOP_STICKER_PRICE=3500
SHOP_MUG_PRICE=6500
SHOP_TSHIRT_PRICE=9500
SHOP_HOODIE_PRICE=12500
```

---

# 64. Demo mode

Обязателен:

```text
DEMO_MODE=true
```

Demo mode должен:

- создавать demo user;
- иметь seeded market history;
- работать при недоступном Finam Trade API;
- позволять пройти полный сценарий за 5–10 минут;
- иметь developer-only shortcut для презентации.

Например:

```text
POST /api/v1/dev/scenario/profitable-month
```

Этот endpoint существует только при `APP_ENV=development` и никогда не доступен в production.

---

# 65. Seed content

Минимум:

- 15–25 stocks;
- 3–5 funds;
- 4 physical shop items;
- 15+ Tamagotchi cosmetics;
- 7 courses;
- 25+ lessons;
- 20 daily quests;
- 10 weekly quests;
- 20 achievements;
- demo user;
- demo portfolio;
- demo market fallback history.

---

# 66. Admin/config

Hidden admin page:

```text
/admin
```

Только admin role.

Настройки:

- merch prices;
- merch stock;
- return multiplier;
- conversion coefficients;
- conversion caps;
- activity cap;
- referral rewards;
- Piggy APR;
- Piggy max share;
- enabled instruments;
- Contest threshold.

Это важно для кейса: economy tuning без изменения кода.

---

# 67. Analytics events

Сделать analytics abstraction. Provider в MVP может быть local/console.

Events:

```text
app_open
onboarding_started
onboarding_completed
goal_selected
instrument_viewed
trade_previewed
trade_bought
trade_sold
profit_realized
conversion_previewed
conversion_completed
shop_viewed
shop_purchase
lesson_started
lesson_completed
quest_completed
streak_extended
achievement_unlocked
tamagotchi_interaction
referral_shared
referral_completed
contest_applied
contest_unlocked
pwa_installed
```

Не отправлять sensitive personal data.

---

# 68. Product metrics

Подготовить admin queries/cards:

- DAU;
- WAU;
- D1/D7 retention, если возможно;
- streak retention;
- lessons/week;
- first trade conversion;
- first realized profit;
- conversion usage;
- median TKN net worth;
- median AC balance;
- sticker redemption;
- mug redemption;
- t-shirt redemption;
- hoodie redemption;
- median days to first merch;
- % пользователей, дошедших до hoodie;
- allocation stock/fund/Piggy;
- referral conversion;
- Contest unlock rate.

---

# 69. Security

Даже в prototype:

- secrets только backend;
- JWT;
- strong password hashing;
- explicit CORS;
- rate limits;
- strict validation;
- parameterized DB access;
- no raw SQL from user input;
- safe errors;
- audit log;
- admin role;
- no dev routes in production;
- refresh token revoke/rotation.

---

# 70. Testing

## Backend unit tests

Обязательные:

- ×10 P&L;
- weighted average cost;
- partial sell;
- realized positive P&L;
- realized loss;
- eligible profit;
- principal non-convertibility;
- conversion formula;
- min/max conversion rate;
- rolling net worth;
- 30-day caps;
- activity boost;
- TKN burn;
- AC credit;
- shop purchase;
- referral cap;
- Piggy APR accrual;
- Contest wallet isolation.

## Integration tests

```text
register
→ onboarding
→ 1000 TKN
→ buy
→ mocked market move
→ sell
→ eligible profit
→ convert
→ AC
→ goal
→ shop purchase
```

Также:

- lesson → quest → boost;
- referral;
- fake Contest verification.

## Frontend

Vitest + Testing Library.

## E2E

Playwright.

Critical E2E использует deterministic `MockMarketDataProvider`.

---

# 71. Development infrastructure

Создать `docker-compose.yml`.

Services:

- backend;
- Redis;
- frontend optional dev container.

SQLite хранить в volume.

Запуск:

```bash
docker compose up
```

Локально backend:

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Можно использовать pnpm, если весь проект единообразно его использует.

---

# 72. README

README обязан содержать:

- описание продукта;
- stack;
- prerequisites;
- installation;
- env;
- migrations;
- seed;
- Finam Trade API integration;
- demo mode;
- economy overview;
- PWA install;
- tests;
- deployment;
- known limitations;
- Finam market-data/production usage note.

---

# 73. Modular monolith

Не использовать microservices в MVP.

Причины:

- case championship;
- FastAPI + SQLite;
- одна команда;
- быстрее разработка;
- проще deployment;
- проще тестирование.

Но модули Market/Economy/Contest должны быть достаточно изолированы, чтобы позже вынести их отдельно.

---

# 74. Screen inventory

Минимум:

1. Splash
2. Login
3. Register
4. Onboarding
5. Goal selection
6. Home
7. Market
8. Stocks
9. Funds
10. Piggy
11. Instrument details
12. Buy
13. Sell
14. Trade result
15. Portfolio
16. Portfolio history
17. Conversion
18. Conversion success
19. Shop
20. Item detail
21. Goal detail
22. Shop purchase flow
23. Learning map
24. Lesson
25. Lesson result
26. Quests
27. Achievements
28. Tamagotchi room
29. Tamagotchi wardrobe
30. Tamagotchi digital shop
31. Referral
32. Contest locked
33. Contest fake verification
34. Contest home
35. Profile
36. Settings
37. Admin/dev
38. Offline/error states

---

# 75. Acceptance criteria

## Functional

- [ ] Новый пользователь регистрируется.
- [ ] Onboarding реально сохраняется.
- [ ] После onboarding пользователь получает ровно 1 000 TKN один раз.
- [ ] Можно выбрать merch goal.
- [ ] Отображаются российские акции Московской биржи с real-time данными через Finam Trade API.
- [ ] Quote в TKN = реальная биржевая цена RUB, полученная через Finam, / 100.
- [ ] Можно купить stock.
- [ ] Можно продать stock.
- [ ] Game P&L ускоряется ×10.
- [ ] Работают funds.
- [ ] Работает Piggy.
- [ ] Positive realized P&L становится eligible.
- [ ] Principal не становится eligible.
- [ ] Можно конвертировать eligible TKN → AC.
- [ ] Курс зависит от rolling net worth.
- [ ] TKN сжигаются при conversion.
- [ ] Sliding caps работают.
- [ ] Activity boost работает.
- [ ] Shop содержит 4 physical merch items с заданными ценами.
- [ ] Goal progress работает.
- [ ] AC списываются при покупке.
- [ ] Tamagotchi функционален.
- [ ] Tamagotchi cosmetics покупаются.
- [ ] Learning работает.
- [ ] Streak работает.
- [ ] Daily quests работают.
- [ ] Weekly quests работают.
- [ ] Achievements работают.
- [ ] Referral работает.
- [ ] Contest fake verification работает.
- [ ] Contest wallet изолирован.
- [ ] PWA устанавливается.
- [ ] Offline read-only fallback работает.
- [ ] Demo mode работает.

## Quality

- [ ] Нет critical TypeScript errors.
- [ ] Backend tests проходят.
- [ ] Critical E2E проходит.
- [ ] Нет hardcoded user balances во frontend.
- [ ] Economy calculations только backend.
- [ ] Money через Decimal.
- [ ] FastAPI OpenAPI docs доступны.
- [ ] Redis outage не рушит весь app.
- [ ] Finam outage не рушит Home.
- [ ] UI mobile-first.
- [ ] Desktop usable.
- [ ] Нет dead primary buttons.

---

# 76. Порядок реализации Codex

## Phase 1 — Foundation

- repository;
- FastAPI;
- React;
- SQLite;
- Redis;
- Docker;
- auth;
- config;
- migrations.

## Phase 2 — Market

- Finam provider;
- stock/fund whitelist;
- quotes;
- candles;
- Redis cache;
- Market UI.

## Phase 3 — Trading engine

- wallets;
- positions;
- buy/sell;
- ×10 P&L;
- ledger;
- portfolio.

## Phase 4 — Economy

- eligible profit;
- rolling net worth;
- conversion;
- caps;
- activity boost;
- AC.

## Phase 5 — Shop

- merch;
- goals;
- purchase;
- mocked delivery.

## Phase 6 — Funds + Piggy

- fund trading;
- Piggy;
- accrual.

## Phase 7 — Learning

- courses;
- lessons;
- XP;
- streak;
- quests;
- achievements;
- conversion boost.

## Phase 8 — Tamagotchi

- character;
- states;
- tasks;
- cosmetics;
- digital shop.

## Phase 9 — Referral + Contest

- invite;
- rewards;
- fake ЕГЭ verification;
- Contest wallet.

## Phase 10 — PWA + Visual polish

- install;
- offline;
- responsive;
- motion;
- accessibility;
- adaptation to Alfa visual reference.

## Phase 11 — QA + Demo

- seed;
- E2E;
- deterministic demo scenario;
- README.

После каждого phase запускать tests и исправлять regressions до перехода дальше.

---

# 77. Решения, которые Codex не должен менять самостоятельно

1. Старт — **1 000 TKN**.
2. Акции — только curated universe российских бумаг Московской биржи, доступных через Finam Trade API.
3. Quote — **реальная биржевая цена из Finam / 100**.
4. Default game P&L multiplier — **×10**.
5. ×10 следует из примера `12% → 120%`.
6. Alfa Coins нельзя купить за деньги.
7. Principal напрямую не конвертируется в AC.
8. Только positive realized trading profit eligible.
9. Conversion сжигает TKN.
10. Dynamic rate зависит от rolling 30-day net worth.
11. Trading AC cap — **2 400 / rolling 30d**.
12. Activity boost cap — **600 / rolling 30d**.
13. Total earn cap — **3 000 / rolling 30d**.
14. Sticker Pack — **3 500 AC**.
15. Mug — **6 500 AC**.
16. T-shirt — **9 500 AC**.
17. Hoodie — **12 500 AC**.
18. Hoodie — top reward.
19. Piggy default — random **7–16% APR**, refresh daily, accrual daily.
20. Literal +7–16% daily — только dev flag.
21. CT полностью изолированы.
22. Contest verification — mock.
23. Backend — Python + FastAPI.
24. DB — SQLite.
25. Redis обязателен.
26. Frontend — installable PWA.
27. Architecture — modular monolith.
28. Economy calculations — backend only.
29. Economy config editable.
30. Visual reference — предоставленный дизайн Альфа-Банка.

---

# 78. Product tone

Приложение не должно ощущаться как скучный курс и не должно выглядеть как детский брокер.

Оно должно ощущаться как:

> **настоящая инвестиционная игра, где рынок ведёт себя как реальный рынок, ошибки не стоят реальных денег, а хорошее понимание инвестиций постепенно превращается в ощутимое достижение.**

Главная эмоция:

```text
Я сам решил, куда вложить виртуальный капитал.
Я увидел, как решение сработало.
Я заработал результат.
Теперь я реально ближе к вещи, которую хотел.
```

---

# 79. Finam / production market-data note

Для prototype основной источник данных:

```text
Finam Trade API
→ real-time quotes / historical market data
→ server-side Redis cache
→ собственный MarketDataProvider
```

При этом Finam API используется **только как источник market data**. Никакие реальные сделки через брокерский счёт Finam из teen-приложения не отправляются.

Secret key:

- существует только server-side;
- не попадает в git;
- не попадает во frontend;
- не записывается в analytics;
- не выводится в logs;
- хранится через `.env` только локально, а в deployment — через secret manager.

Важно разделять:

```text
FINAM_API_SECRET = долгоживущий secret с портала
Finam JWT        = короткоживущий session token (~15 min)
```

Backend самостоятельно получает и обновляет JWT через `/v1/sessions`.

Для production внутри Альфа-Банка `MarketDataProvider` должен оставаться заменяемым. Если в дальнейшем Альфа-Банк предоставит собственный licensed market-data feed, потребуется реализовать новый provider без изменения UI, portfolio и game-economy engine:

```text
Prototype:
FinamTradeApiProvider

Production:
AlfaLicensedMarketDataProvider
или другой согласованный provider

→ тот же MarketDataProvider interface
```

Перед публичным production launch отдельно проверить договорные условия используемого market-data source и права на отображение/ретрансляцию биржевых данных конечным пользователям.


# 80. Definition of Done для Codex

Не завершать работу после генерации UI.

Работа завершена, когда вручную можно пройти:

```text
регистрация
→ onboarding
→ получить 1 000 TKN
→ выбрать худи целью
→ открыть рынок российских акций с real-time Finam data
→ купить российскую акцию
→ увидеть market movement
→ продать
→ получить realized game profit
→ открыть conversion
→ обменять eligible TKN в AC
→ увидеть progress до худи
→ пройти lesson
→ продлить streak
→ выполнить quest
→ получить activity conversion boost
→ взаимодействовать с Тином
→ купить ему cosmetic item
→ открыть Contest
→ пройти fake ЕГЭ verification
→ увидеть отдельный CT wallet
→ установить PWA
```

И deterministic automated E2E этого flow должен проходить с `MockMarketDataProvider`.

---

# 81. Финальная инструкция агенту

При реализации приоритеты следующие:

```text
1. Correct economy
2. Correct trading ledger
3. Reliable Finam real-time integration + Redis/DB fallback
4. Smooth mobile UX
5. Goal/reward clarity
6. Retention mechanics
7. Visual polish
```

Если возникает выбор между «красиво, но fake» и «чуть проще, но реально работает», выбирать **реально работает**.

Не создавать fake market data в production path, если Finam Trade API доступен. Demo data использовать только как явный fallback/dev provider.

Не менять финансовые коэффициенты молча. Любой альтернативный коэффициент должен быть параметром конфигурации и документирован.

---

**Конец ТЗ.**
