from __future__ import annotations

import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from jizhile_mcp.client import ApiError, Client, money
from jizhile_mcp.engine import CATALOG, Engine, GuardError, recommend, validate


class Upstream:
    def __init__(self, balance="5.1", cost="0.5", code=0):
        self.balance = money(balance); self.cost = cost; self.code = code
        self.paid = 0; self.fail = False; self.drop_cost = False; self.requests = []

    def handle(self, request):
        self.requests.append(request)
        if request.url.path.endswith("get_remain_money"):
            return httpx.Response(200, json={"code": 0,"remain_money": str(self.balance)})
        self.paid += 1
        if self.fail: raise httpx.ReadTimeout("SENSITIVE-KEY must not appear")
        self.balance -= money(self.cost)
        data = {"code": self.code,"cost_money": self.cost,"remain_money": str(self.balance),"data": [{"title":"test"}]}
        if self.drop_cost: del data["cost_money"]
        return httpx.Response(200, json=data)


@pytest.fixture
def setup(tmp_path):
    u = Upstream()
    c = Client({"api_key":"SENSITIVE-KEY","verifycode":"PRIVATE"}, httpx.MockTransport(u.handle))
    # These cases exercise configurable limits independently of release defaults.
    return u, Engine(c,tmp_path,single="1",daily="2",reserve="1")


def test_paid_requires_quote_and_confirmation(setup):
    u,e = setup
    with pytest.raises(GuardError): e.execute("invented")
    with pytest.raises(GuardError): e.execute("invented",True)
    q=e.quote("mp_search_articles",{"keyword":"test"})
    assert u.paid == 0
    with pytest.raises(GuardError): e.execute(q["quote_id"])
    assert u.paid == 0


def test_charge_cache_and_one_time_quote(setup):
    u,e=setup
    q=e.quote("mp_search_articles",{"keyword":"test"})
    result=e.execute(q["quote_id"],True)
    assert result["billing"]["charged_yuan"]=="0.5"
    assert result["billing"]["balance_after_yuan"]=="4.6"
    with pytest.raises(GuardError): e.execute(q["quote_id"],True)
    q=e.quote("mp_search_articles",{"keyword":"test"})
    assert q["cache_hit"]
    cached=e.execute(q["quote_id"],True)
    assert cached["billing"]["charged_yuan"]=="0"
    assert "cost_money" not in cached["data"]
    assert u.paid==1


def test_expired_quote_and_cache_do_not_spend(setup):
    u,e=setup
    q=e.quote("mp_search_articles",{"keyword":"test"})
    with e.transaction() as db: db.execute("UPDATE quotes SET created=0")
    with pytest.raises(GuardError):e.execute(q["quote_id"],True)
    assert u.paid==0
    q=e.quote("mp_search_articles",{"keyword":"test"});e.execute(q["quote_id"],True)
    q=e.quote("mp_search_articles",{"keyword":"test"})
    with e.transaction() as db: db.execute("UPDATE cache SET created=0")
    with pytest.raises(GuardError):e.execute(q["quote_id"],True)
    assert u.paid==1


def test_concurrent_same_quote_only_one_request(setup):
    u,e=setup;q=e.quote("mp_search_articles",{"keyword":"test"})
    def run():
        try:return e.execute(q["quote_id"],True)
        except GuardError:return {"blocked":True}
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(lambda _:run(),range(2)))
    assert u.paid==1
    assert sum(r.get("blocked",False) for r in results)==1


def test_concurrent_distinct_quotes_obey_daily_budget(setup):
    u,e=setup;e.daily=money("0.5")
    qs=[e.quote("mp_search_articles",{"keyword":str(i)}) for i in range(2)]
    def run(q):
        try:return e.execute(q["quote_id"],True)
        except GuardError:return {"blocked":True}
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(run,qs))
    assert u.paid==1
    assert sum(r.get("blocked",False) for r in results)==1


@pytest.mark.parametrize("limit,balance,reserve",[("0.4","5.1","1"),("1","1.4","1")])
def test_limits_block_before_charge(setup,limit,balance,reserve):
    u,e=setup;e.single=money(limit);u.balance=money(balance);e.reserve=money(reserve)
    with pytest.raises(GuardError):e.quote("mp_search_articles",{"keyword":"test"})
    assert u.paid==0


def test_db_search_reserves_full_page_even_size_one(setup):
    u,e=setup
    with pytest.raises(GuardError):e.quote("mp_search_db",{"keyword":"test","size":1})
    assert u.paid==0


