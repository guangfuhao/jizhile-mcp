import os
import subprocess
import sys
import time

import httpx


def test_private_setup_save_origin_check_and_process_exit(tmp_path):
    rendezvous=tmp_path/"setup-url"
    config=tmp_path/"credentials.json"
    process=subprocess.Popen([sys.executable,"-m","jizhile_mcp.setup_server","--serve","--no-open",
                              "--timeout","10","--rendezvous",str(rendezvous)],
                             env={**os.environ,"JIZHILE_CONFIG_FILE":str(config)},
                             stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            if rendezvous.exists():break
            time.sleep(0.02)
        assert rendezvous.exists()
        url=rendezvous.read_text()
        with httpx.Client(trust_env=False) as client:
            assert client.get(url).status_code==200
            denied=client.post(url,data={"api_key":"fake-local-test"},headers={"Origin":"https://untrusted.invalid"})
            assert denied.status_code==403 and not config.exists()
            saved=client.post(url,data={"api_key":"fake-local-test"})
            assert saved.status_code==200
            assert "fake-local-test" not in saved.text
        process.wait(timeout=3)
        assert process.returncode==0
        assert config.stat().st_mode & 0o777==0o600
        assert not rendezvous.exists()
        with httpx.Client(trust_env=False,timeout=1) as client:
            try:client.get(url)
            except httpx.ConnectError:pass
            else:raise AssertionError("setup port remains open")
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=3)


def test_setup_times_out_and_releases_port(tmp_path):
    rendezvous=tmp_path/"setup-url"
    process=subprocess.Popen([sys.executable,"-m","jizhile_mcp.setup_server","--serve","--no-open",
                              "--timeout","5","--rendezvous",str(rendezvous)],
                             stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            if rendezvous.exists():break
            time.sleep(0.02)
        url=rendezvous.read_text()
        process.wait(timeout=8)
        assert process.returncode==0 and not rendezvous.exists()
        with httpx.Client(trust_env=False,timeout=1) as client:
            try:client.get(url)
            except httpx.ConnectError:pass
            else:raise AssertionError("setup port remains open")
    finally:
        if process.poll() is None:
            process.terminate();process.wait(timeout=3)
