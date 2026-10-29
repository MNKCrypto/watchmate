"""Shared helpers for calling Meta Model API (OpenAI-SDK compatible)."""

from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

BASE_URL = "https://api.meta.ai/v1"


def get_client() -> OpenAI:
    load_dotenv()
    key = os.environ.get("MODEL_API_KEY")
    if not key:
        sys.exit("MODEL_API_KEY is not set. Add it to .env (see .env.example).")
    return OpenAI(base_url=BASE_URL, api_key=key, max_retries=0)  # we retry ourselves


def video_part(client: OpenAI, path: Path, mode: str = "upload") -> tuple[dict, str | None]:
    """Return (content part, uploaded file id or None)."""
    if mode == "upload":
        with path.open("rb") as f:
            uploaded = client.files.create(file=f, purpose="user_data")
        return {"type": "input_file", "file_id": uploaded.id}, uploaded.id
    data = base64.b64encode(path.read_bytes()).decode()
    return {"type": "input_video", "video_url": f"data:video/mp4;base64,{data}"}, None


def delete_file(client: OpenAI, file_id: str | None) -> None:
    if not file_id:
        return
    try:
        client.files.delete(file_id)
    except Exception:
        pass  # cleanup is best-effort


def parse_json(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