def test_price_uncertainty_requires_explicit_cap_and_acceptance(setup):
    u,e=setup
    with pytest.raises(GuardError):e.quote("channel_find_id",{"keywords":"test"})
    q=e.quote("channel_find_id",{"keywords":"test"},"0.3")
    with pytest.raises(GuardError):e.execute(q["quote_id"],True)
    assert u.paid==0


@pytest.mark.parametrize("failure",["timeout","missing_cost","overrun"])
def test_uncertain_or_overrun_blocks_future_calls(setup,failure):
    u,e=setup
    u.fail=failure=="timeout";u.drop_cost=failure=="missing_cost"
    if failure=="overrun":u.cost="0.7"
    q=e.quote("mp_search_articles",{"keyword":"test"});r=e.execute(q["quote_id"],True)
    assert r["status"] in ("uncertain","overrun")
    with pytest.raises(GuardError):e.quote("mp_search_articles",{"keyword":"next"})
    assert u.paid==1
    with pytest.raises(GuardError):e.resolve(q["quote_id"],"0")
    e.resolve(q["quote_id"],"0.7" if failure=="overrun" else "0.5",True)
    assert not e.status()["blocked"]


def test_charged_error_is_not_cached_or_retried(setup):
    u,e=setup;u.code=101
    r=e.execute(e.quote("mp_search_articles",{"keyword":"test"})["quote_id"],True)
    assert not r["ok"] and r["billing"]["charged_yuan"]=="0.5"
    assert e.status()["accounted_today_yuan"]=="0.5"
    assert u.paid==1


def test_crash_reservation_blocks_next_engine(setup):
    u,e=setup
    with e.transaction() as db: db.execute("INSERT INTO calls VALUES('crashed','2000-01-01','mp_search_articles','0.5',NULL,'inflight',0)")
    other=Engine(e.client,e.state_dir)
    with pytest.raises(GuardError):other.quote("mp_search_articles",{"keyword":"test"})
    assert u.paid==0


@pytest.mark.parametrize("params",[{"key":"bad"},{"keyword":"test","mode":2},{"keyword":""},{"keyword":"test","currentPage":0},{"keyword":"test","currentPage":True}])
def test_invalid_params_block(setup,params):
    u,e=setup
    with pytest.raises(GuardError):e.quote("mp_search_articles",params)
    assert u.paid==0


def test_large_ids_require_string():
    with pytest.raises(GuardError):validate("channel_comments",{"object_id":14462543356698040491})
    _,p=validate("channel_comments",{"object_id":"14462543356698040491"})
    assert p["object_id"]=="14462543356698040491"


def test_credentials_are_redacted_and_errors_generic():
    key="SENSITIVE-KEY"
    c=Client({"api_key":key,"verifycode":"PRIVATE"},httpx.MockTransport(lambda r:httpx.Response(200,json={"key":key,"msg":"oops "+key})))
    assert key not in json.dumps(c.request(CATALOG["balance"],{}))
    def error(r):raise httpx.ReadTimeout("URL key="+key)
    c.transport=httpx.MockTransport(error)
    with pytest.raises(ApiError) as exc:c.request(CATALOG["balance"],{})
    assert key not in str(exc.value)


@pytest.mark.parametrize("encoding,method",[("json","POST"),("form","POST"),("query","POST"),("query","GET")])
def test_documented_request_encoding(encoding,method):
    seen=[]
    c=Client({"api_key":"secret","verifycode":""},httpx.MockTransport(lambda r:(seen.append(r) or httpx.Response(200,json={"code":0}))))
    c.request({"encoding":encoding,"method":method,"path":"/fbmain/monitor/v3/wxvideo"},{"type":1})
    req=seen[0];assert req.method==method
    if encoding=="json":assert json.loads(req.content)["type"]==1
    if encoding=="form":assert "multipart/form-data" in req.headers["content-type"]
    if encoding=="query":assert req.url.params["type"]=="1"


def test_cheapest_only_with_freshness_and_scope():
    r=recommend("mp_accounts");assert r["lowest_estimate"]=="mp_search_accounts"
    r=recommend("channel_videos");assert r["lowest_estimate"]=="channel_search_videos"
    assert recommend("mp_today")["lowest_estimate"]=="mp_today"
    assert len(CATALOG)==303
    assert CATALOG["channel_search_videos_category"]["fixed"]["BusinessType"]==7


@pytest.mark.parametrize("value",["NaN","Infinity","-1",True,None])
def test_invalid_money(value):
    with pytest.raises(ValueError):money(value)
