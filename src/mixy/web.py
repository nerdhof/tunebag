"""Local FastAPI app: HTTP transport for one device agent + web player."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import httpx
import qrcode
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from mixy import __version__
from mixy.agent import DeviceAgent
from mixy.pairing import payload_to_qr_text
from mixy.source import DEFAULT_MIN_DURATION_SECONDS

STATIC_DIR = Path(__file__).parent / "static"


class PairBody(BaseModel):
    payload: dict[str, Any] | None = None
    short_code: str | None = None
    peer_url: str | None = None


class AcceptPairBody(BaseModel):
    payload: dict[str, Any]


class AddArtistsBody(BaseModel):
    urls: list[str]
    min_duration_seconds: int = DEFAULT_MIN_DURATION_SECONDS


def create_app(agent: DeviceAgent) -> FastAPI:
    app = FastAPI(title="mixy", version=__version__)
    app.state.agent = agent

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/health")
    def health() -> dict:
        return {
            "ok": True,
            "version": __version__,
            "device": agent.name,
            "device_id": str(agent.device_id),
        }

    @app.get("/api/pairing")
    def pairing() -> dict:
        return agent.pairing_payload()

    @app.get("/api/pairing/qr.png")
    def pairing_qr() -> Response:
        img = qrcode.make(payload_to_qr_text(agent.pairing_payload()))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return Response(buf.getvalue(), media_type="image/png")

    @app.get("/api/peers")
    def peers() -> dict:
        return {
            "peers": [
                {
                    "id": str(peer.id),
                    "name": peer.name,
                    "public_key_pem": peer.public_key_pem,
                    "priority": peer.priority,
                }
                for peer in agent.peers()
            ]
        }

    @app.get("/api/events")
    def events() -> dict:
        return {"events": [event.model_dump(mode="json") for event in agent.export_events()]}

    @app.post("/api/pair")
    def pair(body: PairBody) -> dict:
        try:
            if body.payload is not None:
                peer = agent.pair(body.payload)
            elif body.short_code and body.peer_url:
                peer = agent.pair_by_short_code(body.short_code, peer_url=body.peer_url)
            else:
                raise HTTPException(
                    status_code=400,
                    detail="provide payload, or short_code with peer_url",
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"peer unreachable: {exc}") from exc
        return {"ok": True, "peer": {"id": str(peer.id), "name": peer.name}}

    @app.post("/api/pair/accept")
    def accept_pair(body: AcceptPairBody) -> dict:
        try:
            peer = agent.accept_pair_offer(body.payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "peer": {"id": str(peer.id), "name": peer.name}}

    @app.post("/api/sync")
    def sync() -> dict:
        try:
            agent.sync()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"peer sync failed: {exc}") from exc
        return {"ok": True, "mixes": len(agent.mixes()), "peers": len(agent.peers())}

    @app.get("/api/mixes")
    def mixes() -> dict:
        return {
            "mixes": [
                {
                    "id": str(mix.id),
                    "title": mix.title,
                    "url": mix.url,
                    "duration_seconds": mix.duration_seconds,
                    "tags": mix.tags,
                }
                for mix in agent.mixes()
            ]
        }

    @app.get("/api/artists")
    def artists() -> dict:
        return {
            "artists": [
                {
                    "id": str(artist.id),
                    "name": artist.name,
                    "url": artist.url,
                    "platform": artist.platform.value,
                }
                for artist in agent.artists()
            ]
        }

    @app.post("/api/artists")
    def add_artists(body: AddArtistsBody) -> dict:
        urls = [u.strip() for u in body.urls if u.strip()]
        if not urls:
            raise HTTPException(status_code=400, detail="provide at least one artist URL")
        try:
            mixes = agent.add_artists(
                urls,
                min_duration_seconds=body.min_duration_seconds,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"source fetch failed: {exc}") from exc
        return {
            "ok": True,
            "added": len(mixes),
            "mixes": len(agent.mixes()),
            "artists": len(agent.artists()),
        }

    @app.get("/api/tags")
    def list_tags(q: str = "") -> dict:
        if q:
            return {"tags": agent.catalog.suggest_tags(q)}
        return {"tags": agent.catalog.all_tags()}

    return app


# Default app for import without CLI name wiring.
app = create_app(DeviceAgent("mixy"))
