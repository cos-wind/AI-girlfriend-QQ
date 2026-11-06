"""Explicit standalone core entry point, also used by atri-core."""
import argparse
import asyncio


def main():
    parser = argparse.ArgumentParser(description="ATRI core API without QQ/AstrBot")
    parser.add_argument('--env', help='配置文件路径，默认主应用 .env')
    args = parser.parse_args()
    from atri_shared.config import load_config
    from .runtime import serve
    try:
        asyncio.run(serve(load_config(args.env)))
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
