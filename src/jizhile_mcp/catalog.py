"""Merge documented request contracts with a traceable, non-executable tariff sheet.

A price list cannot establish authentication, server addresses or body schemas.
Missing contracts stay discoverable but must never reach the HTTP client.
"""
from __future__ import annotations

import json
import re
from decimal import Decimal
from importlib.resources import files
from urllib.parse import urlsplit

from .client import money

SNAPSHOT = json.loads(files("jizhile_mcp").joinpath("tariff_snapshot.json").read_text())
CLOUD_SOURCE = json.loads(files("jizhile_mcp").joinpath("cloud_contracts.json").read_text())
CLOUD_CONTRACTS = CLOUD_SOURCE["contracts"]

# The workbook reuses paths for distinct operations (wxvideo type, web_search mode).
# Row numbers are mapped explicitly instead of guessing the operation from its URL.
MAIN_IDS = """balance mp_today mp_history mp_history_pro mp_picture_history picture_account_history
mp_metrics mp_metrics_pro mp_convert_link mp_detail mp_html mp_detail_pro mp_detail_video
mp_original_count mp_owner mp_comments mp_replies mp_profile mp_estimates mp_owner_search_live
mp_owner_search_db mp_search_db mp_article_info mp_search_articles mp_search_articles_category
search_miniapps search_wx_index search_all search_suggestions mp_sogou_link mp_convert_link
channel_videos channel_replays channel_title channel_metrics channel_comments channel_replies
channel_from_link channel_download channel_convert_id channel_find_id channel_short_link
channel_search_videos channel_search_videos_category channel_search_accounts mp_bound_channel channel_profile""".split()
REPEAT_IDS = MAIN_IDS[:4] + MAIN_IDS[6:]


def reference(record: dict) -> dict:
    return {"sheet": record["sheet"], "row": record["row"], "number": record["number"],
            "title": record["title"], "tariff": record["tariff"], "raw_path": record["raw_path"]}


def tariff_values(text: str) -> list[str]:
    if text == "免费":
        return ["0"]
    return sorted(set(re.findall(r"([0-9]+(?:\.[0-9]+)?)\s*元", text)), key=Decimal)


def configured_cloud_scale() -> str | None:
    from .yddm import credentials
    settings = credentials()
    if settings.get("units_confirmed"):
        try:
            scale = money(settings["units_per_yuan"])
            return str(scale) if scale > 0 else None
        except ValueError:
            pass
    return None


def load_catalog() -> dict:
    catalog = json.loads(files("jizhile_mcp").joinpath("catalog.json").read_text())
    for key, endpoint in catalog.items():
        endpoint.update(contract_status="documented", availability="available", tariff_references=[], provider="jizhile",
                        platform="channel" if key.startswith("channel_") else "search" if key.startswith("search_")
                        else "account" if key == "balance" else "mp")
    by_path = {}
    for record in SNAPSHOT["records"]:
        sheet, number, raw_path = record["sheet"], record["number"], record["raw_path"]
        if sheet == "全媒体" and number <= len(MAIN_IDS):
            key = MAIN_IDS[number - 1]
        elif sheet == "Sheet3":
            key = REPEAT_IDS[number - 1]
        else:
            parsed = urlsplit(raw_path)
            path = parsed.path
            identity = (record["method"], path)
            # The sheet gives query and submit the same PDD URL. Keep both visible;
            # neither may execute without the provider clarifying the contract.
            if sheet == "电商" and number in (1, 2):
                key = "pdd_comment_task_result" if number == 1 else "pdd_comment_task_submit"
            else:
                key = by_path.get(identity) or path.strip("/").replace("/", "_").lower()
                by_path[identity] = key
            if key not in catalog:
                unavailable = "不可用" in record["title"]
                catalog[key] = {
                    "title": record["title"], "path": path, "method": record["method"],
                    "encoding": None, "fixed": {}, "example_params": {}, "allowed": [],
                    "price_yuan": None, "price_status": "unknown", "billing_unit": "request",
                    "source": "workbook:tariff_snapshot.json", "freshness": "unverified",
                    "platform": path.strip("/").split("/")[0].lower(),
                    "contract_status": "missing", "availability": "unavailable" if unavailable else "unverified",
                    "host_in_source": f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else None,
                    "tariff_references": [],
                    "notes": ["仅有资费表，缺少请求参数、编码、鉴权、正式域名、余额及扣费响应契约；禁止付费调用。"]
                             + (["资费表明确标为不可用。"] if unavailable else [])
                }
                catalog[key]["provider"] = "yddm"
        endpoint = catalog[key]
        endpoint["tariff_references"].append(reference(record))
        # Sheet3 is a repeated subset; the primary sheets own the rate snapshot.
        if sheet != "Sheet3":
            rates = tariff_values(record["tariff"])
            endpoint["tariff"] = {
                "unit_prices_yuan": rates, "billing_unit": "item" if "元/条" in record["tariff"] else "request",
                "price_date": SNAPSHOT["price_date"], "imported_date": SNAPSHOT["imported_date"],
                "source_name": SNAPSHOT["source_name"], "sheet": sheet, "row": record["row"],
                "raw": record["tariff"], "conditional": len(rates) > 1,
            }
    cloud_by_path = {e["path"]: key for key, e in catalog.items() if e["provider"] == "yddm" and key != "pdd_comment_task_result"}
    for path, contract in CLOUD_CONTRACTS.items():
        if path == "/users/me":
            key = "yddm_balance"
        elif path == "/pdd/async_get_comment_task":
            key = "pdd_comment_task_result"
        else:
            key = cloud_by_path.get(path) or path.strip("/").replace("/", "_").lower()
        if key not in catalog:
            catalog[key] = {"price_yuan": None, "price_status": "unknown", "billing_unit": "request",
                            "platform": path.strip("/").split("/")[0].lower(),
                            "availability": "available", "tariff_references": [], "notes": []}
        e = catalog[key]
        previous_path = e.get("path")
        e.update(contract, contract_status="documented", freshness="live")
        e["notes"] = [n for n in e["notes"] if not n.startswith("仅有资费表")]
        e["notes"].extend(contract.get("contract_notes", []))
        if e.get("availability") == "unverified":
            e["availability"] = "available"
        if previous_path and previous_path != path:
            e["notes"].append("资费表路径已按新官方文档纠正；原始路径保留在tariff_references。")
        if contract["schema_basis"] == "documented_example":
            e["notes"].append("文档schema为空，字段类型取自官方请求示例；不填入任何示例目标。")
        if contract["deprecated"]:
            e["availability"] = "unavailable"
        if key == "yddm_balance":
            e.update(price_yuan="0", price_status="balance_probe", kind="balance", platform="account")
    for e in catalog.values():
        if e["contract_status"] == "missing":
            e["availability"] = "not_in_current_docs"
            e["notes"] = ["资费表所列旧路径未出现在2026-10-17读取的新文档；保留来源记录并拦截，不自动替换为相似版本。"]
    return catalog


