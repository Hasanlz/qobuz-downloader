import pytest

from qobuz_downloader.qobuz._urls import parse


def test_play_album():
    assert parse("https://play.qobuz.com/album/qxjbxh1dc3xyb") == (
        "album",
        "qxjbxh1dc3xyb",
    )


def test_open_track():
    assert parse("https://open.qobuz.com/track/5966783") == ("track", "5966783")


def test_www_album_with_slug_and_id():
    assert parse(
        "https://www.qobuz.com/us-en/album/back-to-black-amy-winehouse/hd0b3sk0x1hub"
    ) == ("album", "hd0b3sk0x1hub")


def test_www_album_single_segment_slug():
    assert parse("https://www.qobuz.com/gb-en/album/back-to-black-hd0b3sk0x1hub") == (
        "album",
        "hd0b3sk0x1hub",
    )


def test_interpreter_artist():
    assert parse("https://www.qobuz.com/us-en/interpreter/amy-winehouse/5045") == (
        "artist",
        "5045",
    )


def test_playlist():
    assert parse("https://play.qobuz.com/playlist/5388296") == ("playlist", "5388296")


def test_artist_url():
    assert parse("https://play.qobuz.com/artist/2528676") == ("artist", "2528676")


def test_non_qobuz_url_raises():
    with pytest.raises(ValueError):
        parse("https://open.spotify.com/track/6rq486Rf3DBOm6Z66UHpo5")


def test_unsupported_kind_raises():
    with pytest.raises(ValueError):
        parse("https://play.qobuz.com/label/7526")
