"""Localhost-only HTTP adapter for :mod:`human_review_session`."""

from __future__ import annotations

from dataclasses import dataclass
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote, unquote, urlsplit

from .human_review_session import ReviewSession, ReviewSessionError
from .human_review_ui import render_review_page


MAX_JSON_BODY_BYTES = 64 * 1024


@dataclass(frozen=True)
class ReviewServerContext:
    session: ReviewSession
    repo_root: Path
    export_path: Path


def _asset_url(relative_path: str) -> str:
    return "/assets/" + quote(relative_path, safe="/")


def public_session_snapshot(context: ReviewServerContext) -> dict[str, Any]:
    """Expose only review-item state and paired asset URLs to the browser."""

    snapshot = context.session.snapshot()
    public_items = []
    for item in snapshot["items"]:
        public_items.append(
            {
                "review_index": item["review_index"],
                "item_id": item["item_id"],
                "local_image_url": _asset_url(item["local_image_path"]),
                "context_image_url": _asset_url(item["context_image_path"]),
                "optional_neutral_overlay_url": (
                    _asset_url(item["optional_neutral_overlay_path"])
                    if item["optional_neutral_overlay_path"]
                    else None
                ),
                "human_label": item["human_label"],
                "reviewer_note": item["reviewer_note"],
                "review_status": item["review_status"],
                "updated_at": item["updated_at"],
            }
        )
    return {
        "schema_version": snapshot["schema_version"],
        "session_id": snapshot["session_id"],
        "ordering_method": snapshot["ordering_method"],
        "review_order": snapshot["review_order"],
        "manifest_sha256": snapshot["manifest_sha256"],
        "created_at": snapshot["created_at"],
        "updated_at": snapshot["updated_at"],
        "items": public_items,
        "counts": snapshot["counts"],
    }


class _ReviewRequestHandler(BaseHTTPRequestHandler):
    context: ReviewServerContext

    server_version = "DraftsmanHumanReview/1"

    def log_message(self, format: str, *args: object) -> None:
        # Keep the local terminal useful without exposing request bodies.
        super().log_message("[review-ui] " + format, *args)

    def _send_bytes(self, body: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: Mapping[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self._send_bytes(body, "application/json; charset=utf-8", status)

    def _send_error_json(self, message: str, status: HTTPStatus) -> None:
        self._send_json({"error": message}, status)

    def _read_json(self) -> dict[str, Any]:
        content_length = self.headers.get("Content-Length")
        try:
            length = int(content_length or "0")
        except ValueError as exc:
            raise ReviewSessionError("invalid request body length") from exc
        if length < 0 or length > MAX_JSON_BODY_BYTES:
            raise ReviewSessionError("request body is too large")
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReviewSessionError("request body must be JSON") from exc
        if not isinstance(payload, dict):
            raise ReviewSessionError("request body must be a JSON object")
        return payload

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        route = urlsplit(self.path).path
        if route in ("/", "/index.html"):
            self._send_bytes(render_review_page().encode("utf-8"), "text/html; charset=utf-8")
            return
        if route == "/api/session":
            self._send_json({"session": public_session_snapshot(self.context)})
            return
        if route.startswith("/assets/"):
            self._serve_asset(unquote(route[len("/assets/") :]))
            return
        self._send_error_json("not found", HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        route = urlsplit(self.path).path.rstrip("/")
        try:
            payload = self._read_json()
            if route == "/api/export":
                exported = self.context.session.export(self.context.export_path)
                self._send_json(
                    {
                        "export": exported,
                        "export_path": self.context.export_path.name,
                    }
                )
                return

            parts = [unquote(part) for part in route.split("/") if part]
            if len(parts) != 4 or parts[:2] != ["api", "items"]:
                self._send_error_json("not found", HTTPStatus.NOT_FOUND)
                return
            item_id = parts[2]
            operation = parts[3]
            if operation == "label":
                label = payload.get("label")
                item = self.context.session.set_label(item_id, label)
            elif operation == "note":
                item = self.context.session.set_note(item_id, payload.get("note"))
            else:
                self._send_error_json("not found", HTTPStatus.NOT_FOUND)
                return
            snapshot = public_session_snapshot(self.context)
            public_item = next(
                item_snapshot
                for item_snapshot in snapshot["items"]
                if item_snapshot["item_id"] == item_id
            )
            self._send_json({"item": public_item, "session": snapshot})
        except ReviewSessionError as exc:
            self._send_error_json(str(exc), HTTPStatus.BAD_REQUEST)
        except KeyError:
            self._send_error_json("unknown review item", HTTPStatus.NOT_FOUND)
        except FileNotFoundError as exc:
            self._send_error_json(f"review asset not found: {exc}", HTTPStatus.NOT_FOUND)

    def _serve_asset(self, relative_path: str) -> None:
        if not relative_path or relative_path.startswith("/"):
            self._send_error_json("asset not found", HTTPStatus.NOT_FOUND)
            return
        snapshot = self.context.session.snapshot()
        allowed = {
            path
            for item in snapshot["items"]
            for path in (
                item["local_image_path"],
                item["context_image_path"],
                item["optional_neutral_overlay_path"],
            )
            if path
        }
        if relative_path not in allowed:
            self._send_error_json("asset not found", HTTPStatus.NOT_FOUND)
            return
        root = self.context.repo_root.resolve()
        asset_path = (root / Path(*relative_path.split("/"))).resolve()
        try:
            asset_path.relative_to(root)
        except ValueError:
            self._send_error_json("asset not found", HTTPStatus.NOT_FOUND)
            return
        if not asset_path.is_file():
            self._send_error_json("asset not found", HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(asset_path.name)[0] or "application/octet-stream"
        self._send_bytes(asset_path.read_bytes(), content_type)


def create_review_server(
    *,
    session: ReviewSession,
    repo_root: Path,
    export_path: Path,
    host: str = "127.0.0.1",
    port: int = 0,
) -> ThreadingHTTPServer:
    """Create a local review server; callers own its context manager/lifecycle."""

    context = ReviewServerContext(
        session=session,
        repo_root=Path(repo_root).resolve(),
        export_path=Path(export_path),
    )

    class ReviewRequestHandler(_ReviewRequestHandler):
        pass

    ReviewRequestHandler.context = context
    server = ThreadingHTTPServer((host, port), ReviewRequestHandler)
    server.daemon_threads = True
    return server


__all__ = ["ReviewServerContext", "create_review_server", "public_session_snapshot"]
