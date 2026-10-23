"""Minimal Supabase client (Auth + PostgREST + Storage) over httpx. Only what the sync needs."""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path
from typing import Callable
from urllib.parse import quote, urlsplit

import httpx

CHUNK = 1024 * 1024


class SyncError(Exception):
    pass


def _message(r: httpx.Response) -> str:
    try:
        j = r.json()
        msg = j.get("message") or j.get("msg") or j.get("error_description") or j.get("error") or r.text
    except (ValueError, AttributeError):
        msg = r.text
    return f"HTTP {r.status_code}: {str(msg)[:300]}"


def normalize_url(raw: str) -> str:
    """Reduce whatever was pasted to the bare project address (https://<ref>.supabase.co).

    People often paste the dashboard link or an API path such as .../rest/v1/; either gives "404 Invalid path".
    """
    text = raw.strip()
    if re.fullmatch(r"[a-z0-9]{15,25}", text):  # just the project reference
        text = f"https://{text}.supabase.co"
    if "://" not in text:
        text = "https://" + text
    parts = urlsplit(text)
    host = parts.hostname or ""
    if host in ("supabase.com", "www.supabase.com", "app.supabase.com") or host.endswith(".supabase.com"):
        m = re.search(r"/project/([a-z0-9]+)", parts.path)
        hint = f" (your project address looks like https://{m.group(1)}.supabase.co)" if m else ""
        raise SyncError(
            "That is the Supabase dashboard address, not the project URL" + hint + ". "
            "Copy the Project URL from Project Settings → API."
        )
    if not host or "." not in host:
        raise SyncError(f"'{raw}' is not a valid project URL. It should look like https://abcdefgh.supabase.co")
    return f"{parts.scheme}://{parts.netloc}"


class SupabaseClient:
    def __init__(self, url: str, anon_key: str, transport: httpx.BaseTransport | None = None):
        if not url or not anon_key:
            raise SyncError("Cloud sync is not configured (Supabase URL / anon key missing).")
        self.url = normalize_url(url)
        self.anon = anon_key
        self._http = httpx.Client(transport=transport, timeout=httpx.Timeout(30, read=600, write=600))
        self._creds: tuple[str, str] | None = None
        self.token: str | None = None
        self.user_id: str | None = None

    def close(self) -> None:
        self._http.close()

    # ---- auth
    def sign_in(self, email: str, password: str) -> None:
        self._creds = (email, password)
        try:
            r = self._http.post(
                f"{self.url}/auth/v1/token", params={"grant_type": "password"},
                headers={"apikey": self.anon}, json={"email": email, "password": password},
            )
        except httpx.HTTPError as e:
            raise SyncError(f"Could not reach Supabase: {e}") from e
        if r.status_code != 200:
            raise SyncError(f"Sign-in failed ({_message(r)})")
        j = r.json()
        self.token, self.user_id = j["access_token"], j["user"]["id"]

    def _headers(self, extra: dict | None = None) -> dict:
        h = {"apikey": self.anon, "Authorization": f"Bearer {self.token or self.anon}"}
        h.update(extra or {})
        return h

    def _request(self, method: str, path: str, *, params=None, json=None, headers=None, content: Callable | None = None) -> httpx.Response:
        """`content` is a factory so a streamed upload can be replayed after a token refresh."""
        for attempt in (0, 1):
            try:
                r = self._http.request(
                    method, f"{self.url}{path}", params=params, json=json,
                    content=content() if content else None, headers=self._headers(headers),
                )
            except httpx.HTTPError as e:
                raise SyncError(f"Network error: {e}") from e
            if r.status_code == 401 and attempt == 0 and self._creds:
                self.sign_in(*self._creds)  # access tokens last an hour; long uploads can outlive one
                continue
            break
        if r.status_code >= 400:
            raise SyncError(_message(r))
        return r

    # ---- database (PostgREST)
    def select(self, table: str, **params) -> list[dict]:
        return self._request("GET", f"/rest/v1/{table}", params=params).json()

    def upsert(self, table: str, rows: list[dict], on_conflict: str) -> None:
        if rows:
            self._request(
                "POST", f"/rest/v1/{table}", params={"on_conflict": on_conflict}, json=rows,
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            )

    def delete(self, table: str, **filters) -> None:
        self._request("DELETE", f"/rest/v1/{table}", params=filters, headers={"Prefer": "return=minimal"})

    # ---- storage
    def upload(self, bucket: str, path: str, file_path: str | Path, progress: Callable[[int, int], None] | None = None) -> None:
        file_path = Path(file_path)
        total = file_path.stat().st_size
        ctype = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"

        def body():
            sent = 0
            with open(file_path, "rb") as f:
                while chunk := f.read(CHUNK):
                    sent += len(chunk)
                    if progress:
                        progress(sent, total)
                    yield chunk

        self._request(
            "POST", f"/storage/v1/object/{bucket}/{quote(path)}", content=body,
            headers={"Content-Type": ctype, "Content-Length": str(total), "x-upsert": "true"},
        )

    def remove(self, bucket: str, paths: list[str]) -> None:
        if paths:
            self._request("DELETE", f"/storage/v1/object/{bucket}", json={"prefixes": paths})
