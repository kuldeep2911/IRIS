"""Orchestrator — the stateless agent loop (route -> tools -> answer).

All per-request state is passed through the call chain, never stored at module
scope (GOLDEN RULE #3). Built in STEP 1.2. Placeholder for Step 0.1.
"""

from __future__ import annotations
