import pytest

from qobuz_downloader.domain import Track
from qobuz_downloader.naming import Naming


def make_track(**overrides):
    defaults = {
        "id": "t1",
        "title": "Blinding Lights",
        "artist": "The Weeknd",
        "album": "After Hours",
        "track_number": 3,
    }
    return Track(**{**defaults, **overrides})


def test_renders_directory_and_filename():
    naming = Naming("{artist}/{album}", "{tracknumber} - {title}")
    path = naming.path_for(make_track())
    assert str(path) == "The Weeknd/After Hours/03 - Blinding Lights.flac"


def test_strips_illegal_characters():
    track = make_track(album='AC/DC: "Back" <in> Black?', title="Hells Bells")
    naming = Naming("{artist}/{album}", "{tracknumber} - {title}")
    path = naming.path_for(track)
    assert str(path) == "The Weeknd/AC_DC_ _Back_ _in_ Black_/03 - Hells Bells.flac"


def test_missing_track_number_leaves_placeholder_empty():
    naming = Naming("{artist}/{album}", "{tracknumber} - {title}")
    path = naming.path_for(make_track(track_number=None))
    assert str(path) == "The Weeknd/After Hours/Blinding Lights.flac"


def test_unknown_placeholder_raises():
    naming = Naming("{artist}/{album}", "{bogus}")
    with pytest.raises(ValueError):
        naming.path_for(make_track())


def test_filename_template_rejects_path_separators():
    naming = Naming("{artist}", "{album}/{title}")
    with pytest.raises(ValueError):
        naming.path_for(make_track())


def test_collapses_whitespace_and_trailing_dots():
    track = make_track(title="Spaced   Out . ", album="Dot Album.")
    naming = Naming("{artist}", "{title}")
    path = naming.path_for(track)
    assert str(path) == "The Weeknd/Spaced Out.flac"
