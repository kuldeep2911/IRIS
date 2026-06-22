"""Smoke test: prove the Gemini adapter + router work end to end.

Sends a tiny prompt using the model the router picks for a SIMPLE request and
prints the reply text + token usage. Requires a real GEMINI_API_KEY in .env.

Run: ``python scripts/smoke_gemini.py``  (expect: "IRIS online" + token usage)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Make the repo root importable when run as `python scripts/smoke_gemini.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iris.llm import get_llm
from iris.router.model_router import RequestClass, model_for


async def main() -> None:
    choice = model_for(RequestClass.SIMPLE)  # router picks the model id, not us
    llm = get_llm()

    messages = [
        {"role": "system", "content": "You are IRIS. Follow instructions exactly."},
        {"role": "user", "content": "Say 'IRIS online' and nothing else."},
    ]

    resp = await llm.complete(
        choice.model,
        messages,
        max_output_tokens=choice.max_output_tokens,
    )

    print("model:", resp.model)
    print("reply:", resp.text.strip())
    print(
        "usage:",
        f"input={resp.usage.input_tok} output={resp.usage.output_tok} "
        f"total={resp.usage.total_tok}",
    )


if __name__ == "__main__":
    asyncio.run(main())
