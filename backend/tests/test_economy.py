from decimal import Decimal as D

from app.economy import conversion_preview, conversion_rate, game_position_value, piggy_daily_yield, sell_result, weighted_average


def test_game_pnl_is_accelerated_ten_times():
    assert game_position_value(D("10"), D("3"), D("3.03"), D("10")) == D("33.00")


def test_partial_sell_and_positive_eligible_profit():
    result = sell_result(D("4"), D("3"), D("3.2"), D("10"))
    assert result.raw_cost_part == D("12.00")
    assert result.game_pnl == D("8.00")
    assert result.cash_credit == D("20.00")
    assert result.eligible_profit == D("8.00")


def test_loss_never_creates_eligible_profit_or_negative_credit():
    result = sell_result(D("10"), D("3"), D("2"), D("10"))
    assert result.eligible_profit == D("0.00")
    assert result.cash_credit == D("0.00")


def test_weighted_average_cost():
    assert weighted_average(D("2"), D("3"), D("3"), D("4")) == D("3.600000")


def test_conversion_rate_slows_inflation_and_still_rewards_saving():
    assert conversion_rate(D("1000")) == D("50.00")
    assert conversion_rate(D("2000")) == D("35.36")
    assert conversion_rate(D("4000")) == D("25.00")
    assert conversion_rate(D("10000")) == D("15.81")
    assert conversion_rate(D("100000")) == D("5.00")
    assert conversion_rate(D("10000000")) == D("5.00")

    # If earning potential grows proportionally with capital, the absolute AC
    # result keeps growing strongly. A user is not rewarded for staying small.
    capitals = [D("1000"), D("2000"), D("4000"), D("10000"), D("100000")]
    earning_capacity = [capital * conversion_rate(capital) for capital in capitals]
    assert earning_capacity == sorted(earning_capacity)


def test_conversion_burn_is_limited_to_eligible_and_boost_is_capped():
    result = conversion_preview(D("100"), D("80"), D("70"), D("1000"), D("3000"), D("12000"), D("3000"), D("15000"))
    assert result["tokens"] == D("70.00")
    assert result["base_ac"] == D("3500.00")
    assert result["boost_ac"] == D("1225.00")


def test_conversion_never_burns_tokens_beyond_rolling_cap():
    near_cap = conversion_preview(D("10"), D("10"), D("10"), D("1000"), D("100"), D("100"), D("50"), D("150"))
    assert near_cap["tokens"] == D("2.00")
    assert near_cap["base_ac"] == D("100.00")
    assert near_cap["total_ac"] == D("135.00")

    exhausted = conversion_preview(D("10"), D("10"), D("10"), D("1000"), D("100"), D("0"), D("0"), D("0"))
    assert exhausted["tokens"] == D("0.00")
    assert exhausted["total_ac"] == D("0.00")


def test_piggy_apr_is_annualized():
    assert piggy_daily_yield(D("1000"), D("0.12")) == D("0.33")
