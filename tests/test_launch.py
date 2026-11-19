"""The one-click launcher: package-install caching and port helpers (no processes started)."""

import socket

import launch


def test_requirements_hash_is_stable():
    assert launch.requirements_hash() == launch.requirements_hash()
    assert len(launch.requirements_hash()) == 64


def test_packages_not_reinstalled_when_unchanged(tmp_path, monkeypatch):
    marker = tmp_path / "marker"
    marker.write_text(launch.requirements_hash())
    monkeypatch.setattr(launch, "MARKER", marker)
    calls = []
    monkeypatch.setattr(launch.subprocess, "call", lambda *a, **k: calls.append(a) or 0)
    launch.ensure_packages()
    assert calls == []


def test_packages_installed_when_changed(tmp_path, monkeypatch):
    marker = tmp_path / "marker"
    marker.write_text("old")
    monkeypatch.setattr(launch, "MARKER", marker)
    calls = []
    monkeypatch.setattr(launch.subprocess, "call", lambda cmd, **k: calls.append(cmd) or 0)
    launch.ensure_packages()
    assert calls and "pip" in calls[0] and "-r" in calls[0]
    assert marker.read_text() == launch.requirements_hash()


def test_port_open_and_wait_for_timeout():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        assert launch.port_open(port)
    assert launch.wait_for("http://127.0.0.1:9/health", None, 0.6) is False
