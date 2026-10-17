"""Real MCP stdio acceptance. --live authorizes at most two paid first pages."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(os.environ.get("JIZHILE_SMOKE_ROOT", Path(__file__).resolve().parents[1]))


def extract_items(data):
    found=[]
    def walk(x):
        if isinstance(x,dict):
            title=x.get("title") or x.get("nickname") or x.get("nickName")
            link=x.get("url") or x.get("videoUrl") or x.get("article_url") or x.get("doc_url")
            content_id=x.get("exportId") or x.get("object_id") or x.get("docID")
            if title and isinstance(title,str) and content_id:
                found.append({"title":re.sub(r'<[^>]+>','',title)[:200],"has_link":bool(link),"has_id":bool(content_id)})
            for v in x.values():walk(v)
        elif isinstance(x,list):
            for v in x:walk(v)
    walk(data.get("data",data))
    return found


async def run(live=False):
    report={"transport":"MCP stdio","live":live,"queries":[]}
    params=StdioServerParameters(command=str(ROOT/"scripts/run_mcp.sh"),cwd=str(ROOT),env=dict(os.environ))
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write) as session:
            await session.initialize()
            tools=await session.list_tools()
            report["tools"]=[x.name for x in tools.tools]
            assert len(report["tools"])==16
            async def call(name,args):
                result=await session.call_tool(name,args)
                data=result.structuredContent
                if data is None:
                    data=json.loads(next(x.text for x in result.content if x.type=="text"))
                if data.get("blocked") or data.get("ok") is False:raise RuntimeError(json.dumps(data,ensure_ascii=False))
                return data
            cat=await call("jizhile_catalog",{})
            assert cat["total"]==303
            assert cat['summary']['documented_contracts']==291
            assert cat['summary']['missing_contracts']==12
            report['catalog_summary']=cat['summary']
            tail=await call('jizhile_catalog',{'offset':300})
            assert len(tail['operations'])==3 and tail['next_offset'] is None
            pending=await call('jizhile_catalog',{'endpoint':'xhs_note_detail6'})
            assert pending['contract_status']=='missing'
            cloud=await call('jizhile_catalog',{'endpoint':'douyin_general_search'})
            assert cloud['contract_status']=='documented' and cloud['provider']=='yddm'
            unavailable=await call('jizhile_catalog',{'endpoint':'xingtu_external_multi_get_item'})
            assert unavailable['availability']=='unavailable'
            blocked=await session.call_tool('jizhile_quote',{'endpoint':'xhs_note_detail6','params':{},'max_cost_yuan':'1'})
            body=blocked.structuredContent
            if body is None:
                body=json.loads(next(x.text for x in blocked.content if x.type=='text'))
            assert body['blocked'] and not body['ok']
            compare=await call("jizhile_compare",{"intent":"channel_videos"})
            assert compare["lowest_estimate"]=="channel_search_videos"
            if live:
                start=await call("jizhile_balance",{})
                report["balance_before_yuan"]=start["balance_yuan"]
                print(json.dumps({"phase":"balance","data":start},ensure_ascii=False),flush=True)
                for kind in ("mp_articles","channel_videos"):
                    q=await call("jizhile_quote_search",{"kind":kind,"keyword":"人民日报"})
                    print(json.dumps({"phase":"quote","kind":kind,"expected_cost_yuan":q["expected_cost_yuan"],"balance_yuan":q["balance_yuan"],"price_status":q["price_status"]},ensure_ascii=False),flush=True)
                    assert q["expected_cost_yuan"]=="0.5"
                    result=await call("jizhile_execute",{"quote_id":q["quote_id"],"confirm_charge":True})
                    assert result["status"]=="ok"
                    items=extract_items(result["data"])
                    assert items, "no meaningful returned items"
                    report["queries"].append({"kind":kind,"status":result["status"],"items_with_title":len(items),"samples":items[:3],"billing":result["billing"]})
                    # Exact duplicate must be served from cache without a second business charge.
                    qc=await call("jizhile_quote_search",{"kind":kind,"keyword":"人民日报"})
                    assert qc["cache_hit"]
                    cached=await call("jizhile_execute",{"quote_id":qc["quote_id"],"confirm_charge":True})
                    assert cached["cached"] and cached["billing"]["charged_yuan"]=="0"
                    report["queries"][-1]["repeat_query_added_charge_yuan"]="0"
                end=await call("jizhile_balance",{})
                report["balance_after_yuan"]=end["balance_yuan"]
                report["accounted_today_yuan"]=end["accounted_today_yuan"]
    report["stdio_session_closed"]=True
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--live",action="store_true");parser.add_argument("--receipt")
    args=parser.parse_args()
    result=asyncio.run(run(args.live))
    if args.receipt:
        Path(args.receipt).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
