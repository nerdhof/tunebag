"""YouTubeSource — injectable yt-dlp extract, no live Google."""

from __future__ import annotations

import pytest

from tunebag.domain import Platform
from tunebag.source import YouTubeSource

CHANNEL_ID = "UCtoolchannel00000000000"
OLAK_ID = "OLAK5uy_exampleAlbumPlaylist01"
VIDEO_A = "abcdefghijk"
VIDEO_B = "lmnopqrstuv"


def _releases_info(*, entries: list[dict]) -> dict:
    return {
        "id": CHANNEL_ID,
        "channel_id": CHANNEL_ID,
        "channel": "TOOL",
        "uploader": "TOOL",
        "uploader_id": CHANNEL_ID,
        "title": "TOOL - Releases",
        "entries": entries,
    }


def _olak_entry(*, olak_id: str = OLAK_ID, title: str = "Fear Inoculum") -> dict:
    return {
        "id": olak_id,
        "title": title,
        "url": f"https://www.youtube.com/playlist?list={olak_id}",
        "_type": "url",
    }


def _pl_entry() -> dict:
    return {
        "id": "PLuserplaylist000000000000000",
        "title": "Fan mixes",
        "url": "https://www.youtube.com/playlist?list=PLuserplaylist000000000000000",
        "_type": "url",
    }


def _album_info(
    *,
    olak_id: str = OLAK_ID,
    title: str = "Fear Inoculum",
    tracks: list[dict] | None = None,
) -> dict:
    if tracks is None:
        tracks = [
            {
                "id": VIDEO_A,
                "title": "Fear Inoculum",
                "duration": 600,
                "url": f"https://www.youtube.com/watch?v={VIDEO_A}&list={olak_id}",
            },
            {
                "id": VIDEO_B,
                "title": "Pneuma",
                "duration": 700,
                "url": f"https://www.youtube.com/watch?v={VIDEO_B}&list={olak_id}",
            },
        ]
    return {
        "id": olak_id,
        "title": title,
        "thumbnail": "https://i.ytimg.com/vi/cover/hqdefault.jpg",
        "entries": tracks,
    }


def _source_with_extract(pages: dict[str, dict]) -> YouTubeSource:
    def extract_info(url: str) -> dict:
        key = url.rstrip("/")
        if key not in pages:
            raise ValueError(f"unexpected extract url: {url}")
        return pages[key]

    return YouTubeSource(extract_info=extract_info)


@pytest.mark.parametrize(
    "artist_url",
    [
        "https://www.youtube.com/@TOOLmusic",
        "https://www.youtube.com/@TOOLmusic/releases",
        "https://www.youtube.com/@TOOLmusic/videos",
        "https://music.youtube.com/@TOOLmusic",
        "https://music.youtube.com/@TOOLmusic/releases",
        f"https://www.youtube.com/channel/{CHANNEL_ID}",
        f"https://www.youtube.com/channel/{CHANNEL_ID}/releases",
        "https://www.youtube.com/c/TOOLmusic",
        "https://www.youtube.com/user/TOOLmusic",
    ],
)
def test_youtube_channel_forms_list_via_releases(artist_url: str) -> None:
    releases_url = "https://www.youtube.com/@TOOLmusic/releases"
    if "/channel/" in artist_url:
        releases_url = f"https://www.youtube.com/channel/{CHANNEL_ID}/releases"
    elif "/c/" in artist_url:
        releases_url = "https://www.youtube.com/c/TOOLmusic/releases"
    elif "/user/" in artist_url:
        releases_url = "https://www.youtube.com/user/TOOLmusic/releases"

    pages = {
        releases_url: _releases_info(entries=[]),
    }
    source = _source_with_extract(pages)

    listing = source.list_uploads(artist_url)

    assert listing.platform == Platform.YOUTUBE
    assert listing.platform_id == CHANNEL_ID
    assert listing.name == "TOOL"
    assert listing.url == releases_url
    assert listing.uploads == []


@pytest.mark.parametrize(
    "bad_url",
    [
        f"https://www.youtube.com/watch?v={VIDEO_A}",
        f"https://youtu.be/{VIDEO_A}",
        f"https://www.youtube.com/playlist?list={OLAK_ID}",
        "https://music.youtube.com/browse/MPREb_gTAcphH99wE",
        "https://music.youtube.com/playlist?list=OLAK5uy_example",
    ],
)
def test_youtube_rejects_deep_links_with_artist_channel_error(bad_url: str) -> None:
    source = YouTubeSource(extract_info=lambda url: {})
    with pytest.raises(ValueError, match=r"artist channel"):
        source.list_uploads(bad_url)


