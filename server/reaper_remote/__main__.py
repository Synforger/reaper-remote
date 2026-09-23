"""Entry point: `reaper-remote` / `python -m reaper_remote`."""

from __future__ import annotations

import logging

import uvicorn

from .app import create_app
from .config import load


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s: %(message)s")
    cfg = load()
    uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port, log_level="info")


if __name__ == "__main__":
    main()
