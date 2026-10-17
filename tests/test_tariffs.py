import copy
import json
from decimal import Decimal

import httpx
import pytest

from jizhile_mcp.catalog import SNAPSHOT, summary
from jizhile_mcp.client import ApiError, Client
from jizhile_mcp.engine import CATALOG, Engine, GuardError, price, recommend
from jizhile_mcp.server import jizhile_catalog


def test_every_workbook_record_has_one_traceable_operation():
    refs = [(r['sheet'], r['row']) for e in CATALOG.values() for r in e['tariff_references']]
    source = [(r['sheet'], r['row']) for r in SNAPSHOT['records']]
    assert len(refs) == len(set(refs)) == 290
    assert set(refs) == set(source)
    assert summary(CATALOG)['primary_records'] == 245
    assert summary(CATALOG)['documented_contracts'] == 291


def test_paginated_catalog_can_find_last_platform_and_missing_contracts():
    collected = []
    offset = 0
    while True:
        result = jizhile_catalog(offset=offset, limit=31)
        collected += result['operations']
        offset = result['next_offset']
        if offset is None:
            break
    assert len({r['endpoint'] for r in collected}) == len(CATALOG)
    assert jizhile_catalog(callable_only=True)['total'] == 289
    assert len(jizhile_catalog(category='reddit')['operations']) == 6
    assert jizhile_catalog(keyword='商品高级详情')['operations'][0]['endpoint'] == '1688_item_pro'
    assert jizhile_catalog(limit=101)['ok'] is False


def test_all_missing_contracts_block_before_any_network(tmp_path):
    seen = []
    client = Client({'api_key': 'unit-test-secret'}, httpx.MockTransport(lambda r: seen.append(r)))
    engine = Engine(client, tmp_path)
    for key, e in CATALOG.items():
        if e['contract_status'] == 'documented':
            continue
        with pytest.raises(GuardError):
            engine.quote(key, {}, '10')
        with pytest.raises(ApiError):
            client.request(e, {})
    assert not seen


def test_other_host_and_guessed_path_cannot_receive_key():
    seen = []
    client = Client({'api_key': 'unit-test-secret'}, httpx.MockTransport(lambda r: seen.append(r)))
    for path in ['/douyin/general_search', 'https://api.yddm.com/jd/goods_detail',
                 '/fbmain/monitor/v3/../../douyin/user_data', '/fbmain/monitor/v3/get?key=foo']:
        with pytest.raises(ApiError):
            client.request({'path': path, 'method': 'POST', 'encoding': 'json'}, {})
    assert not seen


def test_conflict_and_conditional_rates_reserve_higher_amounts():
    assert price(CATALOG['channel_comments'], {}) == (Decimal('.05'), 'tariff_conflict')
    assert price(CATALOG['channel_download'], {}) == (Decimal('.2'), 'tariff_conflict')
    assert price(CATALOG['mp_today'], {}) == (Decimal('.16'), 'tariff_range')
    assert price(CATALOG['mp_bound_channel'], {}) == (Decimal('.53'), 'tariff_conflict')
    assert price(CATALOG['mp_search_db'], {'size': 1}) == (Decimal('4'), 'documented')
    # Old response example was 7.5/request; sheet says .2/item. Do not downgrade
    # a reservation on an unverified assumption about which billing basis wins.
    assert price(CATALOG['mp_owner_search_db'], {'size': 1}) == (Decimal('7.5'), 'tariff_conflict')


def test_conflicting_prices_require_cap_acceptance_and_show_both_sources(tmp_path):
    seen = []
    def upstream(req):
        seen.append(req)
        if req.url.path.endswith('get_remain_money'):
            return httpx.Response(200, json={'code': 0, 'remain_money': '200'})
        return httpx.Response(200, json={'code': 0, 'cost_money': '.05', 'remain_money': '199.95', 'data': []})
    engine = Engine(Client({'api_key': 'unit-test-secret'}, httpx.MockTransport(upstream)), tmp_path)
    with pytest.raises(GuardError):
        engine.quote('channel_comments', {'object_id': '123'})
    assert not seen
    quote = engine.quote('channel_comments', {'object_id': '123'}, '.05')
    assert quote['tariff']['raw'] == '（0.05元/次）'
    assert quote['legacy_unit_price_yuan'] == '0.03'
    assert quote['expected_cost_yuan'] == '0.05'
    with pytest.raises(GuardError):
        engine.execute(quote['quote_id'], True)
    result = engine.execute(quote['quote_id'], True, True)
    assert result['billing']['charged_yuan'] == '0.05'
    assert sum(not r.url.path.endswith('get_remain_money') for r in seen) == 1


def test_previous_quotes_invalidated_by_catalog_change_before_network(tmp_path, monkeypatch):
    seen = []
    def upstream(req):
        seen.append(req)
        return httpx.Response(200, json={'code': 0, 'remain_money': '200'})
    engine = Engine(Client({'api_key': 'unit-test-secret'}, httpx.MockTransport(upstream)), tmp_path)
    quote = engine.quote('mp_search_articles', {'keyword': 'test'})
    changed = copy.deepcopy(CATALOG['mp_search_articles'])
    changed['tariff']['unit_prices_yuan'] = ['2']
    monkeypatch.setitem(CATALOG, 'mp_search_articles', changed)
    with pytest.raises(GuardError, match='旧报价失效'):
        engine.execute(quote['quote_id'], True)
    assert len(seen) == 1


def test_pdd_conflicting_path_is_corrected_from_authoritative_contract():
    query, submit = CATALOG['pdd_comment_task_result'], CATALOG['pdd_comment_task_submit']
    assert query['path'] == '/pdd/async_get_comment_task' and query['method']=='GET'
    assert submit['path'] == '/pdd/async_commit_comment_task' and submit['method']=='POST'
    assert query['tariff_references'][0]['raw_path'].endswith('/pdd/async_commit_comment_task')
    assert query['title'] != submit['title']
    comparison = recommend('pdd_comments', False, candidates=['pdd_comment_task_result', 'pdd_comment_task_submit'])
    assert all(o['contract_status']=='documented' for o in comparison['options'])


def test_unavailable_and_version_aliases_preserved():
    blocked = {key for key, e in CATALOG.items() if e['availability'] == 'unavailable'}
    assert blocked == {'xingtu_external_multi_get_item', 'xingtu_author_commerce_seed_base_info'}
    # Do not repair a vendor path or collapse variants solely because names match.
    for key in ['xhs_stop_list', 'xhs_shop_list', 'youtube_video_info', 'youtube_video_info_v1']:
        assert key in CATALOG
