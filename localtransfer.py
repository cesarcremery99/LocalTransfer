#!/usr/bin/env python3
"""LocalTransfer - send pictures from your phone (Android / iOS) to this PC
over your local network.

Run this script on the PC, then open the printed URL (or scan the QR code)
on your phone. Pick pictures and tap "Send". Pictures are saved into a folder
per day. Photos that already reached the PC are skipped when re-sent, so a large
transfer can be resumed or split into several smaller selections.

Only the Python standard library is required. If the optional `qrcode`
package is installed (pip install qrcode) a QR code is printed in the terminal.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import secrets
import socket
import sys
import threading
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


class Manifest:
    """Remembers which photos already reached this PC (keyed by the phone's
    file name + size), so re-sending a selection skips them. Stored as an
    append-only text file in the output folder, so it survives restarts."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.keys: dict[str, str] = {}
        if path.exists():
            with open(path, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    key, _, saved_as = line.rstrip("\n").partition("\t")
                    if key:
                        self.keys[key] = saved_as

    def __contains__(self, key: str) -> bool:
        return key in self.keys

    def get(self, key: str) -> str | None:
        return self.keys.get(key)

    def add(self, saved_as: str, *keys: str) -> None:
        with self.lock:
            new = [k for k in keys if k and k not in self.keys]
            if not new:
                return
            with open(self.path, "a", encoding="utf-8") as fh:
                for key in new:
                    self.keys[key] = saved_as
                    fh.write(f"{key}\t{saved_as}\n")


KNOWN_EXTS = {".jpg", ".jpeg", ".heic", ".heif", ".png", ".gif", ".webp", ".dng", ".tif", ".tiff",
              ".mov", ".mp4", ".m4v", ".avif"}


def sniff_extension(path: Path) -> str:
    """Guess a file extension from the first bytes (for uploads sent without one)."""
    with open(path, "rb") as fh:
        head = fh.read(16)
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if head.startswith(b"\x89PNG"):
        return ".png"
    if head.startswith(b"GIF8"):
        return ".gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"heic", b"heix", b"hevc", b"heim", b"heis", b"mif1", b"msf1"):
            return ".heic"
        if brand == b"avif":
            return ".avif"
        if brand == b"qt  ":
            return ".mov"
        return ".mp4"
    return ""


class HashingWriter:
    """File wrapper that computes a SHA-256 of everything written."""

    def __init__(self, fh) -> None:
        self.fh, self.sha = fh, hashlib.sha256()

    def write(self, data: bytes) -> None:
        self.sha.update(data)
        self.fh.write(data)


_EXIF_DATE = re.compile(rb"((?:19|20)\d\d):([01]\d):([0-3]\d) ([0-2]\d):([0-5]\d):([0-5]\d)")


def photo_date(path: Path) -> _dt.datetime | None:
    """Find the date a photo was taken from its EXIF data (JPEG and HEIC).
    A simple scan of the file's start is enough: the EXIF block sits there."""
    with open(path, "rb") as fh:
        head = fh.read(512 * 1024)
    m = _EXIF_DATE.search(head)
    if not m:
        return None
    try:
        return _dt.datetime(*(int(g) for g in m.groups()))
    except ValueError:
        return None


def parse_taken(raw: str) -> float | None:
    """Parse the Shortcut's date header (yyyyMMdd-HHmmss, local time)."""
    try:
        return _dt.datetime.strptime(raw.strip(), "%Y%m%d-%H%M%S").timestamp()
    except ValueError:
        return None


def clean_key(raw: str) -> str:
    return re.sub(r"[\t\r\n]", " ", raw)[:300]


class _AlreadyAnswered(Exception):
    """An error response was already sent for this request."""


class TransferHandler(BaseHTTPRequestHandler):
    server_version = "LocalTransfer/2.0"
    protocol_version = "HTTP/1.1"  # keep-alive: reuse connections across thousands of uploads
    # Set on the class by main()
    token: str = ""
    output_dir: Path = default_output_dir()
    manifest: Manifest
    name_lock = threading.Lock()
    saved_count = 0

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

    def _reject(self, status: int, msg: str) -> None:
        # The request body was not read, so this connection can't be reused.
        self.close_connection = True
        self._json(status, {"error": msg})

    def _authorized(self, query: dict) -> bool:
        given = (query.get("t") or [""])[0] or self.headers.get("X-Token", "")
        return secrets.compare_digest(given, self.token)

    def _length(self, limit: int) -> int | None:
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._reject(HTTPStatus.LENGTH_REQUIRED, "Content-Length required")
            return None
        if length < 0 or length > limit:
            self._reject(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "bad size")
            return None
        return length

    def _shortcut_key(self, query: dict) -> str | None:
        """Key for uploads from the iPhone Shortcut: photo name + date taken,
        sent as X-Name / X-Taken headers (or name / taken query parameters)."""
        taken = self.headers.get("X-Taken") or (query.get("taken") or [""])[0]
        name = self.headers.get("X-Name") or ((query.get("name") or [""])[0] if taken else "")
        if not name:  # not a Shortcut-style request (the browser page uses name|size keys)
            return None
        return clean_key(f"shortcut|{name.strip()}|{taken.strip()}")

    @staticmethod
    def _client_key(query: dict, raw_name: str, length: int) -> str:
        """Key the browser page uses to skip photos (name|size)."""
        given = (query.get("key") or [""])[0]
        if given:
            return clean_key(given)
        return clean_key(f"{raw_name}|{length}") if raw_name else ""

    def _read_body(self, fh) -> int:
        """Copy the request body into fh; supports Content-Length and chunked uploads."""
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            total = 0
            while True:
                size_line = self.rfile.readline(1024)
                if not size_line:
                    raise ConnectionError("phone disconnected mid-upload")
                size = int(size_line.split(b";")[0].strip() or b"0", 16)
                if size == 0:
                    while self.rfile.readline(1024) not in (b"\r\n", b"\n", b""):
                        pass  # skip trailers
                    return total
                total += size
                if total > MAX_UPLOAD_BYTES:
                    raise ValueError("upload too large")
                remaining = size
                while remaining > 0:
                    chunk = self.rfile.read(min(CHUNK, remaining))
                    if not chunk:
                        raise ConnectionError("phone disconnected mid-upload")
                    fh.write(chunk)
                    remaining -= len(chunk)
                self.rfile.readline(1024)  # CRLF after each chunk
        length = self._length(MAX_UPLOAD_BYTES)
        if length is None:
            raise _AlreadyAnswered()
        remaining = length
        while remaining > 0:
            chunk = self.rfile.read(min(CHUNK, remaining))
            if not chunk:
                raise ConnectionError("phone disconnected mid-upload")
            fh.write(chunk)
            remaining -= len(chunk)
        return length

    def log_request(self, code="-", size="-") -> None:
        pass  # don't print a line for each of thousands of requests

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write(f"  [{self.address_string()}] {fmt % args}\n")

    # ---- routes --------------------------------------------------------
    def do_GET(self) -> None:
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            self._send(HTTPStatus.OK, INDEX_HTML.read_bytes(), "text/html; charset=utf-8")
        elif url.path == "/ping":
            ok = self._authorized(parse_qs(url.query))
            self._json(HTTPStatus.OK if ok else HTTPStatus.FORBIDDEN, {"ok": ok})
        elif url.path == "/has":
            # Used by the iPhone Shortcut: plain-text "yes" / "no" is easy to test there.
            query = parse_qs(url.query)
            if not self._authorized(query):
                self._send(HTTPStatus.FORBIDDEN, b"wrong access code", "text/plain")
                return
            key = self._shortcut_key(query)
            answer = b"yes" if key and key in self.manifest else b"no"
            self._send(HTTPStatus.OK, answer, "text/plain; charset=utf-8")
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path not in ("/upload", "/check"):
            self._reject(HTTPStatus.NOT_FOUND, "not found")
        elif not self._authorized(query):
            self._reject(HTTPStatus.FORBIDDEN, "invalid or missing access code")
        elif url.path == "/check":
            self._check()
        else:
            self._upload(query)

    def _check(self) -> None:
        """Body: {"keys": [...]} -> {"have": [keys already on the PC]}"""
        length = self._length(32 * 1024 * 1024)
        if length is None:
            return
        try:
            keys = json.loads(self.rfile.read(length) or b"{}").get("keys", [])
        except (ValueError, AttributeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "bad JSON"})
            return
        have = [k for k in keys if isinstance(k, str) and clean_key(k) in self.manifest]
        self._json(HTTPStatus.OK, {"have": have})

    def _upload(self, query: dict) -> None:
        raw_name = self.headers.get("X-Name") or (query.get("name") or [""])[0]
        name = safe_filename(raw_name, "upload")
        target_dir = self.output_dir / _dt.date.today().isoformat()
        target_dir.mkdir(parents=True, exist_ok=True)
        partial = target_dir / f".{secrets.token_hex(8)}.part"

        try:
            with open(partial, "wb") as fh:
                writer = HashingWriter(fh)
                length = self._read_body(writer)
            if length == 0:
                raise ValueError("empty upload")
            # Same photo already on the PC (whichever way it was sent)? Don't keep a copy.
            content_key = "sha256:" + writer.sha.hexdigest()
            existing = self.manifest.get(content_key)
            if existing:
                partial.unlink(missing_ok=True)
                key = self._shortcut_key(query) or self._client_key(query, raw_name, length)
                self.manifest.add(existing, key)
                self._json(HTTPStatus.OK, {"ok": True, "duplicate": True, "saved": existing, "bytes": length})
                return
            taken = photo_date(partial)
            if not raw_name:  # e.g. the iPhone Shortcut: name it after the date taken
                stamp = (taken or _dt.datetime.now()).strftime("%Y%m%d_%H%M%S")
                name = f"IMG_{stamp}"
            # Keep the photo's original date if the phone sent one.
            mtime = None
            try:
                mtime = float((query.get("lm") or [""])[0]) / 1000
            except ValueError:
                pass
            if not mtime or mtime <= 0:
                mtime = parse_taken(self.headers.get("X-Taken") or (query.get("taken") or [""])[0])
            if (not mtime or mtime <= 0) and taken:
                mtime = taken.timestamp()
            if mtime and mtime > 0:
                os.utime(partial, (mtime, mtime))
            # Shortcuts may send names without an extension ("IMG_1234").
            stem, ext = os.path.splitext(name)
            if ext.lower() not in KNOWN_EXTS:
                name += sniff_extension(partial)
            elif ext.lower() in (".heic", ".heif") and sniff_extension(partial) == ".jpg":
                name = stem + ".jpg"  # converted to JPEG on the phone
            with self.name_lock:  # pick a free name and claim it atomically
                final = unique_path(target_dir, name)
                partial.rename(final)
                TransferHandler.saved_count += 1
                count = TransferHandler.saved_count
        except _AlreadyAnswered:
            partial.unlink(missing_ok=True)
            return
        except Exception as exc:  # noqa: BLE001
            partial.unlink(missing_ok=True)
            self.close_connection = True
            self.log_message("upload of %s failed: %s", name, exc)
            try:
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
            except OSError:
                pass
            return

        key = self._shortcut_key(query) or self._client_key(query, raw_name, length)
        self.manifest.add(f"{target_dir.name}/{final.name}", key, content_key)
        print(f"  #{count:<6} {final.name}  ({length / 1024 / 1024:.1f} MB)")
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
    TransferHandler.manifest = Manifest(TransferHandler.output_dir / ".localtransfer-received.txt")
    for stale in TransferHandler.output_dir.glob("*/.*.part"):  # leftovers from an interrupted run
        stale.unlink(missing_ok=True)

    httpd = ThreadingHTTPServer(("0.0.0.0", args.port), TransferHandler)
    urls = [f"http://{ip}:{args.port}/?t={TransferHandler.token}" for ip in lan_addresses()]

    print("\nLocalTransfer is running.")
    print(f"  Saving to: {TransferHandler.output_dir}")
    received = len(set(TransferHandler.manifest.keys.values()))
    if received:
        print(f"  Already received earlier: {received} pictures (these are skipped)")
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
