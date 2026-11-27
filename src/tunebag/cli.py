"""Tunebag command-line entry. The CLI only starts the agent; pairing is in the browser."""

from __future__ import annotations

import argparse
import logging
import threading
from pathlib import Path

from tunebag import __version__
from tunebag.agent import DeviceAgent
from tunebag.device_tls import write_tls_files
from tunebag.discovery import DISCOVERY_REFRESH_SECONDS, MdnsLanDiscovery
from tunebag.peer_mtls import (
    build_peer_server_ssl_context,
    install_uvicorn_client_cert_scope,
)
from tunebag.web import create_peer_app, create_ui_app
from tunebag.ytdlp_fetch import YtdlpCookies


def default_data_dir(name: str) -> Path:
    """Per-instance state under ~/.tunebag/<safe_name>/ for multi-serve on one machine."""
    safe = name.strip().replace("/", "_").replace("\\", "_").replace("\0", "_")
    if not safe:
        raise ValueError("device name must not be empty")
    return Path.home() / ".tunebag" / safe


def _start_discovery_ticker(agent: DeviceAgent, stop: threading.Event) -> None:
    """Slow periodic browse while no trusted Peer has a live session."""

    def _loop() -> None:
        while not stop.wait(DISCOVERY_REFRESH_SECONDS):
            try:
                agent.tick_discovery()
            except Exception:
                logging.getLogger(__name__).debug(
                    "discovery tick failed", exc_info=True
                )

    threading.Thread(target=_loop, name="tunebag-discovery", daemon=True).start()


def ytdlp_cookies_from_args(args: argparse.Namespace) -> YtdlpCookies | None:
    """Build YouTube cookie config from serve --cookies / --cookies-from-browser."""
    if args.cookies:
        return YtdlpCookies.from_cookiefile(args.cookies)
    browser = getattr(args, "cookies_from_browser", None)
    if browser:
        return YtdlpCookies.from_browser(browser)
    return None


def _run_peer_listener(
    *,
    agent: DeviceAgent,
    host: str,
    peer_port: int,
    stop: threading.Event,
) -> None:
    """Serve the Peer HTTPS listener in a background thread.

    CERT_OPTIONAL so pairing TOFU stays reachable; Event pull / sync / yield
    require a client cert pinned to a trusted Peer (app-level 401 hard cut).
    """
    import uvicorn

    install_uvicorn_client_cert_scope()
    cert_path, key_path = write_tls_files(
        agent.data_dir / "tls",
        cert_pem=agent.tls_cert_pem,
        key_pem=agent.tls_key_pem,
    )
    trusted = [
        peer.tls_cert_pem
        for peer in agent.peers()
        if peer.tls_cert_pem
    ]
    ssl_ctx = build_peer_server_ssl_context(
        cert_file=cert_path,
        key_file=key_path,
        trusted_client_pems=trusted,
    )
    agent.bind_peer_ssl_context(ssl_ctx)
    config = uvicorn.Config(
        create_peer_app(agent),
        host=host,
        port=peer_port,
        ssl_certfile=str(cert_path),
        ssl_keyfile=str(key_path),
        ssl_context_factory=lambda _cfg, _default: ssl_ctx,
        log_level="info",
    )
    server = uvicorn.Server(config)

    def _serve() -> None:
        try:
            server.run()
        finally:
            stop.set()

    threading.Thread(target=_serve, name="tunebag-peer-listener", daemon=True).start()

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="tunebag",
        description="Tunebag — music packed for every device",
    )
    parser.add_argument("--version", action="version", version=f"tunebag {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Start this device's agent and web player")
    serve.add_argument("--name", required=True, help="This device's display name")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument(
        "--port",
        type=int,
        default=8787,
        help="Cleartext UI listener port (companion browser)",
    )
    serve.add_argument(
        "--peer-port",
        type=int,
        default=None,
        help="HTTPS Peer mTLS listener port (default: UI port + 1)",
    )
    serve.add_argument(
        "--priority",
        type=int,
        default=100,
        help="Fetch priority (lower = preferred; laptop ahead of phone)",
    )
    cookies_group = serve.add_mutually_exclusive_group()
    cookies_group.add_argument(
        "--cookies",
        metavar="FILE",
        help="Netscape cookies file for YouTube (forwarded to yt-dlp)",
    )
    cookies_group.add_argument(
        "--cookies-from-browser",
        metavar="BROWSER[+KEYRING][:PROFILE][::CONTAINER]",
        help="Load YouTube cookies from a browser (forwarded to yt-dlp)",
    )

    args = parser.parse_args(argv)

    if args.command == "serve":
        import uvicorn

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
        try:
            data_dir = default_data_dir(args.name)
        except ValueError as exc:
            parser.error(str(exc))
        try:
            cookies = ytdlp_cookies_from_args(args)
        except ValueError as exc:
            parser.error(str(exc))
        peer_port = args.peer_port if args.peer_port is not None else args.port + 1
        ui_url = f"http://{args.host}:{args.port}"
        # Peer Locators / mDNS / paste target the HTTPS Peer listener.
        peer_url = f"https://{args.host}:{peer_port}"
        discovery = MdnsLanDiscovery()
        agent = DeviceAgent(
            args.name,
            priority=args.priority,
            base_url=peer_url,
            ui_url=ui_url,
            data_dir=data_dir,
            discovery=discovery,
            cookies=cookies,
        )
        if agent.seed_default_intents_if_empty():
            print(
                "seeded Explore intent (10|10|10|10|10|50, 8h this device)",
                flush=True,
            )
        # Replay leaves assignments without File bytes until fill runs.
        agent.request_fill()
        stop = threading.Event()
        _start_discovery_ticker(agent, stop)
        _run_peer_listener(
            agent=agent, host=args.host, peer_port=peer_port, stop=stop
        )
        ui_app = create_ui_app(agent)
        print(f"tunebag UI {args.name!r} at {ui_url}", flush=True)
        print(f"tunebag Peer listener at {peer_url}", flush=True)
        print(f"data_dir={data_dir}", flush=True)
        print(f"fingerprint={agent.fingerprint()}", flush=True)
        print(f"tls_fingerprint={agent.tls_cert_fingerprint()}", flush=True)
        try:
            uvicorn.run(ui_app, host=args.host, port=args.port)
        finally:
            stop.set()
            discovery.withdraw()
        return

    parser.error(f"unknown command {args.command}")


if __name__ == "__main__":
    main()
