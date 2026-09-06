import struct

from qobuz_downloader.domain import Complete, Failed, Quality, Stream, Track
from qobuz_downloader.engine import Engine
from qobuz_downloader.engine._source import ByteResponse, ByteSource
from qobuz_downloader.naming import Naming
from qobuz_downloader.qobuz import Qobuz

TRACK = Track(id="t1", title="Song", artist="Artist", album="Album", track_number=1)


def _flac_bytes(size: int = 0) -> bytes:
    header = b"fLaC" + bytes([0x80, 0x00, 0x00, 0x22])
    streaminfo = struct.pack(">HH", 4096, 4096) + b"\x00" * 6
    packed = (44100 << 44) | (1 << 41) | (15 << 36) | 44100
    streaminfo += packed.to_bytes(8, "big") + b"\x00" * 16
    data = header + streaminfo
    return data + b"\x00" * max(0, size - len(data))


class FakeQobuz(Qobuz):
    def __init__(self, qualities):
        self._qualities = list(qualities)
        self.stream_calls = 0

    def item(self, url):
        raise NotImplementedError

    def tracks(self, item):
        raise NotImplementedError

    def search_tracks(self, query, limit):
        return []

    def search_albums(self, query, limit):
        return []

    def qualities(self, track):
        return list(self._qualities)

    def stream(self, track, quality):
        self.stream_calls += 1
        return Stream(url=f"https://cdn.test/{track.id}/{self.stream_calls}")


class FakeByteSource(ByteSource):
    def __init__(self, content, fail_after=None, ignore_range=False):
        self.content = content
        self.fail_after = fail_after
        self.ignore_range = ignore_range
        self.calls = []
        self._failed = False

    def stream(self, url, start):
        self.calls.append(start)
        if self.fail_after is not None and not self._failed:
            self._failed = True
            prefix = self.content[start : start + self.fail_after]
            return ByteResponse(
                status=200,
                length=len(self.content),
                chunks=self._raise_after(prefix),
            )
        if start and self.ignore_range:
            return ByteResponse(
                status=200, length=len(self.content), chunks=iter([self.content])
            )
        if start:
            return ByteResponse(
                status=206,
                length=len(self.content) - start,
                chunks=iter([self.content[start:]]),
            )
        return ByteResponse(
            status=200, length=len(self.content), chunks=iter([self.content])
        )

    def _raise_after(self, prefix):
        yield prefix
        raise ConnectionError("connection reset")


def make_engine(qobuz, source, tmp_path, retry_delays=()):
    naming = Naming("{artist}", "{tracknumber} - {title}", root=tmp_path)
    return Engine(qobuz, naming, source=source, retry_delays=retry_delays), tmp_path


def test_happy_path_downloads_and_renames(tmp_path):
    qobuz = FakeQobuz([Quality.LOSSY, Quality.CD, Quality.HIRES_96, Quality.HIRES_192])
    content = _flac_bytes(2048)
    source = FakeByteSource(content)
    engine, target = make_engine(qobuz, source, tmp_path)

    outcome = engine.download(TRACK, Quality.HIRES_192)

    assert isinstance(outcome, Complete)
    assert outcome.quality == Quality.HIRES_192
    assert not outcome.fell_back
    final = target / "Artist/01 - Song.flac"
    assert final.read_bytes() == content
    assert not final.with_suffix(".flac.part").exists()
    assert source.calls == [0]
    assert qobuz.stream_calls == 1


def test_falls_back_to_best_available_rung(tmp_path):
    qobuz = FakeQobuz([Quality.LOSSY, Quality.CD])
    source = FakeByteSource(_flac_bytes(512))
    engine, _ = make_engine(qobuz, source, tmp_path)

    outcome = engine.download(TRACK, Quality.HIRES_96)

    assert isinstance(outcome, Complete)
    assert outcome.quality == Quality.CD
    assert outcome.fell_back


def test_only_lossy_available_fails(tmp_path):
    qobuz = FakeQobuz([Quality.LOSSY])
    source = FakeByteSource(_flac_bytes(512))
    engine, _ = make_engine(qobuz, source, tmp_path)

    outcome = engine.download(TRACK, Quality.HIRES_192)

    assert isinstance(outcome, Failed)
    assert "lossy" in outcome.reason


def test_resumes_from_partial_after_mid_stream_failure(tmp_path):
    content = _flac_bytes(1024)
    qobuz = FakeQobuz([Quality.CD])
    source = FakeByteSource(content, fail_after=10)
    engine, target = make_engine(qobuz, source, tmp_path, retry_delays=(0.0,))

    outcome = engine.download(TRACK, Quality.CD)

    assert isinstance(outcome, Complete)
    assert source.calls == [0, 10]
    assert qobuz.stream_calls == 2
    final = target / "Artist/01 - Song.flac"
    assert final.read_bytes() == content
    assert not final.with_suffix(".flac.part").exists()


def test_restarts_when_server_ignores_range(tmp_path):
    content = _flac_bytes(1024)
    qobuz = FakeQobuz([Quality.CD])
    source = FakeByteSource(content, fail_after=5, ignore_range=True)
    engine, target = make_engine(qobuz, source, tmp_path, retry_delays=(0.0,))

    outcome = engine.download(TRACK, Quality.CD)

    assert isinstance(outcome, Complete)
    assert source.calls == [0, 5, 0]
    assert (target / "Artist/01 - Song.flac").read_bytes() == content


def test_corrupt_file_exhausts_retries_and_cleans_up(tmp_path):
    qobuz = FakeQobuz([Quality.CD])
    source = FakeByteSource(b"garbage" * 100)
    engine, target = make_engine(qobuz, source, tmp_path, retry_delays=(0.0, 0.0))

    outcome = engine.download(TRACK, Quality.CD)

    assert isinstance(outcome, Failed)
    assert "corrupt" in outcome.reason
    assert source.calls == [0, 0, 0]
    assert not (target / "Artist/01 - Song.flac").exists()
    assert not (target / "Artist/01 - Song.flac.part").exists()


def test_partial_remains_for_next_run_on_final_network_failure(tmp_path):
    content = _flac_bytes(1024)
    qobuz = FakeQobuz([Quality.CD])

    class AlwaysBreaks(FakeByteSource):
        def stream(self, url, start):
            self.calls.append(start)
            prefix = self.content[start : start + 7]
            return ByteResponse(
                status=200, length=len(self.content), chunks=self._raise_after(prefix)
            )

    source = AlwaysBreaks(content)
    engine, target = make_engine(qobuz, source, tmp_path, retry_delays=(0.0,))

    outcome = engine.download(TRACK, Quality.CD)

    assert isinstance(outcome, Failed)
    assert (target / "Artist/01 - Song.flac.part").exists()
