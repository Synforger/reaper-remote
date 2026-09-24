"""Entry point: `reaper-remote [publish [RTSP_URL]]` / `python -m reaper_remote`.

- no argument: run the HTTP server
- `publish`: capture the input device and publish it to mediamtx (mediamtx runs
  this on demand; without a URL it uses mediamtx's RTSP_PORT and MTX_PATH)
"""

from __future__ import annotations

import logging
import sys

from .config import load


def main() -> None:
    # Timestamped, so a report of choppy audio can be matched to its lines.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s:     %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    args = sys.argv[1:]
    cfg = load()
    if args[:1] == ["publish"]:
        from .publish import main as publish_main

        publish_main(cfg, args[1:])
        return
    if args:
        sys.exit(f"usage: reaper-remote [publish [RTSP_URL]] (got {' '.join(args)!r})")

    import uvicorn

    from .app import create_app

    uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port, log_level="info")


if __name__ == "__main__":
    main()
