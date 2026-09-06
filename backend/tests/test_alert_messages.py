"""Alerts that say something.

Three production alarms arrived with nothing actionable in them:

* `upstream circuit open (transport error: )` — `str()` is EMPTY on most httpx transport
  exceptions, so the one field that mattered was blank.
* `[Errno 13] Permission denied: '/var/backups/encar'` — reported as if the backup had
  failed, when the backup was fine and the health check simply could not read the folder.
* `никога не е завършвал успешно` — no hint of how far the sync got or what upstream said.
"""
import asyncio
import os
import tempfile

import httpx
import pytest

import encar
import watchdog


@pytest.mark.parametrize("error", [
    httpx.ProxyError(""),
    httpx.ConnectError(""),
    httpx.ReadTimeout(""),
    httpx.ConnectTimeout(""),
])
def test_a_message_less_transport_error_still_says_what_it_was(error):
    why = encar._why(error)
    assert type(error).__name__ in why
    assert why.strip() not in ("", ":")
    # And which way the request went out: the residential proxy is the usual suspect.
    assert "route=" in why


def test_a_transport_error_with_a_message_keeps_it():
    why = encar._why(RuntimeError("connection reset by peer"))
    assert "connection reset by peer" in why
    assert "RuntimeError" in why


def test_the_proxy_url_never_leaks_into_an_alert(monkeypatch):
    monkeypatch.setenv("ENCAR_PROXY_URL", "http://user:pass@resi.example.net:8080")
    why = encar._why(httpx.ProxyError("failed for http://user:pass@resi.example.net:8080"))
    assert "pass" not in why and "resi.example.net" not in why
    assert "<proxy>" in why


def test_an_unreadable_backup_folder_reports_the_fix(monkeypatch):
    """The dumps are root-owned; the check runs as www-data. Say that, with the remedy."""
    with tempfile.TemporaryDirectory() as folder:
        monkeypatch.setenv("BACKUP_DIR", folder)

        def denied(_path):
            # chmod 000 proves nothing in a container that runs as root, so the refusal
            # the www-data backend actually gets is injected directly.
            raise PermissionError(13, "Permission denied", folder)

        # Scoped: `os.scandir` is global and rmtree needs it back for the cleanup.
        with monkeypatch.context() as patched:
            patched.setattr(watchdog.os, "scandir", denied)
            with pytest.raises(RuntimeError) as raised:
                asyncio.run(watchdog._probe_backup())
        message = str(raised.value)
        assert "chown" in message
        assert folder in message
        # Not an errno dressed up as a failed backup.
        assert "Errno" not in message


def test_a_missing_backup_folder_is_skipped_not_alarmed(monkeypatch):
    monkeypatch.setenv("BACKUP_DIR", "/var/backups/definitely-not-here")
    with pytest.raises(watchdog.Skip):
        asyncio.run(watchdog._probe_backup())
