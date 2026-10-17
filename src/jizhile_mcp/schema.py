"""Validate documented Cloud Point JSON without inventing example targets."""
from __future__ import annotations

import copy
import json
import math

from jsonschema import Draft202012Validator

FORBIDDEN = {"key", "api_key", "x-api-key", "authorization", "verifycode", "api_host", "base_url"}


def validate_cloud(endpoint: dict, params: dict, wire: bool = False) -> dict:
    if not isinstance(params, dict) or set(params) - set(endpoint["allowed"]):
        raise ValueError("含未文档化参数；先读取该接口目录。不允许传Key或覆盖地址。")
    schema = copy.deepcopy(endpoint["request_schema"])
    schema["additionalProperties"] = False
    result = copy.deepcopy(params)

    def check(value, depth=0):
        if depth > 10:
            raise ValueError("JSON参数嵌套超过10层")
        if isinstance(value, dict):
            if any(k.lower() in FORBIDDEN for k in value):
                raise ValueError("业务参数禁止携带Key、鉴权字段或覆盖API地址")
            for v in value.values():
                check(v, depth+1)
        elif isinstance(value, list):
            if len(value) > 200:
                raise ValueError("单个数组最多200项；不自动拆批")
            for v in value:
                check(v, depth+1)
        elif isinstance(value, float) and not math.isfinite(value):
            raise ValueError("JSON数值须为有限数")
        elif not isinstance(value, (str, int, float, bool, type(None))):
            raise ValueError("业务参数必须为JSON类型")

    check(result)
    if len(json.dumps(result, ensure_ascii=False).encode()) > 64000:
        raise ValueError("JSON参数最多64KB")
    for key, value in list(result.items()):
        prop = schema.get("properties", {}).get(key, {})
        is_id = key == "id" or key.endswith("_id") or key.endswith("_ids") or key in {"tid", "nid", "uid", "mid", "oid", "aid", "bvid"}
        if is_id and isinstance(value, int) and not isinstance(value, bool) and abs(value) > 2**53 - 1:
            raise ValueError("长ID必须传字符串，防止客户端精度丢失")
        if is_id and prop.get("type") == "integer" and isinstance(value, str) and value.isdecimal():
            result[key] = int(value)  # exact Python integer, only at the documented wire boundary
    error = next(Draft202012Validator(schema).iter_errors(result), None)
    if error:
        # The upstream or caller value must not be echoed in errors.
        location = ".".join(str(x) for x in error.absolute_path) or "请求体"
        raise ValueError(f"参数{location}不符合官方定义（{error.validator}）；请查目录中的类型、必填项和枚举。")
    # Empty cursors and alternative ID/link fields are explicitly used by the
    # provider. Presence is enforced by schema.required, not a blanket nonempty rule.
    return result if wire else copy.deepcopy(params)
