"""Mem0 client — the Add/Update/Delete/No-op (AUDN) learning loop.

Locally summarises each turn (no raw bodies to Gemini), extracts candidate
facts, reconciles against existing memories, writes survivors with provenance.
Built in STEP 3.2. Placeholder for Step 0.1.
"""

from __future__ import annotations