def test_youtube_lists_olak_albums_with_ordered_tracks() -> None:
    releases_url = "https://www.youtube.com/@TOOLmusic/releases"
    album_url = f"https://www.youtube.com/playlist?list={OLAK_ID}"
    pages = {
        releases_url: _releases_info(entries=[_olak_entry(), _pl_entry()]),
        album_url: _album_info(),
    }
    source = _source_with_extract(pages)

    listing = source.list_uploads("https://music.youtube.com/@TOOLmusic")

    assert listing.platform_id == CHANNEL_ID
    assert [u.platform_id for u in listing.uploads] == [OLAK_ID]
    album = listing.uploads[0]
    assert album.platform == Platform.YOUTUBE
    assert album.title == "Fear Inoculum"
    assert album.url == album_url
    assert album.duration_seconds == 1300
    assert album.cover_url == "https://i.ytimg.com/vi/cover/hqdefault.jpg"
    assert len(album.tracks) == 2
    assert album.tracks[0].platform_id == VIDEO_A
    assert album.tracks[0].title == "Fear Inoculum"
    assert album.tracks[0].url == f"https://www.youtube.com/watch?v={VIDEO_A}"
    assert album.tracks[0].duration_seconds == 600
    assert album.tracks[1].platform_id == VIDEO_B
    assert album.tracks[1].url == f"https://www.youtube.com/watch?v={VIDEO_B}"


def test_youtube_orders_tracks_by_playlist_index() -> None:
    releases_url = "https://www.youtube.com/@TOOLmusic/releases"
    album_url = f"https://www.youtube.com/playlist?list={OLAK_ID}"
    pages = {
        releases_url: _releases_info(entries=[_olak_entry()]),
        album_url: _album_info(
            tracks=[
                {
                    "id": VIDEO_B,
                    "title": "Pneuma",
                    "duration": 700,
                    "playlist_index": 2,
                },
                {
                    "id": VIDEO_A,
                    "title": "Fear Inoculum",
                    "duration": 600,
                    "playlist_index": 1,
                },
            ]
        ),
    }
    source = _source_with_extract(pages)

    album = source.list_uploads("https://www.youtube.com/@TOOLmusic").uploads[0]

    assert [t.platform_id for t in album.tracks] == [VIDEO_A, VIDEO_B]


def test_youtube_skips_incomplete_track_keeps_album() -> None:
    releases_url = "https://www.youtube.com/@TOOLmusic/releases"
    album_url = f"https://www.youtube.com/playlist?list={OLAK_ID}"
    pages = {
        releases_url: _releases_info(entries=[_olak_entry()]),
        album_url: _album_info(
            tracks=[
                {"id": VIDEO_A, "title": "Fear Inoculum", "duration": 600},
                {"id": None, "title": "Broken", "duration": 100},
                {"id": VIDEO_B, "title": "Pneuma", "duration": 700},
            ]
        ),
    }
    source = _source_with_extract(pages)

    album = source.list_uploads("https://www.youtube.com/@TOOLmusic").uploads[0]

    assert [t.platform_id for t in album.tracks] == [VIDEO_A, VIDEO_B]


def test_youtube_skips_bad_album_without_aborting_artist() -> None:
    good_olak = "OLAK5uy_goodAlbumPlaylist0001"
    bad_olak = "OLAK5uy_badAlbumPlaylist00002"
    releases_url = "https://www.youtube.com/@TOOLmusic/releases"
    pages = {
        releases_url: _releases_info(
            entries=[
                _olak_entry(olak_id=bad_olak, title="Broken"),
                _olak_entry(olak_id=good_olak, title="Intact"),
            ]
        ),
        f"https://www.youtube.com/playlist?list={good_olak}": _album_info(
            olak_id=good_olak,
            title="Intact",
        ),
    }

    def extract_info(url: str) -> dict:
        key = url.rstrip("/")
        if bad_olak in key:
            raise RuntimeError("yt-dlp failed")
        if key not in pages:
            raise ValueError(f"unexpected extract url: {url}")
        return pages[key]

    source = YouTubeSource(extract_info=extract_info)

    listing = source.list_uploads("https://www.youtube.com/@TOOLmusic/releases")

    assert [u.platform_id for u in listing.uploads] == [good_olak]
    assert listing.uploads[0].title == "Intact"


def test_youtube_fetch_bytes_uses_injected_fetcher() -> None:
    calls: list[str] = []

    def fetcher(url: str) -> bytes:
        calls.append(url)
        return b"yt-audio"

    source = YouTubeSource(audio_fetcher=fetcher)
    url = f"https://www.youtube.com/watch?v={VIDEO_A}"

    assert source.fetch_bytes(url) == b"yt-audio"
    assert calls == [url]


