"""Downloads and GitHub API reads survive dropped connections.

A real local HTTP server (``scripted_server`` in conftest.py) answers each
request with the next scripted action: a TCP reset, a cut-off body, an HTTP
status with headers, or the real body. The updater code only allows HTTPS, so
the ``local_http`` fixture lets its request builder accept this one local
``http://127.0.0.1`` URL; everything else (sockets, urllib, retries, files) is
the real code path. Pauses are recorded instead of slept.
"""

from __future__ import annotations

import socket
import time
import urllib.error

import pytest

from portable_hermes import common
from portable_hermes.common import UpdateError
from portable_hermes.core import CoreLifecycle
from portable_hermes.wrapper import WrapperUpdater

BODY = bytes(range(256)) * 64          # 16 KiB


@pytest.fixture
def waits(monkeypatch):
    recorded: list[float] = []
    monkeypatch.setattr(common, "_sleep", recorded.append)
    return recorded


@pytest.fixture
def local_http(monkeypatch):
    real = common._request

    def request(url, accept=None):
        if not url.startswith("http://127.0.0.1:"):
            return real(url, accept)
        req = real("https://" + url[len("http://"):], accept)
        req.full_url = url
        return req

    monkeypatch.setattr(common, "_request", request)


def files_in(folder):
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


# --------------------------------------------------------------------------
# downloads
# --------------------------------------------------------------------------

def test_download_survives_a_reset_and_a_503(tmp_path, scripted_server, local_http, waits,
                                             capsys):
    server = scripted_server(BODY, ["reset", 503])
    dest = tmp_path / "out" / "core.zip"
    assert common.download(server.url, dest) == dest
    assert dest.read_bytes() == BODY
    assert server.hits == 3 and waits == [2, 5]
    assert files_in(dest.parent) == ["core.zip"]
    printed = capsys.readouterr().out
    assert "download failed (" in printed
    assert "trying again (2 of 4) ..." in printed and "trying again (3 of 4) ..." in printed


def test_download_waits_as_long_as_retry_after_asks(tmp_path, scripted_server, local_http,
                                                    waits):
    server = scripted_server(BODY, [(429, {"Retry-After": "7"}), (503, {"Retry-After": "1"})])
    dest = tmp_path / "core.zip"
    common.download(server.url, dest, quiet=True)
    assert dest.read_bytes() == BODY
    assert waits == [7, 5]              # the longer of Retry-After and the planned pause


def test_download_does_not_wait_for_a_retry_after_beyond_the_cap(tmp_path, scripted_server,
                                                                  local_http, waits):
    server = scripted_server(BODY, [(503, {"Retry-After": "600"})])
    with pytest.raises(UpdateError) as info:
        common.download(server.url, tmp_path / "core.zip", quiet=True)
    assert info.value.code == "http_503" and server.hits == 1 and waits == []
    assert "(1 attempt; the server asked to wait 600 s)" in info.value.reason


def test_a_missing_file_is_not_retried(tmp_path, scripted_server, local_http, waits):
    server = scripted_server(BODY, [404])
    with pytest.raises(UpdateError) as info:
        common.download(server.url, tmp_path / "out" / "core.zip", quiet=True)
    assert info.value.code == "http_404"
    assert info.value.reason.endswith("(1 attempt; not retried)")
    assert server.hits == 1 and waits == []
    assert files_in(tmp_path / "out") == []


def test_a_cut_off_body_is_never_kept_as_a_finished_file(tmp_path, scripted_server,
                                                         local_http, waits):
    server = scripted_server(BODY, ["truncate"])
    dest = tmp_path / "once" / "core.zip"
    common.download(server.url, dest, quiet=True)
    assert dest.read_bytes() == BODY and waits == [2]
    # Cut off every time: no file at all, neither final nor partial.
    waits.clear()
    server = scripted_server(BODY, ["truncate"] * 4)
    dest = tmp_path / "always" / "core.zip"
    with pytest.raises(UpdateError) as info:
        common.download(server.url, dest, quiet=True)
    assert info.value.code == "network" and info.value.details["attempts"] == 4
    assert "connection closed after" in info.value.reason
    assert info.value.reason.endswith("(4 attempts)")
    assert files_in(dest.parent) == []
    assert waits == [2, 5, 10]


def test_download_gives_up_after_four_attempts(tmp_path, scripted_server, local_http, waits):
    server = scripted_server(BODY, [503] * 4)
    with pytest.raises(UpdateError) as info:
        common.download(server.url, tmp_path / "core.zip", quiet=True)
    assert info.value.code == "http_503"
    assert info.value.reason.endswith("(4 attempts)")
    assert server.hits == 4 and waits == [2, 5, 10]


