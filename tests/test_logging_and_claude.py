import logging

from sasayaki.logging_setup import _Redact
from sasayaki.translate.claude import ClaudeBackend


def test_log_filter_redacts_api_keys():
    rec = logging.LogRecord("x", logging.INFO, "f", 1, "key was %s here", ("sk-ant-api03-AbC_123-xyz",), None)
    assert _Redact().filter(rec)
    assert "sk-ant-***" in rec.msg and "AbC_123" not in rec.msg


def test_workspace_id_is_sent_as_header_only_when_set():
    with_ws = ClaudeBackend("sk-ant-test", workspace_id="  wrkspc_123 ")
    assert with_ws.client.default_headers["anthropic-workspace-id"] == "wrkspc_123"
    without = ClaudeBackend("sk-ant-test")
    assert "anthropic-workspace-id" not in without.client.default_headers
