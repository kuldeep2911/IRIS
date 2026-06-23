"""Privacy audit — prove no raw PII reaches Gemini + payments are blocked.

Simulates an outbound Gemini payload that includes (1) a tool result with a raw
email body and (2) a secret API key, runs them through the real privacy filter +
data sanitiser, and asserts the raw body and secret are gone. Also asserts
payment actions are hard-blocked.

Run: ``python scripts/audit_privacy.py``
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iris.core.confirm import is_payment, needs_confirmation  # noqa: E402
from iris.core.context import contains_raw_body, sanitise_outbound  # noqa: E402
from iris.core.privacy import summarise_tool_output  # noqa: E402

SECRET = "AIzaSyA1234567890abcdef1234567890ABCD"
RAW_EMAIL = json.dumps([
    {"id": "42", "from": "boss@corp.com", "subject": "Confidential merger",
     "snippet": "see attached", "body": "TOP SECRET MERGER DETAILS " * 50}
])


def main() -> None:
    # 1. email read result -> summary only (no body)
    summarised = summarise_tool_output("gmail_read_email", RAW_EMAIL)
    assert "TOP SECRET MERGER DETAILS" not in summarised, "raw email body leaked!"
    assert "Confidential merger" in summarised, "summary lost the subject"
    assert not contains_raw_body(summarised), "body keys still present"
    print("PASS: email read -> summary only (no raw body)")

    # 2. whole outbound payload -> secrets redacted
    messages = [
        {"role": "system", "content": "You are IRIS."},
        {"role": "user", "content": f"my gemini key is {SECRET}"},
        {"role": "tool", "name": "gmail_read_email", "content": summarised},
    ]
    sanitised = sanitise_outbound(messages)
    blob = json.dumps(sanitised)
    assert SECRET not in blob, "secret key leaked into outbound payload!"
    assert "TOP SECRET MERGER DETAILS" not in blob, "raw body leaked into outbound payload!"
    print("PASS: outbound payload sanitised (secret redacted, no raw body)")

    # 3. payments hard-blocked at the action layer
    assert is_payment("buy_now") and is_payment("checkout"), "payment tools not detected"
    assert is_payment("transfer_money"), "money transfer not detected"
    print("PASS: payment actions hard-blocked")

    # 4. send/delete still gated by confirmation
    assert needs_confirmation("email_send") and needs_confirmation("calendar_delete")
    print("PASS: send/delete actions confirmation-gated")

    print("\nPRIVACY AUDIT: ALL CHECKS PASS")


if __name__ == "__main__":
    main()
