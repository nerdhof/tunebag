"""Display-time YouTube title declutter (Catalog stays raw)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tunebag.agent import DeviceAgent
from tunebag.domain import Platform, Stars
from tunebag.player import NullPlayer
from tunebag.source import ArtistListing, FakeSource, Track, Upload
from tunebag.title_display import display_title
from tunebag.web import create_app


@pytest.mark.parametrize(
    ("raw", "artist", "want"),
    [
        (
            "System Of A Down - Hypnotize (Official HD Video)",
            "System Of A Down",
            "Hypnotize",
        ),
        (
            "System Of A Down - Soldier Side (Official Audio)",
            "System Of A Down",
            "Soldier Side",
        ),
        ("TOOL - Vicarious (Official Video)", "TOOL", "Vicarious"),
        ("Song (OFFICIAL LYRIC VIDEO)", None, "Song"),
        ("Song (Offizielles Musikvideo)", None, "Song"),
        ("Song (Offizielles Video - Refurbished 2025)", None, "Song"),
        (
            "Serj Tankian - Left Of Center - Official Music Video",
            "Serj Tankian",
            "Left Of Center",
        ),
        (
            "Serj Tankian - Cornucopia Lyric Video",
            "Serj Tankian",
            "Cornucopia",
        ),
        ("Fear Inoculum (Audio)", "TOOL", "Fear Inoculum"),
        ("Init (Official Visualizer)", "Nine Inch Nails", "Init"),
        ("Song (Audio Only)", None, "Song"),
        ("Song [Official Music Video]", None, "Song"),
        ("", None, ""),
        ("   ", None, ""),
    ],
)
def test_display_title_strips_packaging(
    raw: str, artist: str | None, want: str
) -> None:
    assert display_title(raw, artist=artist) == want


@pytest.mark.parametrize(
    "raw",
    [
        "Song (Live aus Berlin)",
        "Beuteltier (feat. Käptn Peng)",
        "Ölsardinenindustrie (Remastered 2022)",
        'All Aboard (from "The Menu" Soundtrack)',
        "I Am Not Alone (Original Motion Picture Soundtrack)",
        "Song (Instrumental)",
        "Song (2019 Remix)",
    ],
)
def test_display_title_keeps_meaningful_suffixes(raw: str) -> None:
    assert display_title(raw, artist="Someone") == raw


def test_display_title_unknown_artist_still_strips_packaging() -> None:
    assert (
        display_title("Hypnotize (Official HD Video)", artist="Unknown")
        == "Hypnotize"
    )


def test_display_title_empty_after_strip_returns_original() -> None:
    assert display_title("(Official Video)", artist=None) == "(Official Video)"


def test_player_api_serves_cleaned_track_titles_catalog_stays_raw(
    tmp_path: Path,
) -> None:
    raw_track = "System Of A Down - Hypnotize (Official HD Video)"
    raw_album = "Hypnotize (Official Video)"
    track_urls = [
        "https://www.youtube.com/watch?v=t1",
        "https://www.youtube.com/watch?v=t2",
    ]
    source = FakeSource()
    source.add_listing(
        "https://www.youtube.com/@systemofadown/releases",
        ArtistListing(
            platform=Platform.YOUTUBE,
            platform_id="UC-soad",
            name="System Of A Down",
            url="https://www.youtube.com/@systemofadown/releases",
            uploads=[
                Upload(
                    platform=Platform.YOUTUBE,
                    platform_id="olak-hypnotize",
                    title=raw_album,
                    url="https://www.youtube.com/playlist?list=OLAK5hyp",
                    duration_seconds=0,
                    tracks=(
                        Track(
                            platform_id="t1",
                            title=raw_track,
                            url=track_urls[0],
                            duration_seconds=900,
                            size_bytes=1_000_000,
                        ),
                        Track(
                            platform_id="t2",
                            title="Lonely Day (Live aus Berlin)",
                            url=track_urls[1],
                            duration_seconds=600,
                            size_bytes=500_000,
                        ),
                    ),
                ),
            ],
        ),
    )
    for url in track_urls:
        source.bytes_by_url[url] = f"audio:{url}".encode()

    agent = DeviceAgent(
        "laptop",
        source=source,
        data_dir=tmp_path / "laptop",
        player=NullPlayer(),
    )
    added = agent.add_artists(["https://www.youtube.com/@systemofadown/releases"])
    assert len(added) == 1
    album = added[0]
    assert album.title == raw_album
    assert album.tracks[0].title == raw_track

    agent.rate_mix(album.id, Stars.FIVE)
    intent = agent.create_intent(
        "Play",
        seed=1,
        device_hours=[(agent.device_id, 3600)],
    )
    agent.fill_caches()
    agent.play(intent.id, album.id)

    client = TestClient(create_app(agent))
    player = client.get("/api/player").json()
    assert player["title"] == "Hypnotize"
    assert player["tracks"] == [
        {"title": "Hypnotize", "duration_seconds": 900},
        {"title": "Lonely Day (Live aus Berlin)", "duration_seconds": 600},
    ]

    mixes = client.get("/api/mixes").json()["mixes"]
    assert mixes[0]["title"] == "Hypnotize"
    assert agent.catalog.mixes[album.id].title == raw_album
    assert agent.catalog.mixes[album.id].tracks[0].title == raw_track

    playlog = client.get("/api/playlog", params={"intent_id": str(intent.id)}).json()
    current = next(e for e in playlog["items"] if e["offset"] == 0)
    assert current["title"] == "Hypnotize"