def estimate(endpoint: dict, params: dict, units_per_yuan: str | None = None) -> tuple[Decimal | None, str]:
    status = endpoint["price_status"]
    if status == "dynamic":
        old = Decimal("0.5") if str(params.get("mode")) == "1" or str(params.get("BusinessType")) in ("2", "8192") else Decimal("1")
        status = "documented"
    else:
        old = money(endpoint["price_yuan"]) if endpoint["price_yuan"] is not None else None
        if old is not None and endpoint["billing_unit"] == "item":
            old *= max(20, int(params.get("size", 20)))
    tariff = endpoint.get("tariff")
    if not tariff or not tariff["unit_prices_yuan"]:
        if endpoint.get("documented_points_per_request") is not None and units_per_yuan is not None:
            return money(endpoint["documented_points_per_request"]) / money(units_per_yuan), "documented_points"
        return old, status
    # Reserve the higher conditional rate; do not infer a cheaper long-link tier.
    amount = max(map(money, tariff["unit_prices_yuan"]))
    if tariff["billing_unit"] == "item":
        amount *= max(20, int(params.get("size", 20)))
    if status == "balance_probe":
        return Decimal(0), status
    if endpoint.get("documented_points_per_request") is not None and units_per_yuan is not None:
        live_price = money(endpoint["documented_points_per_request"]) / money(units_per_yuan)
        return max(amount, live_price), "documented_points" if amount == live_price else "tariff_conflict"
    conflict = old is not None and (old != amount or endpoint["billing_unit"] != tariff["billing_unit"])
    if conflict:
        return max(amount, old), "tariff_conflict"
    if tariff["conditional"]:
        return amount, "tariff_range"
    # A matching documented rate remains documented; a dated sheet alone is not
    # evidence of the account's current tariff, so all other cases need a cap.
    return amount, "documented" if status == "documented" else "tariff_snapshot"


def summary(catalog: dict) -> dict:
    return {"operations": len(catalog), "documented_contracts": sum(e["contract_status"] == "documented" for e in catalog.values()),
            "missing_contracts": sum(e["contract_status"] == "missing" for e in catalog.values()),
            "unavailable": sum(e["availability"] == "unavailable" for e in catalog.values()),
            "callable_contracts": sum(e["contract_status"] == "documented" and e["availability"] == "available" for e in catalog.values()),
            "cloud_contracts": len(CLOUD_CONTRACTS), "cloud_retrieved_date": CLOUD_SOURCE["retrieved_date"],
            "workbook_records": len(SNAPSHOT["records"]),
            "primary_records": sum(r["sheet"] != "Sheet3" for r in SNAPSHOT["records"]),
            "price_date": SNAPSHOT["price_date"], "imported_date": SNAPSHOT["imported_date"]}
