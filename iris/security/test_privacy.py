"""Tests for the privacy filter + outbound data sanitiser (GOLDEN RULE #5)."""

from __future__ import annotations

import json

from iris.core.context import contains_raw_body, sanitise_outbound
from iris.core.privacy import summarise_tool_output


def test_email_read_drops_body_keeps_summary():
    payload = json.dumps([
        {"id": "1", "from": "sam@x.com", "subject": "Q3 report",
         "snippet": "hi", "body": "FULL CONFIDENTIAL BODY " * 40}
    ])
    out = summarise_tool_output("gmail_search_messages", payload)
    assert "Q3 report" in out and "sam@x.com" in out
    assert "FULL CONFIDENTIAL BODY" not in out
    assert not contains_raw_body(out)


def test_sanitise_outbound_redacts_secrets():
    messages = [
        {"role": "user", "content": "here is my key AIzaSyA1234567890abcdef1234567890ABCD"},
        {"role": "system", "content": "normal text"},
    ]
    out = sanitise_outbound(messages)
    assert "AIza" not in out[0]["content"]
    assert out[1]["content"] == "normal text"


def test_contains_raw_body_detects_body_dump():
    assert contains_raw_body('{"subject":"x","body":"secret stuff"}')
    assert not contains_raw_body('{"subject":"x","snippet":"ok"}')
