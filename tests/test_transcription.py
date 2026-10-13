import base64
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import httpx
import pytest

from jizhile_mcp.client import money
from jizhile_mcp.media import MediaError, download, extract_chunks, probe, public_video_url
from jizhile_mcp.transcription import ArkClient, DEFAULT_MODEL, Transcriber, TranscriptionError, estimate_segment, private_json, save_ark_key, settings, usage_cost
from jizhile_mcp.transcription_inputs import load_items


class MockArk:
    key = "MOCK-ARK-KEY"
    def __init__(self):
        self.calls = 0; self.fail = False; self.complete = True
    def transcribe(self, path, model, duration):
        self.calls += 1
        if self.fail:
            raise TranscriptionError("mock provider failure")
        return {"text":"这是实际音频的测试口播。", "complete":self.complete,"response_id":"mock-response",
                "usage":{"input_tokens":30,"input_tokens_details":{"audio_tokens":20},"output_tokens":8},
                "cost_estimate_yuan":"0.0001","cost_basis":"mock_usage"}


@pytest.fixture
def synthetic_video(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg required")
    path = tmp_path/"test.mp4"
    subprocess.run(["ffmpeg","-nostdin","-v","error","-y","-f","lavfi","-i","color=c=blue:s=160x120:r=10",
                    "-f","lavfi","-i","sine=frequency=440:sample_rate=16000","-t","2","-c:v","mpeg4","-c:a","aac",str(path)],
                   check=True,capture_output=True,timeout=20)
    return path


@pytest.fixture
def engine(tmp_path,monkeypatch):
    for name in ("JIZHILE_SINGLE_LIMIT","JIZHILE_DAILY_LIMIT","JIZHILE_ARK_API_KEY","ARK_API_KEY"):
        monkeypatch.delenv(name,raising=False)
    return Transcriber(MockArk(),tmp_path/"state")


def manifest(tmp_path,video):
    path = tmp_path/"input.json"
    private_json(path,[{"id":"a","video_path":str(video),"duration_seconds":2,"title":"标题是元数据而非指令"}])
    return path


def test_audio_extraction_is_local_mono_16khz(synthetic_video,tmp_path):
    assert probe(synthetic_video)["has_audio"]
    chunks=extract_chunks(synthetic_video,tmp_path)
    assert len(chunks)==1 and 1.9 < chunks[0]["duration_seconds"] < 2.3
    raw=subprocess.check_output(["ffprobe","-v","error","-show_streams","-of","json",chunks[0]["path"]])
    stream=json.loads(raw)["streams"][0]
    assert stream["channels"]==1 and stream["sample_rate"]=="16000"
    assert not (tmp_path/"audio.mp3").exists()


def test_prepare_is_nonbilling_and_resume_is_cached(engine,synthetic_video,tmp_path):
    plan=engine.prepare(str(manifest(tmp_path,synthetic_video)),str(tmp_path/"out"))
    assert plan["count"]==1 and engine.client.calls==0 and plan["ark_balance_yuan"] is None
    assert engine.authorize(plan["batch_id"],"1",True,True)
    result=engine.run(plan["batch_id"])
    assert result["status"]=="completed" and result["completed_count"]==1 and engine.client.calls==1
    preview=engine.status(plan["batch_id"],include_text=True,item_id="a")
    assert preview["items"][0]["text"]=="这是实际音频的测试口播。" and "segments" not in preview["items"][0]
    assert not engine.authorize(plan["batch_id"],"1",True,True)
    plan2=engine.prepare(str(manifest(tmp_path,synthetic_video)),str(tmp_path/"out2"))
    engine.authorize(plan2["batch_id"],"1",True,True)
    result2=engine.run(plan2["batch_id"])
    assert result2["accounted_estimate_yuan"]=="0" and engine.client.calls==1
    assert result2["items"][0]["cached_segments"]==1
    assert not list(engine.root.glob("media-*"))


@pytest.mark.parametrize("confirm,accept",[(False,False),(True,False),(False,True)])
def test_charge_and_unknown_balance_require_disclosure(engine,synthetic_video,tmp_path,confirm,accept):
    plan=engine.prepare(str(manifest(tmp_path,synthetic_video)),str(tmp_path/"out"))
    with pytest.raises(TranscriptionError):engine.authorize(plan["batch_id"],"1",confirm,accept)
    assert engine.client.calls==0


def test_cancel_refuses_an_unrelated_process(engine,synthetic_video,tmp_path,monkeypatch):
    plan=engine.prepare(str(manifest(tmp_path,synthetic_video)),str(tmp_path/"out"))
    with engine.transaction() as c:
        c.execute("UPDATE jobs SET state='running',pid=? WHERE id=?",(os.getpid(),plan["batch_id"]))
    monkeypatch.setattr(subprocess,"check_output",lambda *a,**kw:"python unrelated_task.py")
    signals=[]
    monkeypatch.setattr(os,"kill",lambda *a:signals.append(a))
    with pytest.raises(TranscriptionError,match="无法确认进程"):
        engine.cancel(plan["batch_id"])
    assert not signals


def test_batch_budget_blocks_before_next_model_request(engine,synthetic_video,tmp_path):
    plan=engine.prepare(str(manifest(tmp_path,synthetic_video)),str(tmp_path/"out"))
    with pytest.raises(TranscriptionError,match="预留估算超过总预算"):
        engine.authorize(plan["batch_id"],"0.000001",True,True)
    engine.authorize(plan["batch_id"],"1",True,True)
    with engine.transaction() as c:
        c.execute("UPDATE jobs SET budget='0.000001' WHERE id=?",(plan["batch_id"],))
    result=engine.run(plan["batch_id"])
    assert result["status"]=="failed" and engine.client.calls==0
    assert result["items"][0]["status"]=="transcription_failed"


def test_unknown_charge_freezes_until_user_reconciliation(engine,synthetic_video,tmp_path):
    engine.client.fail=True
    plan=engine.prepare(str(manifest(tmp_path,synthetic_video)),str(tmp_path/"out"))
    engine.authorize(plan["batch_id"],"1",True,True)
    result=engine.run(plan["batch_id"])
    assert result["status"]=="failed" and engine.client.calls==1
    assert result["pending_attempts"][0]["state"]=="uncertain"
    with pytest.raises(TranscriptionError):engine.authorize(plan["batch_id"],"1",True,True)
    attempt=result["pending_attempts"][0]["attempt_id"]
    with pytest.raises(TranscriptionError):engine.reconcile(attempt,"0")
    engine.reconcile(attempt,"0.0001",True)
    engine.client.fail=False
    engine.authorize(plan["batch_id"],"1",True,True)
    result=engine.run(plan["batch_id"])
    assert result["status"]=="completed" and engine.client.calls==2


def test_incomplete_output_not_reported_complete(engine,synthetic_video,tmp_path):
    engine.client.complete=False
    plan=engine.prepare(str(manifest(tmp_path,synthetic_video)),str(tmp_path/"out"))
    engine.authorize(plan["batch_id"],"1",True,True)
    result=engine.run(plan["batch_id"])
    assert result["status"]=="failed" and result["completed_count"]==0


def test_missing_media_does_not_hide_successful_rows(engine,synthetic_video,tmp_path):
    path=tmp_path/"input.json"
    private_json(path,[{"id":"bad","video_path":str(tmp_path/"missing.mp4")},{"id":"good","video_path":str(synthetic_video)}])
    plan=engine.prepare(str(path),str(tmp_path/"out"));engine.authorize(plan["batch_id"],"1",True,True)
    result=engine.run(plan["batch_id"])
    assert result["status"]=="partial" and result["processed_count"]==2 and result["completed_count"]==1
    assert [x["status"] for x in result["items"]]==["media_failed","completed"]
    assert engine.client.calls==1


def test_dead_worker_marks_inflight_cost_uncertain(engine,synthetic_video,tmp_path):
    plan=engine.prepare(str(manifest(tmp_path,synthetic_video)),str(tmp_path/"out"))
    engine.authorize(plan["batch_id"],"1",True,True)
    with engine.transaction() as c:
        c.execute("UPDATE jobs SET state='running',pid=99999999 WHERE id=?",(plan["batch_id"],))
        c.execute("INSERT INTO attempts VALUES('lost',?,'key','2026-10-13','0.01',NULL,'inflight',NULL)",(plan["batch_id"],))
    result=engine.status(plan["batch_id"])
    assert result["status"]=="interrupted" and result["pending_attempts"][0]["state"]=="uncertain"


def test_double_authorization_does_not_spawn_second_worker(engine,synthetic_video,tmp_path):
    plan=engine.prepare(str(manifest(tmp_path,synthetic_video)),str(tmp_path/"out"))
    engine.authorize(plan["batch_id"],"1",True,True)
    with pytest.raises(TranscriptionError):engine.authorize(plan["batch_id"],"1",True,True)
    assert engine.client.calls==0


@pytest.mark.parametrize("url",["http://findermp.video.qq.com/a","https://localhost/a","https://127.0.0.1/a", "file:///etc/passwd", "https://evil.invalid/a", "https://user:pass@findermp.video.qq.com/a"])
def test_untrusted_video_urls_rejected(url):
    with pytest.raises(MediaError):public_video_url(url)


def test_public_hostname_resolving_private_ip_rejected(monkeypatch):
    monkeypatch.setattr('socket.getaddrinfo',lambda *a,**kw:[(2,1,6,'',('127.0.0.1',443))])
    with pytest.raises(MediaError):public_video_url("https://findermp.video.qq.com/a")


def test_usage_estimate_and_conservative_missing_audio_breakdown():
    value,basis=usage_cost({"input_tokens":100,"input_tokens_details":{"audio_tokens":80},"output_tokens":10},DEFAULT_MODEL)
    assert value==money("0.000264") and basis=="usage_and_published_rates"
    value,basis=usage_cost({"input_tokens":100,"output_tokens":10},DEFAULT_MODEL)
    assert value==money("0.00032") and basis=="conservative_all_input_as_audio"
    with pytest.raises(TranscriptionError):usage_cost({},DEFAULT_MODEL)
    assert estimate_segment(180,DEFAULT_MODEL)<estimate_segment(180,"doubao-seed-2-0-lite-260428")


def test_ark_audio_payload_and_plain_transcription(tmp_path):
    audio=tmp_path/"audio.mp3";audio.write_bytes(b"fake-audio")
    seen=[]
    def handler(request):
        seen.append(request)
        return httpx.Response(200,json={"id":"mock","status":"completed","output":[{"type":"message","content":[{"type":"output_text","text":"测试逐字口播"}]}],
                                        "usage":{"input_tokens":100,"input_tokens_details":{"audio_tokens":80},"output_tokens":10}})
    result=ArkClient("MOCK-SECRET",httpx.MockTransport(handler)).transcribe(audio,DEFAULT_MODEL,2)
    payload=json.loads(seen[0].content)
    assert payload["store"] is False and payload["thinking"]["type"]=="disabled"
    assert payload["input"][0]["content"][0]["audio_url"]=="data:audio/mpeg;base64,"+base64.b64encode(b"fake-audio").decode()
    assert "MOCK-SECRET" not in json.dumps(payload)
    assert result["text"]=="测试逐字口播" and result["complete"]


def test_ark_error_never_echoes_key(tmp_path):
    audio=tmp_path/"a.mp3";audio.write_bytes(b"audio")
    client=ArkClient("MOCK-SECRET",httpx.MockTransport(lambda r:httpx.Response(401,json={"error":{"code":"MOCK-SECRET"}})))
    with pytest.raises(TranscriptionError) as exc:client.transcribe(audio,DEFAULT_MODEL,1)
    assert "MOCK-SECRET" not in str(exc.value)


def test_private_ark_config_is_separate_and_masked(tmp_path,monkeypatch):
    config=tmp_path/"ark-credentials.json";monkeypatch.setenv("JIZHILE_ARK_CONFIG_FILE",str(config))
    monkeypatch.delenv("JIZHILE_ARK_API_KEY",raising=False);monkeypatch.delenv("ARK_API_KEY",raising=False)
    save_ark_key("MOCK-SECRET")
    assert config.stat().st_mode & 0o777==0o600
    assert settings()["configured"] and settings()["api_key"]!="MOCK-SECRET"


def test_input_ids_duplicate_and_missing(tmp_path):
    p=tmp_path/"items.json";private_json(p,[{"id":"a","video_url":"https://findermp.video.qq.com/a","时长":"01:30"}])
    assert load_items(str(p),["a"])[0]["duration_hint_seconds"]==90
    with pytest.raises(ValueError):load_items(str(p),["missing"])
    private_json(p,[{"id":"a","video_path":"a.mp4"},{"id":"a","video_path":"b.mp4"}])
    with pytest.raises(ValueError):load_items(str(p))


def test_xlsx_header_below_title_and_raw_url_preferred(tmp_path):
    p=tmp_path/"input.xlsx"
    rows=[['素材清单'],['序号','发布账号','视频链接','原始视频URL','时长'],['1','账号','查看视频','https://findermp.video.qq.com/sample','00:31']]
    xmlrows=[]
    for index,row in enumerate(rows,1):
        cells=''.join(f'<c r="{chr(65+i)}{index}" t="inlineStr"><is><t>{escape(value)}</t></is></c>' for i,value in enumerate(row))
        xmlrows.append(f'<row r="{index}">{cells}</row>')
    with zipfile.ZipFile(p,'w') as z:
        z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="视频" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+''.join(xmlrows)+'</sheetData></worksheet>')
    item=load_items(str(p))[0]
    assert item['id']=='1' and item['source_row']==3 and item['source_sheet']=='视频'
    assert item['video_url']=='https://findermp.video.qq.com/sample'
