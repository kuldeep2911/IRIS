"""Model router — the single source of model selection.

GOLDEN RULE #2: No Gemini model id may appear anywhere else in the codebase.
This module is intentionally the only place that names a model.

NOTE: This is the Step 0.1 placeholder so the module is importable and the file
exists. The full router (RequestClass, MODEL_MAP, classify(), model_for()) is
built in STEP 0.2.
"""

from __future__ import annotations
