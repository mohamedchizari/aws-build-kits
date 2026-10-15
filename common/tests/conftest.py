"""Shared test setup. Everything here keeps the tests offline and credential-free."""
from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

import pytest

COMMON_DIR = Path(__file__).resolve().parents[1]
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

# Never look for real credentials, config files or the instance metadata service.
os.environ["AWS_EC2_METADATA_DISABLED"] = "true"
os.environ["AWS_CONFIG_FILE"] = os.devnull
os.environ["AWS_SHARED_CREDENTIALS_FILE"] = os.devnull
for _name in ("AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_REGION", "AWS_DEFAULT_REGION", "KIT_PREFIX"):
    os.environ.pop(_name, None)


class NetworkUsed(AssertionError):
    pass


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any attempt to open a socket fails the test."""

    def refuse(*args, **kwargs):
        raise NetworkUsed("a test tried to use the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    yield


@pytest.fixture(autouse=True)
def no_real_kit_folders(monkeypatch, tmp_path_factory):
    """The audit reads the kit folders beside common/ by default. Tests never read the real ones."""
    import whats_running

    monkeypatch.setattr(whats_running, "KITS_DIR", tmp_path_factory.mktemp("no_kits"))
    # The audit also reads the budget record that budget_alarm.py keeps in common/.state.json.
    # Tests never read the real one; raising=False so that this file also loads against an older audit.
    monkeypatch.setattr(whats_running, "BUDGET_STATE_FILE", tmp_path_factory.mktemp("no_budget") / ".state.json", raising=False)
    yield
