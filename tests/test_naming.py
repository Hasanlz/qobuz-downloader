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


def test_blank_template_uses_collection_as_directory():
    naming = Naming("", "{tracknumber} - {title}")
    path = naming.path_for(make_track(collection="Roadtrip Mix"))
    assert str(path) == "Roadtrip Mix/03 - Blinding Lights.flac"


def test_blank_template_without_collection_writes_to_root():
    naming = Naming("", "{tracknumber} - {title}")
    path = naming.path_for(make_track())
    assert str(path) == "03 - Blinding Lights.flac"


def test_whitespace_template_is_dynamic():
    naming = Naming("   ", "{title}")
    path = naming.path_for(make_track(collection="Mix"))
    assert str(path) == "Mix/Blinding Lights.flac"


def test_collection_placeholder_in_explicit_template():
    naming = Naming("{collection}/{album}", "{title}")
    path = naming.path_for(make_track(collection="Mix"))
    assert str(path) == "Mix/After Hours/Blinding Lights.flac"


def test_dynamic_collection_cleans_illegal_characters():
    naming = Naming("", "{title}")
    path = naming.path_for(make_track(collection='AC/DC: "Back" <in> Black?'))
    assert str(path) == "AC_DC_ _Back_ _in_ Black_/Blinding Lights.flac"
