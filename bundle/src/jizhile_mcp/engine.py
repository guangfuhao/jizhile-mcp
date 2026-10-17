from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from .client import ApiError, Client, money
from .credentials import credentials
from .catalog import configured_cloud_scale, estimate, load_catalog

CATALOG = load_catalog()
UNCERTAIN_PRICES = {"unknown", "example", "tariff_snapshot", "tariff_range", "tariff_conflict"}
QUOTED_TTL = 600
CACHE_TTL = 300


class GuardError(Exception):
    pass


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def day() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()


def validate(endpoint_id: str, params: dict) -> tuple[dict, dict]:
    if endpoint_id not in CATALOG or endpoint_id == "balance":
        raise GuardError("未知查询接口；余额请使用 jizhile_balance。")
    e = CATALOG[endpoint_id]
    if e.get("availability") == "unavailable":
        raise GuardError("资费表明确标为不可用；停止调用，等待服务方确认恢复。")
    if e.get("contract_status") != "documented":
        raise GuardError("该接口已纳入资费目录，但缺少完整请求、鉴权、域名及扣费契约；需要服务方详细API文档，不能仅凭路径猜测调用。")
    if e.get("kind") == "balance":
        raise GuardError("余额请使用jizhile_balance并指定provider，不经业务执行入口。")
    if e.get("provider") == "yddm":
        from .schema import validate_cloud
        return e, validate_cloud(e, params)
    if not isinstance(params, dict) or set(params) - set(e["allowed"]):
        raise GuardError("含未文档化参数；请先查接口目录。禁止传 Key 或覆盖 API 地址。")
    for k, v in params.items():
        if isinstance(v, bool) or not isinstance(v, (str, int, float)) or len(str(v)) > 16000:
            raise GuardError("参数类型或长度不合法。")
        if isinstance(v, float):
            raise GuardError("参数不接受浮点数。")
        if k in ("object_id", "root_comment_id", "content_id", "object_nonce_id") and not isinstance(v, str):
            raise GuardError("长 ID 必须传字符串，防止精度丢失。")
    for k, v in e["fixed"].items():
        if k in params and str(params[k]) != str(v):
            raise GuardError(f"{k} 是该接口固定参数，不允许覆盖。")
    p = {**e["fixed"], **params}
    # Only safe defaults; never query a documentation example account implicitly.
    for k in ("offset", "Offset", "currentPage", "currenPage", "cookies_buffer", "last_buffer", "buffer", "page", "size", "sort_type", "publish_time_type"):
        if k in e["example_params"] and k not in p:
            p[k] = 20 if k == "size" else 1 if k in ("page", "currentPage", "currenPage") else "" if k in ("cookies_buffer", "last_buffer", "buffer") else 0
    if endpoint_id == "search_all":
        mode = str(p.get("mode", ""))
        if mode not in ("1", "2"):
            raise GuardError("search_all 必须指定 mode=1 或 mode=2。")
        if mode == "2" and str(p.get("BusinessType")) not in ("1", "2", "7", "262208", "8192"):
            raise GuardError("未知 BusinessType，无法安全报价。")
    for k in ("size", "page", "currentPage", "currenPage"):
        if k in p:
            try:
                n = int(p[k])
            except (ValueError, TypeError):
                raise GuardError(f"{k} 必须为正整数。") from None
            if n < 1 or n > (20 if k == "size" else 1000):
                raise GuardError(f"{k} 超出允许范围。")
    required = {
        "channel_videos": ["v2_name"], "channel_replays": ["v2_name"], "channel_profile": ["v2_name"],
        "channel_find_id": ["keywords"], "channel_from_link": ["feed_info"],
        "mp_owner_search_db": ["name"], "mp_owner_search_live": ["keyword"], "mp_profile": ["name"],
        "mp_related_words": ["link"], "mp_convert_link": ["link"],
        "mp_replies": ["url", "content_id"], "channel_replies": ["object_id", "root_comment_id"],
        "channel_comments": ["object_id"], "channel_title": ["object_id"],
        "channel_download": ["object_id"], "channel_download_v2": ["object_id"],
        "channel_convert_id": ["export_id"],
    }.get(endpoint_id, [])
    if "keyword" in e["allowed"] and "keyword" not in required:
        required += ["keyword"]
    if endpoint_id in ("mp_html", "mp_detail", "mp_detail_pro", "mp_detail_video", "mp_metrics", "mp_metrics_pro",
                       "mp_comments", "mp_article_info", "mp_sogou_link"):
        required += ["url"]
    if any(not str(p.get(k, "")).strip() for k in required):
        raise GuardError("缺少必要查询参数：" + ", ".join(required))
    groups = []
    if endpoint_id in ("mp_today", "mp_history", "mp_history_pro", "mp_picture_history", "picture_account_history", "mp_original_count", "mp_bound_channel"):
        groups = ["ghid", "url", "nickname"]
    if endpoint_id in ("channel_metrics", "channel_short_link"):
        groups = ["object_id", "export_id"]
    if endpoint_id in ("mp_owner", "mp_estimates"):
        groups = ["biz", "url", "wxid", "name", "ghid"]
    if groups and not any(str(p.get(k, "")).strip() for k in groups):
        raise GuardError("至少提供一个标识：" + ", ".join(groups))
    return e, p


