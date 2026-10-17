import copy
import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from jsonschema import Draft202012Validator

from jizhile_mcp.catalog import CLOUD_CONTRACTS
from jizhile_mcp.client import Client
from jizhile_mcp.engine import CATALOG, Engine, GuardError, validate
from jizhile_mcp.yddm import YddmClient, save_credentials, snapshot

CREDS = {'api_key': 'cloud-mock-key-only', 'units_per_yuan': '1000', 'balance_units_per_yuan': '1000', 'units_confirmed': True}


def sample(schema):
    if 'enum' in schema:
        return schema['enum'][0]
    for union in ('oneOf', 'anyOf', 'allOf'):
        if union in schema:
            return sample(schema[union][0])
    kind = schema.get('type', 'string')
    if isinstance(kind, list):
        kind = kind[0]
    if kind == 'object':
        return {key: sample(value) for key, value in schema.get('properties', {}).items()}
    if kind == 'array':
        return [sample(schema.get('items', {}))]
    if kind == 'integer':
        return max(1, schema.get('minimum', 1))
    if kind == 'number':
        return max(1.5, schema.get('minimum', 1))
    if kind == 'boolean':
        return True
    if kind == 'null':
        return None
    return 'fixture-value'


def transport(seen, cost=100):
    def send(req):
        seen.append(req)
        assert req.url.host == 'api.yddm.com'
        assert req.headers['x-api-key'] == CREDS['api_key']
        assert not req.url.query
        if req.url.path == '/users/me':
            return httpx.Response(200, json={'code': 0, 'data': {'balance_cents': 5_000_000,
                'api_key': CREDS['api_key'], 'phone_num': 'private-not-for-output', 'email': 'private@example.invalid'}})
        return httpx.Response(200, json={'code': 0, 'data': {'cost': cost, 'balance': 4_999_900,
            'items': [{'id': 14462543356698040491, 'title': 'mock acceptance'}]}})
    return httpx.MockTransport(send)


BUSINESS = [(key, e) for key, e in CATALOG.items() if e['provider'] == 'yddm'
            and e['availability'] == 'available' and e.get('kind') != 'balance']


@pytest.mark.parametrize('key,endpoint', BUSINESS, ids=[key for key, _ in BUSINESS])
def test_every_callable_cloud_contract_roundtrips_over_guarded_http(tmp_path, key, endpoint):
    Draft202012Validator.check_schema(endpoint['request_schema'])
    seen = []
    engine = Engine(YddmClient(CREDS, transport(seen)), tmp_path)
    params = sample(endpoint['request_schema'])
    quote = engine.quote(key, params, '10')
    assert quote['quote_id'].startswith('yddm:') and quote['provider'] == 'yddm'
    result = engine.execute(quote['quote_id'], True, True)
    assert result['status'] == 'ok'
    assert result['billing']['charged_yuan'] == '0.1'
    assert result['billing']['balance_after_yuan'] == '4999.9'
    assert result['data']['data']['items'][0]['id'] == '14462543356698040491'
    assert all(CREDS['api_key'] not in req.content.decode() for req in seen)
    business = [req for req in seen if req.url.path != '/users/me']
    assert len(business) == 1
    assert business[0].method == endpoint['method'] and business[0].url.path == endpoint['path']
    assert json.loads(business[0].content) == params


def test_nested_billing_cache_does_not_report_old_fee_as_new(tmp_path):
    seen = []
    engine = Engine(YddmClient(CREDS, transport(seen)), tmp_path)
    quote = engine.quote('weibo_hot_search', {'hot_type': '1'}, '.1')
    engine.execute(quote['quote_id'], True, True)
    quote2 = engine.quote('weibo_hot_search', {'hot_type': '1'}, '.1')
    result = engine.execute(quote2['quote_id'], True, True)
    assert result['cached'] and result['billing']['charged_yuan'] == '0'
    assert 'cost' not in result['data']['data'] and 'balance' not in result['data']['data']
    assert sum(req.url.path != '/users/me' for req in seen) == 1


