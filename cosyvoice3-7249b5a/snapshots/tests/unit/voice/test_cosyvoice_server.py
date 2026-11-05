from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import threading

import httpx
import numpy as np
import pytest

_SERVER_PATH = Path(__file__).resolve().parents[3] / "services" / "cosyvoice" / "server.py"
_spec = importlib.util.spec_from_file_location("cosyvoice_server", _SERVER_PATH)
server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(server)


class _BlockingModel:
    """Fake model whose synchronous inference blocks until released."""

    sample_rate = 24000

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.raise_error = False

    def inference_zero_shot(self, *args, **kwargs):
        self.entered.set()
        self.release.wait(timeout=10.0)
        if self.raise_error:
            raise RuntimeError("simulated inference failure")
        pcm = np.zeros(2400, dtype=np.float32)
        yield {"tts_speech": type("T", (), {"numpy": lambda self: pcm})()}


@pytest.fixture
def fake_model(monkeypatch: pytest.MonkeyPatch):
    model = _BlockingModel()
    monkeypatch.setattr(server, "_COSYVOICE", model)
    monkeypatch.setattr(server, "_READY", True)
    monkeypatch.setattr(server, "_CONFIG", {"spk_id": "test", "mp3_bitrate": "96k"})
    monkeypatch.setattr(server, "_encode_pcm16_to_mp3", lambda pcm, sr, br: b"MP3")
    yield model
    model.release.set()
    if server._LOCK.locked():
        server._LOCK.release()


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=server.app), base_url="http://testserver"
    )


async def _post(client: httpx.AsyncClient) -> httpx.Response:
    return await client.post("/inference_zero_shot", data={"tts_text": "你好"})


def test_health_and_busy_503_while_synthesis_blocked(fake_model) -> None:
    async def exercise():
        async with _client() as client:
            first = asyncio.create_task(_post(client))
            await asyncio.to_thread(fake_model.entered.wait, 5.0)
            health = await asyncio.wait_for(client.get("/health"), timeout=2.0)
            assert health.status_code == 200
            assert health.json()["busy"] is True
            second = await asyncio.wait_for(_post(client), timeout=2.0)
            assert second.status_code == 503
            fake_model.release.set()
            resp = await asyncio.wait_for(first, timeout=5.0)
            assert resp.status_code == 200
            health_after = await client.get("/health")
            assert health_after.json()["busy"] is False

    asyncio.run(exercise())


def test_client_cancel_keeps_lock_until_inference_finishes(fake_model) -> None:
    async def exercise():
        async with _client() as client:
            first = asyncio.create_task(_post(client))
            await asyncio.to_thread(fake_model.entered.wait, 5.0)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            # Inference is still running on the worker thread.
            assert await asyncio.to_thread(server._LOCK.locked) is True
            busy = await asyncio.wait_for(_post(client), timeout=2.0)
            assert busy.status_code == 503
            fake_model.release.set()
            # Wait until the lock is released by the worker.
            for _ in range(100):
                if not server._LOCK.locked():
                    break
                await asyncio.sleep(0.05)
            assert server._LOCK.locked() is False
            fake_model.entered.clear()
            fake_model.release.set()
            resp = await asyncio.wait_for(_post(client), timeout=5.0)
            assert resp.status_code == 200

    asyncio.run(exercise())


def test_inference_exception_releases_lock(fake_model) -> None:
    async def exercise():
        fake_model.raise_error = True
        fake_model.release.set()
        async with _client() as client:
            with pytest.raises(RuntimeError, match="simulated inference failure"):
                await _post(client)
            assert server._LOCK.locked() is False

    asyncio.run(exercise())