def price(e: dict, p: dict, units_per_yuan: str | None = None) -> tuple[Decimal | None, str]:
    return estimate(e, p, units_per_yuan)


def contract_fingerprint(e: dict) -> str:
    return hashlib.sha256(canonical(e).encode()).hexdigest()


class Engine:
    def __init__(self, client: Client | None = None, state_dir: Path | None = None,
                 single: str | None = None, daily: str | None = None, reserve: str | None = None,
                 provider: str = "jizhile", budget_root: Path | None = None):
        if provider not in {"jizhile", "yddm"}:
            raise GuardError("未知数据服务provider")
        if client is None and provider == "yddm":
            from .yddm import YddmClient
            client = YddmClient()
        self.client = client or Client(credentials())
        self.provider = self.client.provider
        account = hashlib.sha256(self.client.credentials.get("api_key", "").encode()).hexdigest()[:20]
        base = Path(os.getenv("JIZHILE_STATE_DIR", "~/.local/share/jizhile-mcp")).expanduser()
        self.state_dir = state_dir or base / (("yddm-" if self.provider == "yddm" else "") + account)
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.budget_root = budget_root or (state_dir if state_dir is not None else base)
        self.budget_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = self.state_dir / "state.sqlite3"
        self.single = money(single if single is not None else os.getenv("JIZHILE_SINGLE_LIMIT", "10"))
        self.daily = money(daily if daily is not None else os.getenv("JIZHILE_DAILY_LIMIT", "500"))
        self.reserve = money(reserve if reserve is not None else os.getenv("JIZHILE_BALANCE_RESERVE", "100"))
        with self.transaction() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS quotes(id TEXT PRIMARY KEY, created REAL, body TEXT, used INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS calls(id TEXT PRIMARY KEY, day TEXT, endpoint TEXT, reserved TEXT, charged TEXT, status TEXT, created REAL);
                CREATE TABLE IF NOT EXISTS cache(id TEXT PRIMARY KEY, created REAL, body TEXT);
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
            """)
            self.unit_mismatch = False
            if self.provider == "yddm":
                units = canonical({k:self.client.credentials.get(k) for k in ("units_per_yuan", "balance_units_per_yuan")})
                previous = conn.execute("SELECT value FROM meta WHERE key='billing_units'").fetchone()
                has_calls = conn.execute("SELECT 1 FROM calls LIMIT 1").fetchone()
                self.unit_mismatch = bool(previous and previous[0] != units and has_calls)
                if not has_calls or not previous:
                    conn.execute("INSERT OR REPLACE INTO meta VALUES('billing_units',?)", (units,))

    @contextmanager
    def transaction(self):
        guard = sqlite3.connect(self.budget_root / "query-budget.sqlite3", timeout=50)
        os.chmod(self.budget_root / "query-budget.sqlite3", 0o600)
        conn = None
        try:
            guard.execute("BEGIN IMMEDIATE")  # shared lock across both query providers
            conn = sqlite3.connect(self.db, timeout=50)
            os.chmod(self.db, 0o600)
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            if conn is not None:
                conn.rollback()
            raise
        finally:
            if conn is not None:
                conn.close()
            guard.rollback()
            guard.close()

    def _spent(self, conn) -> Decimal:
        total = sum((money(r[0] or r[1]) for r in conn.execute("SELECT charged,reserved FROM calls WHERE day=?", (day(),))), Decimal("0"))
        for path in self.budget_root.glob("*/state.sqlite3"):
            if path.resolve() == self.db.resolve():
                continue
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as other:
                total += sum((money(r[0] or r[1]) for r in other.execute("SELECT charged,reserved FROM calls WHERE day=?", (day(),))), Decimal(0))
        return total

    def _check(self, conn, amount: Decimal, balance: Decimal):
        if self.unit_mismatch:
            raise GuardError("云端点换算单位与已有账本不同；先核对历史账目，不得删除账本来绕过预算。")
        if conn.execute("SELECT 1 FROM meta WHERE key='blocked'").fetchone():
            raise GuardError("有费用不确定、执行中断或超出报价的调用；先查看账本并核对后解锁。")
        if conn.execute("SELECT 1 FROM calls WHERE status IN ('inflight','uncertain')").fetchone():
            raise GuardError("存在费用待核对的调用，阻止继续扣费。")
        if amount > self.single:
            raise GuardError(f"超过单次预算 {self.single} 元。")
        if self._spent(conn) + amount > self.daily:
            raise GuardError(f"超过每日插件预算 {self.daily} 元（Asia/Shanghai）。")
        if balance - amount < self.reserve:
            raise GuardError(f"余额不足以支付并保留 {self.reserve} 元安全余额。")

    def status(self) -> dict:
        balance = self.client.balance()
        with self.transaction() as conn:
            spent = self._spent(conn)
            unresolved = conn.execute("SELECT id,endpoint,status,reserved FROM calls WHERE status IN ('inflight','uncertain','overrun')").fetchall()
            blocked = bool(conn.execute("SELECT 1 FROM meta WHERE key='blocked'").fetchone()) or bool(unresolved)
        low = money(balance["balance_yuan"]) < self.reserve if balance["balance_yuan"] is not None else None
        return {**balance, "provider": self.provider, "single_limit_yuan": str(self.single), "daily_limit_yuan": str(self.daily),
                "balance_reserve_yuan": str(self.reserve), "accounted_today_yuan": str(spent),
                "daily_available_yuan": str(max(Decimal(0), self.daily-spent)), "blocked": blocked,
                "low_balance": low, "billing_unit_mismatch": self.unit_mismatch,
                "paid_calls_allowed": not blocked and low is False and not self.unit_mismatch and spent < self.daily,
                "unresolved": [{"request_id": r[0], "endpoint": r[1], "status": r[2], "reserved_yuan": r[3]} for r in unresolved],
                "notice": "每次业务调用可能计费。预算仅约束本插件；上游未提供硬性单次扣费上限。"}

    def quote(self, endpoint_id: str, params: dict, max_cost_yuan: str | None = None, fresh: bool = False) -> dict:
        e, p = validate(endpoint_id, params)
        if e["provider"] != self.provider:
            raise GuardError("接口与Key服务不匹配；不能跨服务发送Key。")
        if self.provider == "yddm" and not self.client.credentials.get("units_confirmed"):
            raise GuardError("请在云端点本机配置页核实积分与余额换算，再执行人民币预算报价。")
        expected, basis = price(e, p, self.client.credentials.get("units_per_yuan") if self.provider == "yddm" else None)
        if basis in UNCERTAIN_PRICES and max_cost_yuan is None:
            raise GuardError("该接口价格未确认或资费存在日期、档位、来源冲突。请展示文档与资费表价格，并由用户明确给出本次预留金额后再报价。")
        cap = money(max_cost_yuan) if max_cost_yuan is not None else expected
        if cap is None or cap <= 0 or expected is not None and cap < expected:
            raise GuardError("预算必须大于零且不得低于已知/示例费用。")
        cache_key = hashlib.sha256(canonical([endpoint_id, p]).encode()).hexdigest()
        balance = self.client.balance()
        with self.transaction() as conn:
            cached = conn.execute("SELECT created FROM cache WHERE id=?", (cache_key,)).fetchone()
            hit = bool(not fresh and cached and time.time()-cached[0] <= CACHE_TTL)
            self._check(conn, Decimal(0) if hit else cap, money(balance["balance_yuan"]))
            qid = ("yddm:" if self.provider == "yddm" else "") + str(uuid.uuid4())
            q = {"quote_id": qid, "endpoint": endpoint_id, "title": e["title"], "params": p,
                 "expected_cost_yuan": str(expected) if expected is not None else None,
                 "max_cost_yuan": str(cap), "price_status": basis, "source": e["source"],
                 "planned_new_charge_yuan": "0" if hit else str(cap),
                 "balance_yuan": balance["balance_yuan"], "balance_after_reservation_yuan": str(money(balance["balance_yuan"])-(Decimal(0) if hit else cap)),
                 "cache_hit": hit, "fresh": fresh, "cache_key": cache_key, "expires_in_seconds": QUOTED_TTL,
                 "notes": e["notes"], "notice": "请向用户展示余额、费用、预留金额及价格依据，再在用户授权范围内执行。单页单次；无自动重试。上游实际扣费可能高于估计，发生时立即阻止后续调用。"}
            q.update(contract_fingerprint=contract_fingerprint(e), tariff=e.get("tariff"),
                     tariff_references=e.get("tariff_references", []),
                     legacy_unit_price_yuan=e["price_yuan"], legacy_price_status=e["price_status"],
                     legacy_billing_unit=e["billing_unit"],
                     billing_unit=e.get("tariff", {}).get("billing_unit", e["billing_unit"]))
            q.update(provider=self.provider, kind=e.get("kind", "query"),
                     billing_units={k:self.client.credentials.get(k) for k in ("units_per_yuan", "balance_units_per_yuan", "units_confirmed")} if self.provider == "yddm" else None,
                     documented_points_per_request=e.get("documented_points_per_request"))
            if e.get("kind") in {"task_submit", "task_poll"}:
                q["notice"] += " 此接口为异步任务提交/查询/验收步骤，每一步分别计费和报价；不自动轮询。"
            conn.execute("INSERT INTO quotes(id,created,body) VALUES(?,?,?)", (qid,time.time(),canonical(q)))
        return {k: v for k, v in q.items() if k != "cache_key"}

    def execute(self, quote_id: str, confirm_charge: bool = False, accept_uncertain_price: bool = False) -> dict:
        if not confirm_charge:
            raise GuardError("需要费用已告知且用户已授权：confirm_charge=true。")
        # A process-wide SQLite write lock serializes all instances for this Key.
        with self.transaction() as conn:
            row = conn.execute("SELECT created,body,used FROM quotes WHERE id=?", (quote_id,)).fetchone()
            if not row or row[2] or time.time()-row[0] > QUOTED_TTL:
                raise GuardError("报价不存在、已使用或已过期；不重复提交。")
            q = json.loads(row[1]); e = CATALOG[q["endpoint"]]
            if e["provider"] != self.provider or q.get("provider") != self.provider:
                raise GuardError("报价所属服务与当前账本不匹配")
            if self.provider == "yddm" and q.get("billing_units") != {k:self.client.credentials.get(k) for k in ("units_per_yuan", "balance_units_per_yuan", "units_confirmed")}:
                raise GuardError("计费换算配置已变化；请重新报价。")
            if q.get("contract_fingerprint") != contract_fingerprint(e):
                raise GuardError("接口或资费目录已更新；旧报价失效，请重新报价并展示费用。")
            validate(q["endpoint"], q["params"])
            if q["price_status"] in UNCERTAIN_PRICES and not accept_uncertain_price:
                raise GuardError("价格不确定，用户明确接受后才可 accept_uncertain_price=true。")
            cached = conn.execute("SELECT created,body FROM cache WHERE id=?", (q["cache_key"],)).fetchone()
            if not q["fresh"] and cached and time.time()-cached[0] <= CACHE_TTL:
                balance = self.client.balance()
                conn.execute("UPDATE quotes SET used=1 WHERE id=?", (quote_id,))
                return {"ok": True, "cached": True, "cached_at_unix": cached[0], "age_seconds": round(time.time()-cached[0]),
                        "data": json.loads(cached[1]), "billing": {"charged_yuan": "0", **balance},
                        "notice": "返回5分钟内缓存，本次业务查询未调用上游，不产生新的业务查询费。"}
            if q["cache_hit"]:
                raise GuardError("报价时缓存现已过期；重新报价并展示费用后执行。")
            balance = self.client.balance(); before = money(balance["balance_yuan"]); cap = money(q["max_cost_yuan"])
            self._check(conn, cap, before)
            # Commit the durable reservation BEFORE network I/O. A crash remains fail-closed.
            conn.execute("UPDATE quotes SET used=1 WHERE id=?", (quote_id,))
            conn.execute("INSERT INTO calls VALUES(?,?,?,?,?,?,?)", (quote_id,day(),q["endpoint"],str(cap),None,"inflight",time.time()))
            conn.commit(); conn.execute("BEGIN IMMEDIATE")
            # Another process may observe inflight but cannot create a second paid call.
            try:
                data = self.client.request(e, q["params"])
            except Exception:
                conn.execute("UPDATE calls SET status='uncertain' WHERE id=?", (quote_id,))
                conn.execute("INSERT OR REPLACE INTO meta VALUES('blocked',?)", (quote_id,))
                return {"ok": False, "request_id": quote_id, "status": "uncertain", "billing": {"reserved_yuan": str(cap), "charged_yuan": None},
                        "notice": "上游请求失败，可能已扣费；预算按预留金额占用，已阻止后续付费请求，不自动重试。请核对账单。"}
            actual = remaining = None
            try:
                actual, remaining = self.client.billing(data)
            except ValueError:
                pass
            ok = str(data.get("code")) == "0"
            status = "ok" if ok else "upstream_error"
            if actual is None: status = "uncertain"
            if actual is not None and actual > cap: status = "overrun"
            conn.execute("UPDATE calls SET charged=?,status=? WHERE id=?", (str(actual) if actual is not None else None,status,quote_id))
            if status in ("uncertain", "overrun"):
                conn.execute("INSERT OR REPLACE INTO meta VALUES('blocked',?)", (quote_id,))
            if remaining is None:
                try: remaining = money(self.client.balance()["balance_yuan"])
                except ApiError: pass
            if ok and actual is not None and status != "overrun":
                # Historical billing fields are excluded so a cache hit cannot look like a new charge.
                content = self.client.cache_content(data)
                conn.execute("INSERT OR REPLACE INTO cache VALUES(?,?,?)", (q["cache_key"],time.time(),canonical(content)))
            return {"ok": ok, "cached": False, "request_id": quote_id, "status": status, "data": data,
                    "billing": {"provider": self.provider, "billing_units": q.get("billing_units"), "price_status": q["price_status"], "expected_cost_yuan": q["expected_cost_yuan"],
                                "reserved_yuan": str(cap), "charged_yuan": str(actual) if actual is not None else None,
                                "balance_before_yuan": str(before), "balance_after_yuan": str(remaining) if remaining is not None else None,
                                "accounted_today_yuan": str(self._spent(conn))},
                    "notice": f"请向用户报告本次实际扣费和最新余额。失败响应也检查费用；余额低于安全预留金额{self.reserve}元请提醒。" +
                              ("费用不确定或超过预留，已阻止后续付费调用。" if status in ("uncertain", "overrun") else "")}

    def resolve(self, request_id: str, verified_charge_yuan: str, confirm_user_verified: bool = False) -> dict:
        if not confirm_user_verified:
            raise GuardError("请用户核对上游账单并提供该次真实扣费；不能仅凭余额差额推断。")
        charge = money(verified_charge_yuan)
        balance = self.client.balance()
        with self.transaction() as conn:
            row = conn.execute("SELECT status FROM calls WHERE id=?", (request_id,)).fetchone()
            if not row or row[0] not in ("inflight", "uncertain", "overrun"):
                raise GuardError("没有对应的待核对记录。")
            conn.execute("UPDATE calls SET charged=?,status='reconciled' WHERE id=?", (str(charge),request_id))
            if not conn.execute("SELECT 1 FROM calls WHERE status IN ('inflight','uncertain','overrun')").fetchone():
                conn.execute("DELETE FROM meta WHERE key='blocked'")
        return {"reconciled": True, "verified_charge_yuan": str(charge), **balance}


def recommend(intent: str, require_live: bool = True, has_identifier: bool = False,
              candidates: list[str] | None = None) -> dict:
    routes = {
        "mp_accounts": ["mp_search_accounts", "mp_search_db"],
        "mp_articles": ["mp_search_articles", "mp_search_articles_category"],
        "mp_history": ["mp_history", "mp_history_pro"],
        "mp_today": ["mp_today", "mp_history"],
        "mp_content": ["mp_html", "mp_detail_pro", "mp_detail", "mp_detail_video"],
        "mp_metrics": ["mp_metrics", "mp_metrics_pro", "mp_article_info"],
        "mp_owner_accounts": ["mp_owner_search_live", "mp_owner_search_db"],
        "channel_accounts": ["channel_find_id", "channel_search_accounts"],
        "channel_videos": ["channel_videos"] if has_identifier else ["channel_search_videos", "channel_search_videos_category"],
        "channel_download": ["channel_download", "channel_download_v2"],
        "channel_metrics": ["channel_metrics", "channel_download"],
    }
    if candidates is not None:
        if not 1 <= len(candidates) <= 30 or any(k not in CATALOG or k == "balance" for k in candidates):
            raise GuardError("candidates须为1至30个目录接口ID。")
        routes[intent] = list(dict.fromkeys(candidates))
    if intent not in routes:
        raise GuardError("未知需求；可先查目录，再提供candidates接口ID列表比较参考费用。")
    options = []
    cloud_scale = configured_cloud_scale()
    for id in routes[intent]:
        e = CATALOG[id]
        n, status = price(e, e["example_params"], cloud_scale if e["provider"] == "yddm" else None)
        eligible = (not require_live or e["freshness"] == "live") and (intent != "mp_today" or id == "mp_today") and e["contract_status"] == "documented" and e["availability"] == "available"
        options.append({"endpoint": id,"title": e["title"],"estimated_yuan": str(n) if n is not None else None,
                        "price_status": status,"freshness": e["freshness"], "eligible": eligible,
                        "source": e["source"], "notes": e["notes"], "tariff": e.get("tariff"),
                        "contract_status": e["contract_status"], "availability": e["availability"],
                        "billing_unit": e.get("tariff", {}).get("billing_unit", e["billing_unit"])})
    # No unconditional recommendation between non-equivalent outputs or unconfirmed tariffs.
    eligible = [x for x in options if x["eligible"] and x["estimated_yuan"] is not None]
    suggested = min(eligible, key=lambda x: money(x["estimated_yuan"]))["endpoint"] if eligible else None
    caveats = {"mp_today": "历史列表与当天发文窗口不同；查当天应使用mp_today，不能只按价格替换。",
               "mp_content": "HTML、纯文本、Pro、可下载视频字段不完全等价；先确认所需输出。",
               "mp_metrics": "基础阅读/点赞/在看无需升级Pro；转发收藏评论才比较Pro。",
               "channel_accounts": "精确名称定位单个视频号可考虑find_id；发现多个账号用search_accounts。find_id价格仅为示例。",
               "channel_metrics": "两接口字段与标识要求不同；优先复用已有列表互动信息，避免再次收费。",
               "channel_download": "下载接口覆盖和时效不同；旧版失败不得自动升级V2。"}
    return {"intent": intent,"options": options,"lowest_estimate": suggested,
            "notice": caveats.get(intent, "按需求与实时性筛选后比较费用；优先复用结果中的ID、列表和已有字段。") +
                      " 日期为2026-03-05的资费表是参考快照；条件价按高档、来源冲突按较高预留比较。不得将未确认价格当固定单价；候选输出不一定等价。本工具不执行业务请求。"}