def test_download_never_waits_past_its_deadline(tmp_path, scripted_server, local_http, waits):
    server = scripted_server(BODY, [503, 503])
    with pytest.raises(UpdateError) as info:
        common.download(server.url, tmp_path / "core.zip", timeout=6, quiet=True)
    # 2 s fit into the 6 s deadline; another 5 s do not.
    assert server.hits == 2 and waits == [2]
    assert info.value.reason.endswith("(2 attempts; no time left to try again)")


def test_a_download_that_cannot_take_its_name_is_reported_and_cleaned_up(
        tmp_path, scripted_server, local_http, waits, monkeypatch):
    server = scripted_server(BODY, [])
    dest = tmp_path / "out" / "core.zip"
    dest.parent.mkdir()
    dest.write_bytes(b"the earlier download")
    real_replace = common.os.replace

    def locked_replace(src, dst):
        if str(dst) == str(dest):             # e.g. the file is open in another program
            raise PermissionError(13, "The process cannot access the file", str(dst))
        return real_replace(src, dst)

    monkeypatch.setattr(common.os, "replace", locked_replace)
    with pytest.raises(UpdateError) as info:
        common.download(server.url, dest, quiet=True)
    assert info.value.code == "save_failed"   # not "network": nothing to try again
    assert str(dest) in info.value.reason and "cannot access the file" in info.value.reason
    assert server.hits == 1 and waits == []
    assert files_in(dest.parent) == ["core.zip"]          # no core.zip.part left
    assert dest.read_bytes() == b"the earlier download"   # the existing file is untouched


def test_https_only_is_unchanged(tmp_path, waits):
    with pytest.raises(UpdateError) as info:
        common.download("http://example.invalid/x.zip", tmp_path / "x.zip")
    assert info.value.code == "insecure_url" and waits == []
    with pytest.raises(UpdateError) as info:
        common.http_get("http://example.invalid/x")
    assert info.value.code == "insecure_url"


# --------------------------------------------------------------------------
# small API reads
# --------------------------------------------------------------------------

def test_api_read_retries_with_short_pauses(scripted_server, local_http, waits):
    server = scripted_server(b"answer", [503, "truncate"])
    assert common.http_get(server.url) == b"answer"
    assert server.hits == 3 and waits == [1, 2]


@pytest.mark.parametrize("answer", [404, 403, (403, {"X-RateLimit-Remaining": "1"})])
def test_api_read_does_not_retry_answers_that_will_not_change(scripted_server, local_http,
                                                              waits, answer):
    server = scripted_server(b"answer", [answer])
    with pytest.raises(UpdateError) as info:
        common.http_get(server.url)
    assert server.hits == 1 and waits == []
    assert info.value.reason.endswith("(1 attempt; not retried)")


def test_api_read_retries_a_rate_limit_only_when_it_ends_soon(scripted_server, local_http,
                                                              waits):
    server = scripted_server(b"answer", [(403, {"Retry-After": "1"})])
    assert common.http_get(server.url) == b"answer" and waits == [1]
    waits.clear()
    reset = str(int(time.time()) + 3600)
    server = scripted_server(b"answer", [(403, {"X-RateLimit-Remaining": "0",
                                                "X-RateLimit-Reset": reset})])
    with pytest.raises(UpdateError) as info:
        common.http_get(server.url)
    assert server.hits == 1 and waits == [] and info.value.code == "http_403"
    assert "the server asked to wait" in info.value.reason


# --------------------------------------------------------------------------
# what an offline PC costs the update checks
# --------------------------------------------------------------------------

class _Offline:
    def open(self, *args, **kwargs):
        raise urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed"))


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setattr(common, "_opener", _Offline)


def test_offline_core_check_waits_at_most_three_seconds(tmp_path, offline, waits):
    info = CoreLifecycle(tmp_path).check()
    assert info["ok"] and info["update_available"] is None
    assert "getaddrinfo failed" in info["network_error"]
    assert info["network_error"].endswith("(3 attempts)")
    assert waits == [1, 2]


def test_offline_wrapper_check_waits_at_most_three_seconds(tmp_path, offline, waits):
    info = WrapperUpdater(tmp_path, run_verify=lambda root: {"ok": True}).check()
    assert info["ok"] and info["update_available"] is None
    assert info["network_error"].endswith("(3 attempts)")
    assert waits == [1, 2]
