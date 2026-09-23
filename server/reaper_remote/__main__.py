"""Entry point: `reaper-remote` / `python -m reaper_remote`."""

from __future__ import annotations

import uvicorn

from .app import create_app
from .config import load


def main() -> None:
    cfg = load()
    uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port, log_level="info")


if __name__ == "__main__":
    main()
