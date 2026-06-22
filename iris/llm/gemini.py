"""GeminiClient — google-genai SDK adapter implementing LLMClient.

Reads GEMINI_API_KEY from settings ONLY. Maps messages + tool schemas to Gemini
function-calling, normalises the response, with backoff / circuit breaker /
timeout. Built in STEP 0.3. Placeholder for Step 0.1.
"""

from __future__ import annotations
