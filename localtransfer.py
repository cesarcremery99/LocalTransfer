#!/usr/bin/env python3
"""LocalTransfer - send pictures from your phone (Android / iOS) to this PC
over your local network.

Run this script on the PC, then open the printed URL (or scan the QR code)
on your phone. Pick pictures and tap "Send". Batches of more than 10 pictures
are packed into a single .zip on the phone before uploading.

Only the Python standard library is required. If the optional `qrcode`
package is installed (pip install qrcode) a QR code is printed in the terminal.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import secrets
import socket
import sys
import unicodedata
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
INDEX_HTML = HERE / "static" / "index.html"
CHUNK = 1024 * 1024
MAX_UPLOAD_BYTES = 8 * 1024 ** 3  # 8 GiB per request, sanity limit


def default_output_dir() -> Path:
    pictures = Path.home() / "Pictures"
    base = pictures if pictures.is_dir() else Path.home()
    return base / "LocalTransfer"


def lan_addresses() -> list[str]:
    """Best-effort list of this machine's LAN IPv4 addresses."""
    found: list[str] = []
    # The "connect a UDP socket" trick reveals the primary interface address
    # without actually sending any packets.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            found.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in found:
                found.append(ip)
    except OSError:
        pass
    found = [ip for ip in found if not ip.startswith("127.")]
    return found or ["127.0.0.1"]


_SAFE_CHARS = re.compile(r"[^A-Za-z0-9._ ()\-]+")


def safe_filename(name: str, fallback: str = "file") -> str:
    """Strip any path components and unsafe characters from a client filename."""
    name = name.replace("\\", "/").split("/")[-1]
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = _SAFE_CHARS.sub("_", name).strip(" .")
    if not name:
        name = fallback
    return name[:150]


def unique_path(directory: Path, name: str) -> Path:
    candidate = directory / name
    stem, suffix = os.path.splitext(name)
    n = 1
    while candidate.exists():
        candidate = directory / f"{stem} ({n}){suffix}"
        n += 1
    return candidate


class TransferHandler(BaseHTTPRequestHandler):
    server_version = "LocalTransfer/1.0"
    # Set on the class by main()
    token: str = ""
    output_dir: Path = default_output_dir()

    # ---- helpers -------------------------------------------------------
    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        self._send(status, json.dumps(payload).encode(), "application/json")

    def _authorized(self, query: dict) -> bool:
        given = (query.get("t") or [""])[0] or self.headers.get("X-Token", "")
        return secrets.compare_digest(given, self.token)

    def log_message(self, fmt: str, *args) -> None:  # quieter logging
        sys.stderr.write(f"  [{self.address_string()}] {fmt % args}\n")

    # ---- routes --------------------------------------------------------
    def do_GET(self) -> None:
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            self._send(HTTPStatus.OK, INDEX_HTML.read_bytes(), "text/html; charset=utf-8")
        elif url.path == "/ping":
            ok = self._authorized(parse_qs(url.query))
            self._json(HTTPStatus.OK if ok else HTTPStatus.FORBIDDEN, {"ok": ok})
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        url = urlparse(self.path)
        if url.path != "/upload":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        query = parse_qs(url.query)
        if not self._authorized(query):
            self._json(HTTPStatus.FORBIDDEN, {"error": "invalid or missing access code"})
            return

        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._json(HTTPStatus.LENGTH_REQUIRED, {"error": "Content-Length required"})
            return
        if length <= 0 or length > MAX_UPLOAD_BYTES:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "bad size"})
            return

        name = safe_filename((query.get("name") or ["upload"])[0], "upload")
        target_dir = self.output_dir / _dt.date.today().isoformat()
        target_dir.mkdir(parents=True, exist_ok=True)
        final = unique_path(target_dir, name)
        partial = final.with_name(final.name + ".part")

        remaining = length
        try:
            with open(partial, "wb") as fh:
                while remaining > 0:
                    chunk = self.rfile.read(min(CHUNK, remaining))
                    if not chunk:
                        raise ConnectionError("client disconnected")
                    fh.write(chunk)
                    remaining -= len(chunk)
            # Re-check uniqueness in case of a concurrent upload with the same name.
            final = unique_path(target_dir, final.name)
            partial.rename(final)
        except Exception as exc:  # noqa: BLE001
            partial.unlink(missing_ok=True)
            self.log_message("upload failed: %s", exc)
            try:
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
            except OSError:
                pass
            return

        print(f"  Saved {final}  ({length / 1024 / 1024:.1f} MB)")
        self._json(HTTPStatus.OK, {"ok": True, "saved": final.name, "bytes": length})


def print_qr(url: str) -> None:
    try:
        import qrcode  # type: ignore
    except ImportError:
        print("  (Tip: `pip install qrcode` to show a scannable QR code here.)")
        return
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.make(fit=True)
    qr.print_ascii(invert=True)


_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")


def choose_code(given: str | None) -> str:
    """Return the access code: from --code, typed at a prompt, or random."""
    if given is not None:
        if not _CODE_RE.fullmatch(given):
            sys.exit("Access code must be 4-64 characters: letters, digits, '-' or '_'.")
        return given
    if not sys.stdin.isatty():
        return secrets.token_urlsafe(6)
    while True:
        try:
            typed = input("Access code for the link (press Enter for a random one): ").strip()
        except EOFError:
            typed = ""
        if not typed:
            return secrets.token_urlsafe(6)
        if _CODE_RE.fullmatch(typed):
            return typed
        print("  Use 4-64 characters: letters, digits, '-' or '_'. Try again.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Receive pictures from your phone over the local network.")
    parser.add_argument("-p", "--port", type=int, default=8765, help="port to listen on (default 8765)")
    parser.add_argument("-o", "--output", type=Path, default=default_output_dir(),
                        help="folder to save pictures in (default ~/Pictures/LocalTransfer)")
    parser.add_argument("--code", help="access code used in the link; skips the prompt "
                        "(default: asked at startup, random if left empty)")
    args = parser.parse_args()

    TransferHandler.token = choose_code(args.code)
    TransferHandler.output_dir = args.output.expanduser().resolve()
    TransferHandler.output_dir.mkdir(parents=True, exist_ok=True)

    httpd = ThreadingHTTPServer(("0.0.0.0", args.port), TransferHandler)
    urls = [f"http://{ip}:{args.port}/?t={TransferHandler.token}" for ip in lan_addresses()]

    print("\nLocalTransfer is running.")
    print(f"  Saving to: {TransferHandler.output_dir}")
    print("  Open this on your phone (same Wi-Fi network):")
    for u in urls:
        print(f"    {u}")
    print()
    print_qr(urls[0])
    print("\n  Press Ctrl+C to stop.\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
