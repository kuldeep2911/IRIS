"""Context assembly — build the prompt context (memory + screen + session).

GOLDEN RULE #5: only SANITISED context reaches Gemini; raw bodies never leave
the machine. The data sanitiser lives here. Built in STEP 1.2, extended in
STEP 3.1. Placeholder for Step 0.1.
"""

from __future__ import annotations
