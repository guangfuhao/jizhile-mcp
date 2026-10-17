"""Cloud Point credentials and billing adapter, separate from WeChat and Ark."""
from __future__ import annotations

import getpass
import json
import os
import tempfile
from pathlib import Path
from decimal import Decimal

import httpx

from .client import ApiError, Client, money, redact

HOST = "https://api.yddm.com"


class YddmClient(Client):
    provider = "yddm"

    def __init__(self, credentials: dict | None = None, transport: httpx.BaseTransport | None = None):
        super().__init__(credentials if credentials is not None else globals()["credentials"](), transport)

    def request(self, endpoint: dict, params: dict) -> dict:
        if not self.credentials.get("api_key"):
            raise ApiError("请先通过云端点本机配置页保存独立X-API-Key；不会使用极致了或火山Key代替。")
        if endpoint["path"] != "/users/me":
            from .catalog import CLOUD_CONTRACTS
            contract = CLOUD_CONTRACTS.get(endpoint["path"])
            if not contract or endpoint.get("contract_status") != "documented" or endpoint.get("availability") != "available" or endpoint["method"] != contract["method"]:
                raise ApiError("云端点请求不在已验证契约目录内；阻止发送Key。")
            from .schema import validate_cloud
            params = validate_cloud(contract, params, wire=True)
        elif endpoint["method"] != "GET" or params:
            raise ApiError("余额入口只允许GET /users/me，无业务参数。")
        if endpoint["path"] != "/users/me" and not self.credentials.get("units_confirmed"):
            raise ApiError("云端点积分/余额换算未核实；请在本机配置页确认后再付费。")
        try:
            with httpx.Client(transport=self.transport, trust_env=False, follow_redirects=False,
                              timeout=httpx.Timeout(45, connect=10)) as client:
                kwargs = {"json": params} if endpoint["path"] != "/users/me" else {}
                response = client.request(endpoint["method"], HOST + endpoint["path"],
                    headers={"X-API-Key": self.credentials["api_key"]}, **kwargs)
            response.raise_for_status()
            if len(response.content) > 20_000_000:
                raise ApiError("云端点响应过大；可能已计费，不自动重试。")
            data = response.json()
            if not isinstance(data, dict):
                raise ApiError("云端点响应不是对象；可能已计费，不自动重试。")
            return redact(data, [self.credentials["api_key"]])
        except (httpx.HTTPError, json.JSONDecodeError, UnicodeDecodeError):
            raise ApiError("云端点网络、HTTP或JSON异常；可能已计费，不自动重试。") from None

    def balance(self) -> dict:
        data = self.request({"path": "/users/me", "method": "GET"}, {})
        if str(data.get("code")) != "0" or not isinstance(data.get("data"), dict) or "balance_cents" not in data["data"]:
            raise ApiError("云端点个人信息/余额查询失败；请检查云端点独立Key，禁止付费。")
        raw = money(data["data"]["balance_cents"])
        confirmed = self.credentials.get("units_confirmed", False)
        scale = money(self.credentials.get("balance_units_per_yuan", "1000"))
        if scale <= 0:
            raise ApiError("云端点余额换算不合法。")
        return {"provider": "yddm", "balance_yuan": str(raw / scale) if confirmed else None,
                "raw_balance_units": str(raw), "balance_units_per_yuan": str(scale),
                "units_confirmed": bool(confirmed), "source": "GET /users/me: data.balance_cents",
                "notice": "仅返回余额，个人信息及Key不输出。人民币换算基于用户在本机确认的单位。"}

    def billing(self, data: dict) -> tuple[Decimal | None, Decimal | None]:
        scale = money(self.credentials["units_per_yuan"])
        if not self.credentials.get("units_confirmed") or scale <= 0:
            return None, None
        body = data.get("data", {})
        if not isinstance(body, dict):
            return None, None
        cost = money(body["cost"]) / scale if body.get("cost") is not None else None
        balance = money(body["balance"]) / scale if body.get("balance") is not None else None
        return cost, balance

    def cache_content(self, data: dict) -> dict:
        content = json.loads(json.dumps(data))
        if isinstance(content.get("data"), dict):
            for key in ("cost", "balance"):
                content["data"].pop(key, None)
        return content


def config_path() -> Path:
    return Path(os.getenv("JIZHILE_YDDM_CONFIG_FILE", "~/.config/jizhile-mcp/yddm-credentials.json")).expanduser()


def credentials() -> dict:
    try:
        raw = json.loads(config_path().read_text())
    except (OSError, ValueError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    return {"api_key": os.getenv("JIZHILE_YDDM_API_KEY") or raw.get("api_key", ""),
            "units_per_yuan": os.getenv("JIZHILE_YDDM_UNITS_PER_YUAN") or raw.get("units_per_yuan", "1000"),
            "balance_units_per_yuan": os.getenv("JIZHILE_YDDM_BALANCE_UNITS_PER_YUAN") or raw.get("balance_units_per_yuan", "1000"),
            "units_confirmed": os.getenv("JIZHILE_YDDM_UNITS_CONFIRMED", str(raw.get("units_confirmed", False))).lower() == "true"}


def save_credentials(api_key: str, units_per_yuan: str = "1000", balance_units_per_yuan: str = "1000",
                     units_confirmed: bool = False) -> None:
    if not isinstance(api_key, str) or not api_key.strip() or len(api_key) > 256 or any(c in api_key for c in "\r\n"):
        raise ValueError("云端点Key为空或格式不合法")
    expense, balance = money(units_per_yuan), money(balance_units_per_yuan)
    if expense <= 0 or balance <= 0 or expense > 1_000_000 or balance > 1_000_000:
        raise ValueError("计费和余额换算单位须为正数且不大于1000000")
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w") as out:
            json.dump({"api_key": api_key.strip(), "units_per_yuan": str(expense),
                       "balance_units_per_yuan": str(balance), "units_confirmed": bool(units_confirmed)}, out)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def snapshot() -> dict:
    c = credentials()
    return {"provider": "yddm", "configured": bool(c["api_key"]), "api_key": "••••••••" if c["api_key"] else "",
            "api_host": HOST, "config_file": str(config_path()),
            "units_per_yuan": c["units_per_yuan"], "balance_units_per_yuan": c["balance_units_per_yuan"],
            "units_confirmed": c["units_confirmed"],
            "notice": "云端点与极致了、火山独立密钥和余额。1000单位/元由表格0.1元与文档100积分交叉推算，不能代替账户核实；计费和余额单位确认前禁止付费。"}


def configure():
    key = getpass.getpass("云端点 X-API-Key（隐藏输入）: ")
    expense = input("计费cost/balance每1元对应单位数（须控制台核实，默认1000）: ").strip() or "1000"
    balance = input("个人信息balance_cents每1元对应单位数（须核实，默认1000）: ").strip() or "1000"
    verified = input("是否已核实以上两个单位？输入yes确认: ").strip().lower() == "yes"
    save_credentials(key, expense, balance, verified)
    print("云端点配置已独立保存（0600）。" + ("" if verified else "换算单位待核实，付费调用保持拦截。"))
