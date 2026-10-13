import httpx
import pytest

from jizhile_mcp.client import Client, money
from jizhile_mcp.engine import Engine, GuardError, day
from test_guards import Upstream


@pytest.fixture
def defaults(tmp_path, monkeypatch):
    for name in ("JIZHILE_SINGLE_LIMIT", "JIZHILE_DAILY_LIMIT", "JIZHILE_BALANCE_RESERVE"):
        monkeypatch.delenv(name, raising=False)
    upstream = Upstream(balance="1000", cost="10")
    client = Client({"api_key": "MOCK-KEY", "verifycode": ""}, httpx.MockTransport(upstream.handle))
    return upstream, Engine(client, tmp_path)


def test_ten_yuan_allowed_and_single_overage_blocked(defaults):
    upstream, engine = defaults
    quote = engine.quote("mp_search_articles", {"keyword": "boundary"}, "10")
    result = engine.execute(quote["quote_id"], True)
    assert result["billing"]["charged_yuan"] == "10"
    with pytest.raises(GuardError, match="单次预算 10 元"):
        engine.quote("mp_search_articles", {"keyword": "over-limit"}, "10.01")
    assert upstream.paid == 1


def test_daily_five_hundred_boundary(defaults):
    upstream, engine = defaults
    with engine.transaction() as conn:
        conn.execute("INSERT INTO calls VALUES(?,?,?,?,?,?,?)",
                     ("earlier-mock-calls", day(), "mp_search_articles", "490", "490", "ok", 0))
    quote = engine.quote("mp_search_articles", {"keyword": "last-ten"}, "10")
    engine.execute(quote["quote_id"], True)
    assert engine.status()["accounted_today_yuan"] == "500"
    with pytest.raises(GuardError, match="每日插件预算 500 元"):
        engine.quote("mp_search_articles", {"keyword": "over-daily-budget"})
    assert upstream.paid == 1


@pytest.mark.parametrize("balance,allowed", [("100.50", True), ("100.49", False), ("100", False), ("99.99", False)])
def test_reserve_boundary_blocks_before_paid_query(defaults, balance, allowed):
    upstream, engine = defaults
    upstream.balance = money(balance)
    upstream.cost = "0.5"
    if allowed:
        quote = engine.quote("mp_search_articles", {"keyword": "reserve-boundary"})
        result = engine.execute(quote["quote_id"], True)
        assert result["billing"]["balance_after_yuan"] == "100.00"
        assert upstream.paid == 1
    else:
        with pytest.raises(GuardError, match="保留 100 元"):
            engine.quote("mp_search_articles", {"keyword": "reserve-boundary"})
        assert upstream.paid == 0


def test_execution_rechecks_reserve_after_quote(defaults):
    upstream, engine = defaults
    upstream.balance = money("110")
    quote = engine.quote("mp_search_articles", {"keyword": "balance-changes"}, "10")
    upstream.balance = money("109.99")
    with pytest.raises(GuardError, match="保留 100 元"):
        engine.execute(quote["quote_id"], True)
    assert upstream.paid == 0


def test_status_and_warning_follow_new_reserve(defaults):
    upstream, engine = defaults
    status = engine.status()
    assert (status["single_limit_yuan"], status["daily_limit_yuan"], status["balance_reserve_yuan"]) == ("10", "500", "100")
    upstream.balance = money("99")
    assert engine.status()["low_balance"]
    upstream.balance = money("100")
    assert not engine.status()["low_balance"]


def test_explicit_environment_overrides_still_take_precedence(defaults, monkeypatch):
    upstream, original = defaults
    monkeypatch.setenv("JIZHILE_SINGLE_LIMIT", "12")
    monkeypatch.setenv("JIZHILE_DAILY_LIMIT", "600")
    monkeypatch.setenv("JIZHILE_BALANCE_RESERVE", "80")
    engine = Engine(original.client, original.state_dir)
    quote = engine.quote("mp_search_articles", {"keyword": "configured-limits"}, "12")
    assert quote["max_cost_yuan"] == "12"
    status = engine.status()
    assert (status["single_limit_yuan"], status["daily_limit_yuan"], status["balance_reserve_yuan"]) == ("12", "600", "80")
    assert upstream.paid == 0
