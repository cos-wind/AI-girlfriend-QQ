from __future__ import annotations

import asyncio

from .config import load_config
from .onebot import run_server


def main() -> None:
    config = load_config()
    try:
        asyncio.run(run_server(config))
    except KeyboardInterrupt:
        print("\n[atri] stopped")


if __name__ == "__main__":
    main()
