"""Local FastAPI app: HTTP transport for one device agent + web player."""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import qrcode
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from tunebag import __version__
from tunebag.agent import DeviceAgent, DeviceHoursSpec
from tunebag.domain import StarDistribution, Stars
from tunebag.pairing import payload_to_qr_text
from tunebag.source import DEFAULT_MIN_DURATION_SECONDS

STATIC_DIR = Path(__file__).parent / "static"


class PairBody(BaseModel):
    payload: dict[str, Any] | None = None
    short_code: str | None = None
    peer_url: str | None = None


class AcceptPairBody(BaseModel):
    payload: dict[str, Any]


class ProveBody(BaseModel):
    nonce: str = Field(min_length=1)


class AddArtistsBody(BaseModel):
    urls: list[str]
    min_duration_seconds: int = DEFAULT_MIN_DURATION_SECONDS


class RefreshArtistsBody(BaseModel):
    artist_ids: list[UUID] | None = None
    min_duration_seconds: int = DEFAULT_MIN_DURATION_SECONDS


class DeviceHoursBody(BaseModel):
    device_id: UUID
    budget_seconds: int = Field(gt=0)
    expires_at: datetime | None = None


class CreateIntentBody(BaseModel):
    name: str
    tags: list[str] = Field(default_factory=list)
    distribution: StarDistribution | None = None
    seed: int | None = None
    device_hours: list[DeviceHoursBody] = Field(default_factory=list)


class UpdateIntentBody(BaseModel):
    name: str | None = None
    tags: list[str] | None = None
    distribution: StarDistribution | None = None
    device_hours: list[DeviceHoursBody] | None = None


class SetDeviceHoursBody(BaseModel):
    device_id: UUID
    budget_seconds: int = Field(gt=0)
    expires_at: datetime | None = None


def _hours_spec(dh: DeviceHoursBody) -> DeviceHoursSpec:
    if dh.expires_at is None:
        return (dh.device_id, dh.budget_seconds)
    return (dh.device_id, dh.budget_seconds, dh.expires_at)


def _hours_json(dh: Any) -> dict[str, Any]:
    return {
        "device_id": str(dh.device_id),
        "budget_seconds": dh.budget_seconds,
        "expires_at": dh.expires_at.isoformat() if dh.expires_at else None,
    }


class MeteredBody(BaseModel):
    metered: bool


class CurrentMixBody(BaseModel):
    mix_id: UUID | None = None


class PlayBody(BaseModel):
    intent_id: UUID
    mix_id: UUID | None = None


class SkipBody(BaseModel):
    intent_id: UUID | None = None


class PauseBody(BaseModel):
    position_seconds: float | None = Field(default=None, ge=0)


class PlayheadBody(BaseModel):
    position_seconds: float = Field(ge=0)


class MarkPlayedBody(BaseModel):
    mix_id: UUID | None = None


class RateBody(BaseModel):
    stars: int = Field(ge=1, le=5)


class TagBody(BaseModel):
    tags: list[str] = Field(default_factory=list)


