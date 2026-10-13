import runpy
from pathlib import Path


def test_acceptance_counts_content_not_search_controls():
    extract=runpy.run_path(str(Path(__file__).resolve().parents[1]/"scripts/mcp_smoke.py"))["extract_items"]
    response={"advanceSearch":{"title":"已选择：文章"},"data":[{"items":[
        {"title":"<em>实际文章</em>","docID":"12345678901234567890","doc_url":"https://mp.weixin.qq.com/s/example","source":{"title":"公众号"}}
    ]}]}
    assert extract(response)==[{"title":"实际文章","has_link":True,"has_id":True}]
