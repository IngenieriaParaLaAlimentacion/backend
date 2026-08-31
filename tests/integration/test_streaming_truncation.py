"""Does a mid-stream failure reach a real HTTP client as an error?

The front-end guidance for exports (docs/frontend/csv-exports.md) tells clients
to read the body and treat a read failure as a broken download. That only works
if the server aborts the connection instead of ending the response cleanly.

uvicorn's source says it does -- on an exception once ``response_started`` it
calls ``transport.close()`` rather than finishing the body. This exercises that
over a real socket, because the in-process ASGI transport cannot reproduce it.

No database involved: a minimal app is enough to pin the transport behaviour.
"""

import socket
import threading

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

pytestmark = pytest.mark.asyncio

FIRST_CHUNK = b"Nombre;Documento\r\n"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/truncated")
    async def truncated():
        async def gen():
            yield FIRST_CHUNK
            raise RuntimeError("boom mid-stream")

        return StreamingResponse(gen(), media_type="text/csv; charset=utf-8")

    @app.get("/complete")
    async def complete():
        async def gen():
            yield FIRST_CHUNK
            yield b"Ana;30123456\r\n"

        return StreamingResponse(gen(), media_type="text/csv; charset=utf-8")

    return app


@pytest.fixture(scope="module")
def live_server():
    """Run a real uvicorn on a loopback port for the duration of the module."""
    port = _free_port()
    config = uvicorn.Config(
        _app(), host="127.0.0.1", port=port, log_level="critical", access_log=False
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        import time

        time.sleep(0.05)
    else:  # pragma: no cover - only on a hung startup
        pytest.fail("uvicorn did not start")
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


class TestRealSocketBehaviour:
    async def test_real_server_aborts_the_connection_on_mid_stream_failure(
        self, live_server
    ):
        """The load-bearing claim: truncation is an error, not a short 200."""
        async with httpx.AsyncClient(base_url=live_server) as client:
            with pytest.raises(httpx.HTTPError):
                # Headers arrive with 200; the failure surfaces on read.
                await client.get("/truncated")

    async def test_a_complete_stream_reads_cleanly(self, live_server):
        """Control: the same setup succeeds when nothing goes wrong, so the
        test above is detecting the failure and not the transport."""
        async with httpx.AsyncClient(base_url=live_server) as client:
            response = await client.get("/complete")

        assert response.status_code == 200
        assert response.content == FIRST_CHUNK + b"Ana;30123456\r\n"

    async def test_the_response_is_chunked(self, live_server):
        """Truncation is only detectable because there is no Content-Length."""
        async with httpx.AsyncClient(base_url=live_server) as client:
            response = await client.get("/complete")

        assert response.headers.get("transfer-encoding") == "chunked"
        assert "content-length" not in response.headers