def create_app(agent: DeviceAgent) -> FastAPI:
    app = FastAPI(title="Tunebag", version=__version__)
    app.state.agent = agent

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(
            STATIC_DIR / "index.html",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/health")
    def health() -> dict:
        return {
            "ok": True,
            "version": __version__,
            "device": agent.name,
            "device_id": str(agent.device_id),
            "metered": agent.is_metered(),
            "current_mix_id": (
                str(agent.current_mix()) if agent.current_mix() is not None else None
            ),
            "fill_in_progress": agent.fill_in_progress,
        }

    @app.get("/api/metered")
    def get_metered() -> dict:
        return {"metered": agent.is_metered()}

    @app.put("/api/metered")
    def put_metered(body: MeteredBody) -> dict:
        agent.set_metered(body.metered)
        return {"ok": True, "metered": agent.is_metered()}

    @app.put("/api/current-mix")
    def put_current_mix(body: CurrentMixBody) -> dict:
        try:
            agent.set_current_mix(body.mix_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        current = agent.current_mix()
        return {
            "ok": True,
            "current_mix_id": str(current) if current is not None else None,
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

    @app.post("/api/prove")
    def prove(body: ProveBody) -> dict:
        """Challenge–response: sign a meet nonce with this Device's private key."""
        return {"signature": agent.prove_possession(body.nonce)}

    @app.get("/api/activity")
    def activity() -> dict:
        return {"entries": [entry.as_dict() for entry in agent.activity()]}

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
            agent.sync(fill=False)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"peer sync failed: {exc}") from exc
        agent.request_fill()
        return {
            "ok": True,
            "mixes": len(agent.mixes()),
            "peers": len(agent.peers()),
            "files": len(agent.files()),
            "fill_in_progress": agent.fill_in_progress,
        }

    @app.post("/api/fill")
    def fill() -> dict:
        agent.request_fill()
        return {
            "ok": True,
            "files": len(agent.files()),
            "mixes": len(agent.mixes()),
            "metered": agent.is_metered(),
            "fill_in_progress": agent.fill_in_progress,
        }

    @app.post("/api/intents/{intent_id}/fill-now")
    def fill_now(intent_id: UUID) -> dict:
        if intent_id not in {intent.id for intent in agent.intents()}:
            raise HTTPException(status_code=404, detail=f"unknown intent {intent_id}")
        agent.request_fill(override_intent_id=intent_id)
        return {
            "ok": True,
            "files": len(agent.files()),
            "mixes": len(agent.mixes()),
            "metered": agent.is_metered(),
            "intent_id": str(intent_id),
            "fill_in_progress": agent.fill_in_progress,
        }

    @app.get("/api/files")
    def files() -> dict:
        downloading = agent.downloading_mix_id
        groups = []
        for group in agent.cache_groups():
            group_id = group["id"]
            groups.append(
                {
                    "id": None if group_id is None else str(group_id),
                    "name": group["name"],
                    "overview": group["overview"],
                    "mixes": [
                        {
                            "id": str(mix["id"]),
                            "title": mix["title"],
                            "duration_seconds": mix["duration_seconds"],
                            "status": mix["status"],
                            **(
                                {"size_bytes": mix["size_bytes"]}
                                if "size_bytes" in mix
                                else {}
                            ),
                            **(
                                {
                                    "downloaded_bytes": mix["downloaded_bytes"],
                                    "total_bytes": mix["total_bytes"],
                                }
                                if mix["status"] == "loading"
                                and "downloaded_bytes" in mix
                                else {}
                            ),
                        }
                        for mix in group["mixes"]
                    ],
                }
            )
        return {
            "files": [
                {
                    "id": str(mix.id),
                    "title": mix.title,
                    "duration_seconds": mix.duration_seconds,
                }
                for mix in agent.files()
            ],
            "groups": groups,
            "cache_summary": agent.cache_summary(),
            "downloading_mix_id": None if downloading is None else str(downloading),
        }

    @app.get("/api/mixes")
    def mixes() -> dict:
        artists_by_id = {a.id: a for a in agent.artists()}
        pending_until = {
            str(p.mix_id): p.undo_until.isoformat() for p in agent.pending_rejects()
        }
        return {
            "mixes": [
                {
                    "id": str(mix.id),
                    "artist_id": str(mix.artist_id),
                    "artist": (
                        artists_by_id[mix.artist_id].name
                        if mix.artist_id in artists_by_id
                        else "Unknown"
                    ),
                    "artist_url": (
                        artists_by_id[mix.artist_id].url
                        if mix.artist_id in artists_by_id
                        else None
                    ),
                    "title": mix.title,
                    "url": mix.url,
                    "duration_seconds": mix.duration_seconds,
                    "size_bytes": mix.size_bytes,
                    "tags": mix.tags,
                    "stars": int(mix.stars) if mix.stars is not None else None,
                    "played": mix.played,
                    "rejected": mix.rejected,
                    "last_heard_at": (
                        mix.last_heard_at.isoformat()
                        if mix.last_heard_at is not None
                        else None
                    ),
                    "reject_pending_until": pending_until.get(str(mix.id)),
                }
                for mix in agent.mixes()
            ]
        }

    @app.post("/api/mixes/{mix_id}/rate")
    def rate_mix(mix_id: UUID, body: RateBody) -> dict:
        try:
            mix = agent.rate_mix(mix_id, Stars(body.stars))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "ok": True,
            "mix": {
                "id": str(mix.id),
                "stars": int(mix.stars) if mix.stars is not None else None,
            },
        }

    @app.post("/api/mixes/{mix_id}/reject")
    def reject_mix(mix_id: UUID) -> dict:
        try:
            mix = agent.reject_mix(mix_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        pending = next(
            (p for p in agent.pending_rejects() if p.mix_id == mix_id),
            None,
        )
        return {
            "ok": True,
            "mix": {
                "id": str(mix.id),
                "rejected": mix.rejected,
                "reject_pending_until": (
                    pending.undo_until.isoformat() if pending is not None else None
                ),
            },
        }

    @app.post("/api/mixes/{mix_id}/undo-reject")
    def undo_reject(mix_id: UUID) -> dict:
        undone = agent.undo_reject(mix_id)
        mix = agent.mix(mix_id)
        if mix is None:
            raise HTTPException(status_code=404, detail=f"unknown mix {mix_id}")
        return {
            "ok": True,
            "undone": undone,
            "mix": {
                "id": str(mix.id),
                "rejected": mix.rejected,
                "reject_pending_until": None,
            },
        }

    @app.post("/api/mixes/{mix_id}/un-reject")
    def un_reject(mix_id: UUID) -> dict:
        try:
            mix = agent.un_reject_mix(mix_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "ok": True,
            "mix": {
                "id": str(mix.id),
                "rejected": mix.rejected,
                "reject_pending_until": None,
            },
        }

    @app.post("/api/mixes/{mix_id}/tags")
    def tag_mix(mix_id: UUID, body: TagBody) -> dict:
        try:
            mix = agent.tag_mix(mix_id, body.tags)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"ok": True, "mix": {"id": str(mix.id), "tags": mix.tags}}

    @app.get("/api/player")
    def player_state() -> dict:
        current = agent.current_mix()
        mix = agent.mix(current) if current is not None else None
        pending_until = None
        if current is not None:
            pending = next(
                (p for p in agent.pending_rejects() if p.mix_id == current),
                None,
            )
            if pending is not None:
                pending_until = pending.undo_until.isoformat()
        return {
            "playing": agent.is_playing(),
            "intent_id": (
                str(agent.playing_intent_id())
                if agent.playing_intent_id() is not None
                else None
            ),
            "current_mix_id": str(current) if current is not None else None,
            "title": mix.title if mix is not None else None,
            "duration_seconds": mix.duration_seconds if mix is not None else None,
            "size_bytes": (
                int(mix.size_bytes)
                if mix is not None and mix.size_bytes is not None
                else None
            ),
            "position_seconds": agent.playback_position(),
            "stars": int(mix.stars) if mix is not None and mix.stars is not None else None,
            "tags": mix.tags if mix is not None else [],
            "played": mix.played if mix is not None else False,
            "rejected": mix.rejected if mix is not None else False,
            "reject_pending_until": pending_until,
        }

    @app.post("/api/player/play")
    def player_play(body: PlayBody) -> dict:
        try:
            mix = agent.play(body.intent_id, body.mix_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "ok": True,
            "playing": agent.is_playing(),
            "mix": {
                "id": str(mix.id),
                "title": mix.title,
                "duration_seconds": mix.duration_seconds,
            },
        }

    @app.post("/api/player/stop")
    def player_stop() -> dict:
        agent.stop()
        return {"ok": True, "playing": agent.is_playing()}

    @app.post("/api/player/pause")
    def player_pause(body: PauseBody = PauseBody()) -> dict:
        try:
            agent.pause(body.position_seconds)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        current = agent.current_mix()
        mix = agent.mix(current) if current is not None else None
        played = bool(mix.played) if mix is not None else False
        return {
            "ok": True,
            "playing": agent.is_playing(),
            "position_seconds": agent.playback_position(),
            "current_mix_id": str(current) if current is not None else None,
            "played": played,
            "later": agent.later_features() if played else [],
        }

    @app.post("/api/player/skip")
    def player_skip(body: SkipBody = SkipBody()) -> dict:
        try:
            mix = agent.skip(body.intent_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "ok": True,
            "playing": agent.is_playing(),
            "mix": {
                "id": str(mix.id),
                "title": mix.title,
                "duration_seconds": mix.duration_seconds,
            },
        }

    @app.post("/api/player/playhead")
    def player_playhead(body: PlayheadBody) -> dict:
        try:
            head = agent.report_playhead(body.position_seconds)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        mix = agent.mix(head.mix_id)
        return {
            "ok": True,
            "mix_id": str(head.mix_id),
            "position_seconds": head.position_seconds,
            "played": mix.played if mix is not None else False,
            "playing": agent.is_playing(),
            "later": agent.later_features() if mix is not None and mix.played else [],
        }

    @app.post("/api/player/seek")
    def player_seek(body: PlayheadBody) -> dict:
        try:
            head = agent.seek(body.position_seconds)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        mix = agent.mix(head.mix_id)
        return {
            "ok": True,
            "mix_id": str(head.mix_id),
            "position_seconds": head.position_seconds,
            "played": mix.played if mix is not None else False,
            "playing": agent.is_playing(),
            "later": agent.later_features() if mix is not None and mix.played else [],
        }

    @app.post("/api/player/mark-played")
    def player_mark_played(body: MarkPlayedBody) -> dict:
        try:
            mix = agent.mark_played(body.mix_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "ok": True,
            "mix": {"id": str(mix.id), "played": mix.played},
            "playing": agent.is_playing(),
            "later": agent.later_features(),
        }

    @app.get("/api/later")
    def later() -> dict:
        return {"features": agent.later_features()}

    @app.get("/api/artists")
    def artists() -> dict:
        mixes = agent.mixes()
        return {
            "artists": [
                {
                    "id": str(artist.id),
                    "name": artist.name,
                    "url": artist.url,
                    "platform": artist.platform.value,
                    "mixes": sum(1 for m in mixes if m.artist_id == artist.id),
                    "rejected_mixes": sum(
                        1 for m in mixes if m.artist_id == artist.id and m.rejected
                    ),
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

    @app.post("/api/artists/refresh")
    def refresh_artists(body: RefreshArtistsBody) -> dict:
        try:
            mixes = agent.refresh_artists(
                body.artist_ids,
                min_duration_seconds=body.min_duration_seconds,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
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

    @app.delete("/api/artists/{artist_id}")
    def delete_artist(artist_id: UUID) -> dict:
        try:
            agent.delete_artist(artist_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"ok": True, "deleted": str(artist_id)}

    @app.get("/api/tags")
    def list_tags(q: str = "") -> dict:
        if q:
            return {"tags": agent.suggest_tags(q)}
        return {"tags": agent.catalog.all_tags()}

    @app.get("/api/intents")
    def intents() -> dict:
        return {
            "intents": [
                {
                    "id": str(intent.id),
                    "name": intent.name,
                    "tags": intent.tags,
                    "distribution": intent.distribution.model_dump(),
                    "seed": intent.seed,
                    "device_hours": [_hours_json(dh) for dh in intent.device_hours],
                }
                for intent in agent.intents()
            ]
        }

    @app.post("/api/intents")
    def create_intent(body: CreateIntentBody) -> dict:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="name is required")
        try:
            intent = agent.create_intent(
                name,
                tags=body.tags,
                distribution=body.distribution,
                seed=body.seed,
                device_hours=[_hours_spec(dh) for dh in body.device_hours],
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        agent.request_fill()
        return {
            "ok": True,
            "intent": {"id": str(intent.id), "name": intent.name},
            "files": len(agent.files()),
            "fill_in_progress": agent.fill_in_progress,
        }

    @app.patch("/api/intents/{intent_id}")
    def update_intent(intent_id: UUID, body: UpdateIntentBody) -> dict:
        if (
            body.name is None
            and body.tags is None
            and body.distribution is None
            and body.device_hours is None
        ):
            raise HTTPException(status_code=400, detail="provide at least one field to update")
        name = body.name.strip() if body.name is not None else None
        if body.name is not None and not name:
            raise HTTPException(status_code=400, detail="name is required")
        try:
            intent = agent.update_intent(
                intent_id,
                name=name,
                tags=body.tags,
                distribution=body.distribution,
                device_hours=(
                    [_hours_spec(dh) for dh in body.device_hours]
                    if body.device_hours is not None
                    else None
                ),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        agent.request_fill()
        return {
            "ok": True,
            "intent": {"id": str(intent.id), "name": intent.name},
            "files": len(agent.files()),
            "fill_in_progress": agent.fill_in_progress,
        }

    @app.delete("/api/intents/{intent_id}")
    def delete_intent(intent_id: UUID) -> dict:
        try:
            agent.delete_intent(intent_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"ok": True, "deleted": str(intent_id)}

    @app.put("/api/intents/{intent_id}/hours")
    def set_intent_hours(intent_id: UUID, body: SetDeviceHoursBody) -> dict:
        hours_kwargs: dict[str, Any] = {}
        if "expires_at" in body.model_dump(exclude_unset=True):
            hours_kwargs["expires_at"] = body.expires_at
        try:
            intent = agent.set_device_hours(
                intent_id,
                body.device_id,
                body.budget_seconds,
                **hours_kwargs,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        agent.request_fill()
        return {
            "ok": True,
            "intent": {
                "id": str(intent.id),
                "device_hours": [_hours_json(dh) for dh in intent.device_hours],
            },
            "files": len(agent.files()),
            "fill_in_progress": agent.fill_in_progress,
        }

    @app.post("/api/intents/{intent_id}/refresh-sequence")
    def refresh_intent_sequence(intent_id: UUID) -> dict:
        try:
            intent = agent.refresh_intent_sequence(intent_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        agent.request_fill()
        return {
            "ok": True,
            "intent": {
                "id": str(intent.id),
                "name": intent.name,
                "seed": intent.seed,
            },
            "files": len(agent.files()),
            "fill_in_progress": agent.fill_in_progress,
        }

    @app.get("/api/intents/{intent_id}/sequence")
    def intent_sequence(intent_id: UUID) -> dict:
        sequence = agent.sequence(intent_id)
        if sequence is None:
            raise HTTPException(status_code=404, detail="sequence not found")
        mix_by_id = {mix.id: mix for mix in agent.mixes()}
        device_names = {
            device.id: device.name for device in agent.catalog.devices.values()
        }
        local = agent.assignment(intent_id)
        assignments = [
            assignment
            for (iid, _device_id), assignment in agent.catalog.assignments.items()
            if iid == intent_id
        ]
        return {
            "intent_id": str(sequence.intent_id),
            "entries": [
                {
                    "mix_id": str(entry.mix_id),
                    "position": entry.position,
                    "bucket": entry.bucket.value,
                    "title": (
                        mix_by_id[entry.mix_id].title
                        if entry.mix_id in mix_by_id
                        else None
                    ),
                    "duration_seconds": (
                        mix_by_id[entry.mix_id].duration_seconds
                        if entry.mix_id in mix_by_id
                        else None
                    ),
                }
                for entry in sequence.entries
            ],
            "assignment": (
                {
                    "device_id": str(local.device_id),
                    "device_name": device_names.get(local.device_id),
                    "mix_ids": [str(mix_id) for mix_id in local.mix_ids],
                    "budget_seconds": local.budget_seconds,
                }
                if local is not None
                else None
            ),
            "assignments": [
                {
                    "device_id": str(assignment.device_id),
                    "device_name": device_names.get(assignment.device_id),
                    "mix_ids": [str(mix_id) for mix_id in assignment.mix_ids],
                    "budget_seconds": assignment.budget_seconds,
                }
                for assignment in assignments
            ],
        }

    return app


# Default app for import without CLI name wiring.
app = create_app(DeviceAgent("tunebag"))
