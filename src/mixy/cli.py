"""mixy command-line entry. The CLI only starts the agent; pairing is in the browser."""

from __future__ import annotations

import argparse
import logging

from mixy import __version__
from mixy.agent import DeviceAgent
from mixy.web import create_app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="mixy", description="Distributed music cache")
    parser.add_argument("--version", action="version", version=f"mixy {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Start this device's agent and web player")
    serve.add_argument("--name", required=True, help="This device's display name")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8787)
    serve.add_argument(
        "--priority",
        type=int,
        default=100,
        help="Fetch priority (lower = preferred; laptop ahead of phone)",
    )

    args = parser.parse_args(argv)

    if args.command == "serve":
        import uvicorn

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
        base_url = f"http://{args.host}:{args.port}"
        agent = DeviceAgent(args.name, priority=args.priority, base_url=base_url)
        app = create_app(agent)
        print(f"mixy agent {args.name!r} at {base_url}", flush=True)
        print(f"short_code={agent.short_code()}", flush=True)
        uvicorn.run(app, host=args.host, port=args.port)
        return

    parser.error(f"unknown command {args.command}")


if __name__ == "__main__":
    main()
