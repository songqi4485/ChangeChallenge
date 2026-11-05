# Copyright (c) 2024 Alibaba Inc (authors: Xiang Lyu)
# Licensed under the Apache License, Version 2.0.
# Adapted from runtime/python/fastapi/server.py (commit 074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc)
from __future__ import annotations

import argparse
import logging
from pathlib import Path
import subprocess
import sys
import threading

from fastapi import FastAPI, Form, HTTPException, Response
import numpy as np
import uvicorn
import yaml

logging.getLogger("matplotlib").setLevel(logging.WARNING)


class _RedactSynthesisTextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "synthesis text" not in record.getMessage()


for _handler in logging.root.handlers:
    _handler.addFilter(_RedactSynthesisTextFilter())
logging.getLogger().addFilter(_RedactSynthesisTextFilter())

PROJECT_ROOT = Path(__file__).resolve().parents[2]
app = FastAPI()

_LOCK = threading.Lock()
_READY = False
_COSYVOICE = None
_CONFIG: dict[str, object] = {}


def _encode_pcm16_to_mp3(pcm_bytes: bytes, sample_rate: int, bitrate: str) -> bytes:
    if not pcm_bytes:
        raise RuntimeError("empty PCM output from CosyVoice")
    proc = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "s16le",
            "-ar",
            str(sample_rate),
            "-ac",
            "1",
            "-i",
            "pipe:0",
            "-codec:a",
            "libmp3lame",
            "-b:a",
            bitrate,
            "-f",
            "mp3",
            "pipe:1",
        ],
        input=pcm_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    if not proc.stdout:
        raise RuntimeError("ffmpeg produced empty MP3 output")
    return proc.stdout


def _synthesize_mp3_sync(tts_text: str) -> bytes:
    spk_id = str(_CONFIG["spk_id"])
    model_output = _COSYVOICE.inference_zero_shot(
        tts_text,
        "",
        "",
        zero_shot_spk_id=spk_id,
        stream=False,
    )
    pcm_parts: list[bytes] = []
    for item in model_output:
        tts_audio = (item["tts_speech"].numpy() * (2 ** 15)).astype(np.int16).tobytes()
        pcm_parts.append(tts_audio)
    return _encode_pcm16_to_mp3(
        b"".join(pcm_parts),
        int(_COSYVOICE.sample_rate),
        str(_CONFIG.get("mp3_bitrate", "96k")),
    )


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok" if _READY else "starting",
        "ready": _READY,
        "busy": _LOCK.locked(),
    }


@app.post("/inference_zero_shot")
def inference_zero_shot(tts_text: str = Form()) -> Response:
    text = tts_text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="tts_text must not be empty")
    if not _READY or _COSYVOICE is None:
        raise HTTPException(status_code=503, detail="CosyVoice model is not ready")
    if not _LOCK.acquire(blocking=False):
        raise HTTPException(status_code=503, detail="CosyVoice synthesizer is busy")
    try:
        mp3_bytes = _synthesize_mp3_sync(text)
        return Response(content=mp3_bytes, media_type="audio/mpeg")
    finally:
        _LOCK.release()


def init_service(config_path: str | Path) -> None:
    global _CONFIG, _COSYVOICE, _READY
    raw = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    _CONFIG = dict(raw["cosyvoice"])
    repo_dir = (PROJECT_ROOT / str(_CONFIG["repo_dir"])).resolve()
    matcha_dir = repo_dir / "third_party" / "Matcha-TTS"
    for p in (repo_dir, matcha_dir):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))

    import soundfile as sf
    import torch
    import torchaudio

    def _sf_load(filepath, *args, **kwargs):
        data, sr = sf.read(filepath, dtype="float32", always_2d=True)
        return torch.from_numpy(data.T), sr

    torchaudio.load = _sf_load

    from cosyvoice.cli.cosyvoice import AutoModel

    for _logger_name in logging.Logger.manager.loggerDict:
        logging.getLogger(_logger_name).addFilter(_RedactSynthesisTextFilter())

    model_dir = (PROJECT_ROOT / str(_CONFIG["model_dir"])).resolve()
    fp16 = bool(_CONFIG.get("fp16", True))
    _COSYVOICE = AutoModel(
        model_dir=str(model_dir),
        fp16=fp16,
    )
    if fp16 and torch.cuda.is_available():
        _COSYVOICE.model.llm.half()
        _COSYVOICE.model.flow.half()

    llm_encoder = _COSYVOICE.model.llm.llm

    def _fast_forward_one_step(xs, masks, cache=None):
        outs = llm_encoder.model(
            inputs_embeds=xs,
            attention_mask=None,
            output_hidden_states=True,
            return_dict=True,
            use_cache=True,
            past_key_values=cache,
        )
        return outs.hidden_states[-1], outs.past_key_values

    llm_encoder.forward_one_step = _fast_forward_one_step

    prompt_wav = str((PROJECT_ROOT / str(_CONFIG["prompt_wav"])).resolve())
    _COSYVOICE.add_zero_shot_spk(
        str(_CONFIG["prompt_text"]),
        prompt_wav,
        str(_CONFIG["spk_id"]),
    )
    _synthesize_mp3_sync("你好。")
    _READY = True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/cosyvoice.yaml")
    args = parser.parse_args()
    init_service(args.config)
    uvicorn.run(
        app,
        host=str(_CONFIG.get("host", "127.0.0.1")),
        port=int(_CONFIG.get("port", 50000)),
    )


if __name__ == "__main__":
    main()
