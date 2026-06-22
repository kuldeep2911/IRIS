"""Run IRIS: ``python -m iris`` (equivalent to ``make dev``).

Starts the FastAPI gateway with uvicorn. Host/port/log level come from settings
(GOLDEN RULE #8: config in one place).
"""

from __future__ import annotations

import uvicorn

from iris.config.settings import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "iris.gateway.api:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.ENV == "local",
        log_level=settings.LOG_LEVEL.lower(),
    )


if __name__ == "__main__":
    main()
