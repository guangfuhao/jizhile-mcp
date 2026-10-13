from __future__ import annotations

import json
import logging
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

# Query-encoded contracts include secrets in the URL. Never emit HTTP wire logs.
for _logger in ("httpx", "httpcore"):
    logging.getLogger(_logger).disabled = True
    logging.getLogger(_logger).setLevel(logging.CRITICAL)

HOST = "https://www.dajiala.com"


class ApiError(Exception):
    pass


def money(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("金额必须为有限非负数")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("金额必须为有限非负数") from None
    if not result.is_finite() or result < 0:
        raise ValueError("金额必须为有限非负数")
    return result


def redact(value: Any, secrets: list[str]) -> Any:
    if isinstance(value, dict):
        return {k: "[REDACTED]" if k.lower() in {"key", "api_key", "verifycode", "token", "authorization"}
                else redact(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
    return value


class Client:
    def __init__(self, credentials: dict, transport: httpx.BaseTransport | None = None):
        self.credentials = credentials
        self.transport = transport

    def request(self, endpoint: dict, params: dict) -> dict:
        if not self.credentials.get("api_key"):
            raise ApiError("请先配置 API Key；不要把 Key 传给查询工具。")
        payload = {**params, "key": self.credentials["api_key"], "verifycode": self.credentials.get("verifycode", "")}
        kwargs: dict = {}
        if endpoint["encoding"] == "json":
            kwargs["json"] = payload
        elif endpoint["encoding"] == "form":
            # Some wxvideo contracts require multipart/form-data rather than JSON.
            kwargs["files"] = {k: (None, str(v)) for k, v in payload.items()}
        else:
            kwargs["params"] = payload
        try:
            with httpx.Client(transport=self.transport, timeout=httpx.Timeout(35, connect=10),
                              follow_redirects=False) as client:
                response = client.request(endpoint["method"], HOST + endpoint["path"], **kwargs)
            response.raise_for_status()
            if len(response.content) > 20_000_000:
                raise ApiError("响应过大；费用状态待核对，不自动重试。")
            data = response.json()
            if not isinstance(data, dict):
                raise ApiError("响应格式异常；费用状态待核对，不自动重试。")
            return redact(data, list(self.credentials.values()))
        except (httpx.HTTPError, json.JSONDecodeError, UnicodeDecodeError):
            # Exception strings can contain a credential-bearing request URL.
            raise ApiError("上游网络、HTTP 或 JSON 异常；可能已经扣费，不自动重试。") from None

    def balance(self) -> dict:
        data = self.request({"method": "POST", "encoding": "json",
                             "path": "/fbmain/monitor/v3/get_remain_money"}, {})
        if str(data.get("code")) != "0" or "remain_money" not in data:
            raise ApiError("余额查询失败；阻止付费调用。")
        try:
            balance = money(data["remain_money"])
        except ValueError:
            raise ApiError("余额格式异常；阻止付费调用。") from None
        return {"balance_yuan": str(balance), "request_time": data.get("request_time"),
                "source": "upstream_balance", "notice": "余额查询未标示费用；本次实测未扣费。业务查询通常计费。"}