def test_cloud_balance_reveals_no_profile_or_key():
    result = YddmClient(CREDS, transport([])).balance()
    text = json.dumps(result)
    assert result['balance_yuan'] == '5000'
    assert CREDS['api_key'] not in text and 'private-not-for-output' not in text and 'private@example.invalid' not in text


def test_unconfirmed_units_block_before_network(tmp_path):
    seen = []
    creds = {**CREDS, 'units_confirmed': False}
    engine = Engine(YddmClient(creds, transport(seen)), tmp_path)
    with pytest.raises(GuardError, match='换算'):
        engine.quote('weibo_hot_search', {}, '.1')
    assert not seen


def test_realistic_low_balance_keeps_reserve_and_sends_no_business_request(tmp_path):
    paths = []
    def send(req):
        paths.append(req.url.path)
        assert req.url.path == '/users/me'
        return httpx.Response(200, json={'code': 0, 'data': {'balance_cents': 1000}})
    engine = Engine(YddmClient(CREDS, httpx.MockTransport(send)), tmp_path)
    with pytest.raises(GuardError, match='100 元安全余额'):
        engine.quote('weibo_hot_search', {}, '.1')
    assert paths == ['/users/me']


def test_unknown_parameters_invalid_enum_and_large_ids_block_before_network():
    for params in [{'hot_type': '9'}, {'api_key': 'forbidden'}, {'hot_type': True}]:
        with pytest.raises(ValueError):
            validate('weibo_hot_search', params)
    with pytest.raises(ValueError, match='长ID'):
        validate('douyin_aweme_detail', {'aweme_id': 14462543356698040491})
    # Empty pagination controls are valid in the provider's schemas.
    e = CATALOG['weibo_user_posts_v2']
    validate('weibo_user_posts_v2', {'uid': '123', 'cursor': ''})


def test_shared_daily_budget_is_serialized_across_both_query_providers(tmp_path):
    def legacy(req):
        if req.url.path.endswith('get_remain_money'):
            return httpx.Response(200, json={'code': 0, 'remain_money': '5000'})
        return httpx.Response(200, json={'code': 0, 'cost_money': '.5', 'remain_money': '4999.5'})
    old = Engine(Client({'api_key': 'old-mock-key'}, httpx.MockTransport(legacy)), tmp_path/'old', daily='.5', budget_root=tmp_path)
    cloud = Engine(YddmClient(CREDS, transport([], cost=500)), tmp_path/'cloud', daily='.5', budget_root=tmp_path)
    q1 = old.quote('mp_search_articles', {'keyword': 'fixture'})
    q2 = cloud.quote('weibo_hot_search', {}, '.5')
    def run(pair):
        try:
            return pair[0].execute(pair[1]['quote_id'], True, True)['status']
        except GuardError:
            return 'blocked'
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(run, [(old,q1),(cloud,q2)]))
    assert sorted(results) == ['blocked', 'ok']
    assert old.status()['accounted_today_yuan'] == cloud.status()['accounted_today_yuan'] == '0.5'


def test_cloud_credentials_remain_separate_and_private(tmp_path, monkeypatch):
    path = tmp_path/'cloud.json'
    monkeypatch.setenv('JIZHILE_YDDM_CONFIG_FILE', str(path))
    save_credentials('private-cloud-test', '1000', '100', True)
    assert path.stat().st_mode & 0o777 == 0o600
    state = snapshot()
    assert state['units_per_yuan']=='1000' and state['balance_units_per_yuan']=='100'
    assert 'private-cloud-test' not in json.dumps(state)


def test_official_schema_errors_have_explicit_example_based_corrections():
    assert set(CATALOG['xhs_share_id_to_web_id']['allowed']) == {'share_link'}
    assert 'video_id' in CATALOG['youtube_video_detail_v2']['allowed']
    assert 'video_id ' not in CATALOG['youtube_video_detail_v2']['allowed']
    assert 'page_num' in CATALOG['toutiao_search']['allowed']
    assert 'flow_type' in CATALOG['xingtu_author_show_items']['allowed']
