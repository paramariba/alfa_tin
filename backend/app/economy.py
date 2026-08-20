from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

ZERO = Decimal("0")
MONEY = Decimal("0.01")
QTY = Decimal("0.0001")


def d(value: object) -> Decimal:
    return Decimal(str(value))


def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def display_token_price(real_price_rub: Decimal) -> Decimal:
    return money(real_price_rub / d(100))


def game_position_value(quantity: Decimal, average_buy: Decimal, current_quote: Decimal, multiplier: Decimal) -> Decimal:
    raw_cost = quantity * average_buy
    raw_pnl = quantity * current_quote - raw_cost
    return money(max(ZERO, raw_cost + raw_pnl * multiplier))


@dataclass(frozen=True)
class SellResult:
    raw_cost_part: Decimal
    raw_pnl: Decimal
    game_pnl: Decimal
    cash_credit: Decimal
    eligible_profit: Decimal


def sell_result(quantity: Decimal, average_buy: Decimal, current_quote: Decimal, multiplier: Decimal) -> SellResult:
    raw_cost = quantity * average_buy
    raw_proceeds = quantity * current_quote
    raw_pnl = raw_proceeds - raw_cost
    game_pnl = raw_pnl * multiplier
    return SellResult(
        raw_cost_part=money(raw_cost),
        raw_pnl=money(raw_pnl),
        game_pnl=money(game_pnl),
        cash_credit=money(max(ZERO, raw_cost + game_pnl)),
        eligible_profit=money(max(ZERO, game_pnl)),
    )


def weighted_average(old_quantity: Decimal, old_average: Decimal, bought_quantity: Decimal, buy_quote: Decimal) -> Decimal:
    total = old_quantity + bought_quantity
    if total <= ZERO:
        return ZERO
    return ((old_quantity * old_average + bought_quantity * buy_quote) / total).quantize(Decimal("0.000001"))


def conversion_rate(
    rolling_net_worth: Decimal,
    base: Decimal = d(50),
    minimum: Decimal = d(5),
    reference: Decimal = d(1000),
    softening: Decimal = d(8000),
) -> Decimal:
    """Return a decreasing AC rate while keeping total earning power monotonic.

    A square-root curve means doubling capital still increases the absolute AC
    earning capacity by sqrt(2), rather than doubling it. ``softening`` remains
    in the signature for backwards-compatible config/API calls.
    """
    effective = max(rolling_net_worth, reference)
    safe_reference = max(reference, d(1))
    rate = base / (effective / safe_reference).sqrt()
    return money(max(minimum, min(base, rate)))


def conversion_preview(
    tokens: Decimal,
    eligible: Decimal,
    cash: Decimal,
    rolling_net_worth: Decimal,
    pending_boost: Decimal,
    base_cap_remaining: Decimal,
    boost_cap_remaining: Decimal,
    total_cap_remaining: Decimal,
    base_rate: Decimal = d(50),
    minimum_rate: Decimal = d(35),
    reference_net_worth: Decimal = d(1000),
    rate_softening: Decimal = d(8000),
) -> dict[str, Decimal]:
    requested_burn = min(max(tokens, ZERO), eligible, cash)
    rate = conversion_rate(rolling_net_worth, base_rate, minimum_rate, reference_net_worth, rate_softening)
    base_limit = max(ZERO, min(base_cap_remaining, total_cap_remaining))
    # Never burn tokens that cannot produce AC because a rolling cap is almost
    # exhausted. The final min below also absorbs cent rounding at the edge.
    burn = min(requested_burn, base_limit / rate if rate > ZERO else ZERO).quantize(MONEY, rounding=ROUND_DOWN)
    base_ac = money(min(burn * rate, base_cap_remaining, total_cap_remaining))
    boost = money(min(pending_boost, base_ac * d("0.35"), boost_cap_remaining, max(ZERO, total_cap_remaining - base_ac)))
    return {"tokens": burn, "rate": rate, "base_ac": base_ac, "boost_ac": boost, "total_ac": money(base_ac + boost)}


def piggy_daily_yield(balance: Decimal, annual_rate: Decimal) -> Decimal:
    return money(balance * annual_rate / d(365))
