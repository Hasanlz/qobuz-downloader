from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass

import httpx


@dataclass(frozen=True, slots=True)
class ByteResponse:
    status: int
    length: int | None
    chunks: Iterator[bytes]


class ByteSource(ABC):
    @abstractmethod
    def stream(self, url: str, start: int) -> ByteResponse: ...


class HttpByteSource(ByteSource):
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(follow_redirects=True)

    def stream(self, url: str, start: int) -> ByteResponse:
        headers = {"Range": f"bytes={start}-"} if start else {}
        response = self._client.send(
            self._client.build_request("GET", url, headers=headers), stream=True
        )
        length = response.headers.get("content-length")
        return ByteResponse(
            status=response.status_code,
            length=int(length) if length is not None else None,
            chunks=self._chunks(response),
        )

    @staticmethod
    def _chunks(response: httpx.Response) -> Iterator[bytes]:
        try:
            yield from response.iter_bytes()
        finally:
            response.close()
