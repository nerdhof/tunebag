"""HTTP PeerBytes: File presence probe + Mix/Album track fetch over Peer meet."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol
from uuid import UUID

TRACK_COUNT_HEADER = "x-tunebag-tracks"


class _HttpResponse(Protocol):
    status_code: int
    headers: Mapping[str, str]
    content: bytes


class _HttpPeerClient(Protocol):
    def head(self, url: str, **kwargs: Any) -> _HttpResponse: ...

    def get(self, url: str, **kwargs: Any) -> _HttpResponse: ...

    def close(self) -> None: ...


class HttpPeerBytes:
    """``PeerBytes`` over mTLS Peer File HEAD/GET (issue 03).

    Probes with HEAD before any body GET. Incomplete / missing Release → None.
    """

    def __init__(
        self,
        *,
        name: str,
        client_factory: Callable[[], _HttpPeerClient],
    ) -> None:
        self._name = name
        self._client_factory = client_factory

    @property
    def name(self) -> str:
        return self._name

    def file_bytes(self, mix_id: UUID) -> bytes | None:
        client = self._client_factory()
        try:
            head = self._probe(client, mix_id)
            if head is None or head.headers.get(TRACK_COUNT_HEADER):
                return None
            response = client.get(f"/api/files/{mix_id}")
            if response.status_code != 200:
                return None
            return response.content
        finally:
            client.close()

    def album_track_bytes(self, mix_id: UUID) -> list[bytes] | None:
        client = self._client_factory()
        try:
            head = self._probe(client, mix_id)
            if head is None:
                return None
            raw_count = head.headers.get(TRACK_COUNT_HEADER)
            if raw_count is None:
                return None
            try:
                track_count = int(raw_count)
            except ValueError:
                return None
            if track_count < 1:
                return None
            tracks: list[bytes] = []
            for index in range(track_count):
                response = client.get(f"/api/files/{mix_id}/tracks/{index}")
                if response.status_code != 200:
                    return None
                tracks.append(response.content)
            return tracks
        finally:
            client.close()

    @staticmethod
    def _probe(client: _HttpPeerClient, mix_id: UUID) -> _HttpResponse | None:
        head = client.head(f"/api/files/{mix_id}")
        if head.status_code != 200:
            return None
        return head