def test_youtube_listing_enables_ejs_without_cookies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict] = []

    class _FakeYDL:
        def __init__(self, opts: dict) -> None:
            captured.append(opts)

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def extract_info(self, url: str, *, download: bool = True) -> dict:
            del download
            return {
                "id": CHANNEL_ID,
                "channel_id": CHANNEL_ID,
                "channel": "TOOL",
                "title": "TOOL - Releases",
                "entries": [],
                "webpage_url": url,
            }

    monkeypatch.setattr("yt_dlp.YoutubeDL", _FakeYDL)

    listing = YouTubeSource().list_uploads("https://www.youtube.com/@TOOLmusic")

    assert listing.platform_id == CHANNEL_ID
    assert len(captured) == 1
    opts = captured[0]
    assert opts.get("remote_components") == ["ejs:github"]
    assert opts.get("extractor_args") == {"youtubetab": {"skip": ["authcheck"]}}
    assert opts.get("skip_download") is True
    assert "cookiefile" not in opts
    assert "cookiesfrombrowser" not in opts


def test_youtube_listing_forwards_cookiefile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tunebag.ytdlp_fetch import YtdlpCookies

    captured: list[dict] = []

    class _FakeYDL:
        def __init__(self, opts: dict) -> None:
            captured.append(opts)

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def extract_info(self, url: str, *, download: bool = True) -> dict:
            del download
            return {
                "id": CHANNEL_ID,
                "channel_id": CHANNEL_ID,
                "channel": "TOOL",
                "title": "TOOL - Releases",
                "entries": [],
                "webpage_url": url,
            }

    monkeypatch.setattr("yt_dlp.YoutubeDL", _FakeYDL)

    source = YouTubeSource(cookies=YtdlpCookies.from_cookiefile("/tmp/yt.txt"))
    listing = source.list_uploads("https://www.youtube.com/@TOOLmusic")

    assert listing.platform_id == CHANNEL_ID
    assert captured[0]["cookiefile"] == "/tmp/yt.txt"
    assert "cookiesfrombrowser" not in captured[0]
    assert captured[0]["extractor_args"] == {
        "youtubetab": {"skip": ["authcheck"]}
    }


def test_youtube_listing_forwards_cookies_from_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tunebag.ytdlp_fetch import YtdlpCookies

    cookies = YtdlpCookies.from_browser("chrome:Default")
    captured: list[dict] = []

    class _FakeYDL:
        def __init__(self, opts: dict) -> None:
            captured.append(opts)

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def extract_info(self, url: str, *, download: bool = True) -> dict:
            del download
            return {
                "id": CHANNEL_ID,
                "channel_id": CHANNEL_ID,
                "channel": "TOOL",
                "title": "TOOL - Releases",
                "entries": [],
                "webpage_url": url,
            }

    monkeypatch.setattr("yt_dlp.YoutubeDL", _FakeYDL)

    source = YouTubeSource(cookies=cookies)
    listing = source.list_uploads("https://www.youtube.com/@TOOLmusic")

    assert listing.platform_id == CHANNEL_ID
    assert captured[0]["cookiesfrombrowser"] == ("chrome", "Default", None, None)
    assert "cookiefile" not in captured[0]
    assert captured[0]["extractor_args"] == {
        "youtubetab": {"skip": ["authcheck"]}
    }


def test_youtube_listing_auth_challenge_surfaces_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _AuthFailYDL:
        def __init__(self, opts: dict) -> None:
            del opts

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def extract_info(self, url: str, *, download: bool = True) -> dict:
            del url, download
            from yt_dlp.utils import DownloadError

            raise DownloadError(
                "ERROR: [youtube] Sign in to confirm you’re not a bot"
            )

    monkeypatch.setattr("yt_dlp.YoutubeDL", _AuthFailYDL)

    with pytest.raises(ValueError) as excinfo:
        YouTubeSource().list_uploads("https://www.youtube.com/@TOOLmusic")

    message = str(excinfo.value).lower()
    assert "anonymous" in message or "cookie" in message
    assert "--cookies" in message or "cookies-from-browser" in message
    assert "youtube" in message


