import httpx
import pytest

from jizhile_mcp.engine import Engine, GuardError
from jizhile_mcp.yddm import YddmClient

CREDS={'api_key':'mock-cloud-failure-key','units_per_yuan':'1000','balance_units_per_yuan':'1000','units_confirmed':True}


@pytest.mark.parametrize('failure',['timeout','missing_cost','overrun','charged_error'])
def test_cloud_failure_accounting_no_retry_and_uncertainty_freeze(tmp_path,failure):
    calls=[]
    def send(req):
        if req.url.path=='/users/me':
            return httpx.Response(200,json={'code':0,'data':{'balance_cents':500000}})
        calls.append(req)
        if failure=='timeout':
            raise httpx.ReadTimeout('sensitive request must not appear in error')
        data={'cost':200 if failure=='overrun' else 100,'balance':499900}
        if failure=='missing_cost':data.pop('cost')
        return httpx.Response(200,json={'code':400 if failure=='charged_error' else 0,'data':data})
    engine=Engine(YddmClient(CREDS,httpx.MockTransport(send)),tmp_path)
    quote=engine.quote('weibo_hot_search',{},'.1')
    result=engine.execute(quote['quote_id'],True,True)
    assert len(calls)==1
    if failure=='charged_error':
        assert not result['ok'] and result['status']=='upstream_error'
        assert result['billing']['charged_yuan']=='0.1'
    else:
        assert result['status'] in ['uncertain','overrun']
        with pytest.raises(GuardError):engine.quote('weibo_hot_search',{},'.1',True)
        with pytest.raises(GuardError):engine.resolve(quote['quote_id'],'0')


def test_changed_unit_conversion_invalidates_quote_before_network(tmp_path):
    calls=[]
    def send(req):
        calls.append(req)
        assert req.url.path=='/users/me'
        return httpx.Response(200,json={'code':0,'data':{'balance_cents':500000}})
    client=YddmClient(dict(CREDS),httpx.MockTransport(send))
    engine=Engine(client,tmp_path)
    quote=engine.quote('weibo_hot_search',{},'.1')
    client.credentials['units_per_yuan']='100'
    with pytest.raises(GuardError,match='配置已变化'):
        engine.execute(quote['quote_id'],True,True)
    assert len(calls)==1