def _music_browse_with_album(
    *,
    channel_id: str = CHANNEL_ID,
    name: str = "TOOL - Topic",
    olak_id: str = OLAK_ID,
    album_title: str = "Fear Inoculum",
) -> dict:
    return {
        "header": {
            "musicImmersiveHeaderRenderer": {
                "title": {"runs": [{"text": name}]},
            }
        },
        "contents": {
            "singleColumnBrowseResultsRenderer": {
                "tabs": [
                    {
                        "tabRenderer": {
                            "content": {
                                "sectionListRenderer": {
                                    "contents": [
                                        {
                                            "musicCarouselShelfRenderer": {
                                                "header": {
                                                    "musicCarouselShelfBasicHeaderRenderer": {
                                                        "title": {
                                                            "runs": [{"text": "Albums"}]
                                                        }
                                                    }
                                                },
                                                "contents": [
                                                    {
                                                        "musicTwoRowItemRenderer": {
                                                            "title": {
                                                                "runs": [
                                                                    {"text": album_title}
                                                                ]
                                                            },
                                                            "navigationEndpoint": {
                                                                "browseEndpoint": {
                                                                    "browseId": "MPREb_example",
                                                                    "browseEndpointContextSupportedConfigs": {
                                                                        "browseEndpointContextMusicConfig": {
                                                                            "pageType": "MUSIC_PAGE_TYPE_ALBUM"
                                                                        }
                                                                    },
                                                                }
                                                            },
                                                            "thumbnailOverlay": {
                                                                "musicItemThumbnailOverlayRenderer": {
                                                                    "content": {
                                                                        "musicPlayButtonRenderer": {
                                                                            "playNavigationEndpoint": {
                                                                                "watchPlaylistEndpoint": {
                                                                                    "playlistId": olak_id
                                                                                }
                                                                            }
                                                                        }
                                                                    }
                                                                }
                                                            },
                                                        }
                                                    }
                                                ],
                                            }
                                        }
                                    ]
                                }
                            }
                        }
                    }
                ]
            }
        },
        "microformat": {"channel_id": channel_id},
    }


def test_youtube_topic_channel_falls_back_to_music_browse() -> None:
    topic_id = "UCgYJA69st2KEPGUVkAXu7nA"
    releases_url = f"https://www.youtube.com/channel/{topic_id}/releases"
    album_url = f"https://www.youtube.com/playlist?list={OLAK_ID}"
    browse_calls: list[str] = []

    def extract_info(url: str) -> dict:
        key = url.rstrip("/")
        if key == releases_url:
            raise ValueError(
                f"ERROR: [youtube:tab] {topic_id}: This channel does not have a releases tab"
            )
        if key == album_url:
            return _album_info()
        raise ValueError(f"unexpected extract url: {url}")

    def browse_music_artist(channel_id: str) -> dict:
        browse_calls.append(channel_id)
        return _music_browse_with_album(
            channel_id=channel_id,
            name="Die Tentakel von Delphi - Topic",
        )

    source = YouTubeSource(
        extract_info=extract_info,
        browse_music_artist=browse_music_artist,
    )

    listing = source.list_uploads(f"https://music.youtube.com/channel/{topic_id}")

    assert browse_calls == [topic_id]
    assert listing.platform == Platform.YOUTUBE
    assert listing.platform_id == topic_id
    assert listing.name == "Die Tentakel von Delphi"
    assert listing.url == releases_url
    assert [u.platform_id for u in listing.uploads] == [OLAK_ID]
    assert listing.uploads[0].tracks[0].platform_id == VIDEO_A


def test_youtube_releases_path_does_not_call_music_browse() -> None:
    browse_calls: list[str] = []
    releases_url = "https://www.youtube.com/@TOOLmusic/releases"
    pages = {releases_url: _releases_info(entries=[])}

    def extract_info(url: str) -> dict:
        key = url.rstrip("/")
        if key not in pages:
            raise ValueError(f"unexpected extract url: {url}")
        return pages[key]

    source = YouTubeSource(
        extract_info=extract_info,
        browse_music_artist=lambda channel_id: browse_calls.append(channel_id) or {},
    )

    listing = source.list_uploads("https://www.youtube.com/@TOOLmusic")

    assert listing.platform_id == CHANNEL_ID
    assert listing.uploads == []
    assert browse_calls == []


def test_youtube_topic_name_strips_topic_suffix() -> None:
    topic_id = "UCtopicchannel00000000001"
    releases_url = f"https://www.youtube.com/channel/{topic_id}/releases"

    def extract_info(url: str) -> dict:
        if url.rstrip("/") == releases_url:
            raise ValueError(
                f"ERROR: [youtube:tab] {topic_id}: This channel does not have a releases tab"
            )
        raise ValueError(f"unexpected extract url: {url}")

    source = YouTubeSource(
        extract_info=extract_info,
        browse_music_artist=lambda _cid: _music_browse_with_album(
            channel_id=topic_id,
            name="Foo - Topic",
        ),
    )

    listing = source.list_uploads(f"https://www.youtube.com/channel/{topic_id}")

    assert listing.name == "Foo"
    assert listing.uploads == []
