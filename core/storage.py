# core/storage.py

import os
import uuid
import mimetypes
import logging
from io import BytesIO
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, Union

# Lazy import for environments without supabase-py installed
try:
    from supabase import create_client, Client  # server-only
except Exception:  # keep imports lazy-safe for local/dev
    create_client = None
    Client = None  # type: ignore


def _guess_mime(name: str) -> str:
    mt, _ = mimetypes.guess_type(name or "")
    return mt or "application/octet-stream"


class OutputStorage:
    """
    Unified storage helper for generated artifacts (pptx/docx/xlsx/images/etc).

    Primary target: Supabase Storage (private bucket + signed URLs).
    Dev fallback: local file path served by FastAPI StaticFiles at /files/outputs.

    Environment variables:
      - SUPABASE_URL
      - SUPABASE_SERVICE_ROLE_KEY  (preferred, server-only)
      - SUPABASE_SERVICE_KEY       (fallback)
      - SUPABASE_ANON_KEY          (fallback; not recommended for server)
      - SUPABASE_BUCKET_OUTPUT     (default: "user-outputs")
      - SUPABASE_SIGN_TTL          (seconds; default: 604800 = 7 days)
      - FORCE_LOCAL_OUTPUTS        ("true"/"false"; default: false)
      - OUTPUTS_LOCAL_DIR          (default: "/tmp/opex/outputs")
      - SUPABASE_PUBLIC_BUCKET     ("true"/"false"; default: false)
    """

    def __init__(self, bucket: Optional[str] = None, sign_ttl: Optional[int] = None) -> None:
        self.bucket = bucket or os.getenv("SUPABASE_BUCKET_OUTPUT", "user-outputs")
        self.sign_ttl = int(os.getenv("SUPABASE_SIGN_TTL", sign_ttl or 604800))  # 7 days default
        self.force_local = os.getenv("FORCE_LOCAL_OUTPUTS", "false").lower() == "true"
        self.public_bucket = os.getenv("SUPABASE_PUBLIC_BUCKET", "false").lower() == "true"
        self.default_local_dir = os.getenv("OUTPUTS_LOCAL_DIR", "/tmp/opex/outputs")

        self.url = os.getenv("SUPABASE_URL", "")
        # Prefer service-role on server
        self.key = (
            os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            or os.getenv("SUPABASE_SERVICE_KEY")
            or os.getenv("SUPABASE_ANON_KEY")
            or ""
        )

        self.client: Optional[Client] = None
        self.logger = logging.getLogger(self.__class__.__name__)

        if self.url and self.key and create_client:
            try:
                self.client = create_client(self.url, self.key)
                self.logger.info(
                    f"[{self.__class__.__name__}] Supabase client initialized. "
                    f"Bucket='{self.bucket}', URL='{self.url}', Public={self.public_bucket}, "
                    f"ForceLocal={self.force_local}, SignTTL={self.sign_ttl}s"
                )
            except Exception as e:
                self.client = None
                self.logger.warning(
                    f"[{self.__class__.__name__}] Failed to initialize Supabase client: {e}. "
                    "Falling back to local outputs."
                )
        else:
            self.logger.info(
                f"[{self.__class__.__name__}] Supabase not configured (missing SUPABASE_URL/KEY or library). "
                "Using local outputs."
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────
    def save_bytes(
        self,
        data: Union[bytes, bytearray, BytesIO],
        *,
        ext: Optional[str] = None,
        filename: Optional[str] = None,
        user_id: Optional[str] = None,
        local_dir: Optional[str] = None,
        prefix: str = "artifacts",
    ) -> Dict[str, Any]:
        """
        Save in-memory bytes (or BytesIO) to Supabase (preferred) or local dev fallback.
        Returns dict with keys: filename, path (bucket path), download_url (absolute),
        and also signed_url/public_url for clarity.
        """
        # Normalize incoming bytes
        if isinstance(data, BytesIO):
            raw = data.getvalue()
        elif isinstance(data, (bytes, bytearray)):
            raw = bytes(data)
        else:
            raise TypeError(f"data must be bytes/bytearray/BytesIO, got {type(data)}")

        safe_name = self._safe_filename(filename, ext)
        remote_path = self._remote_path(user_id or "anonymous", safe_name, prefix=prefix)

        # Try Supabase unless forced local
        if self.client and not self.force_local:
            ok, err, url_kind, url_value = self._upload_bytes_to_supabase(raw, remote_path, mime_hint=safe_name)
            if ok:
                self.logger.info(
                    f"[{self.__class__.__name__}] Uploaded {safe_name} → {remote_path} | {url_kind}=True"
                )
                out: Dict[str, Any] = {"filename": safe_name, "path": remote_path}
                out[url_kind] = url_value
                out["download_url"] = url_value
                out["absolute_url"] = url_value
                return out
            else:
                self.logger.error(
                    f"[{self.__class__.__name__}] Supabase upload failed for {safe_name}: {err}. "
                    "Falling back to local."
                )

        # Dev/local fallback
        local_base = local_dir or self.default_local_dir
        os.makedirs(local_base, exist_ok=True)
        local_path = os.path.join(local_base, safe_name)
        with open(local_path, "wb") as f:
            f.write(raw)
        self.logger.info(f"[{self.__class__.__name__}] 💾 Saved locally: {local_path} (fallback)")
        return {
            "filename": safe_name,
            "download_url": f"/files/outputs/{safe_name}",
            "path": f"local://{safe_name}",
        }

    def save_file_path(
        self,
        file_path: Union[str, Path],
        *,
        user_id: Optional[str] = None,
        local_dir: Optional[str] = None,
        prefix: str = "artifacts",
        remote_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Upload an existing local file path to Supabase (or fallback local copy)."""
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"File not found: {file_path}")

        safe_name = remote_name or path.name.replace("/", "_").replace("\\", "_")
        remote_path = self._remote_path(user_id or "anonymous", safe_name, prefix=prefix)

        if self.client and not self.force_local:
            try:
                data = path.read_bytes()
                ok, err, url_kind, url_value = self._upload_bytes_to_supabase(data, remote_path, mime_hint=safe_name)
                if ok:
                    self.logger.info(
                        f"[{self.__class__.__name__}] Uploaded {path.name} → {remote_path} | {url_kind}=True"
                    )
                    out: Dict[str, Any] = {"filename": safe_name, "path": remote_path}
                    out[url_kind] = url_value
                    out["download_url"] = url_value
                    out["absolute_url"] = url_value
                    return out
                else:
                    self.logger.error(
                        f"[{self.__class__.__name__}] Supabase upload failed for {path.name}: {err}. "
                        "Falling back to local."
                    )
            except Exception as e:
                self.logger.error(
                    f"[{self.__class__.__name__}] Supabase upload exception for {path.name}: {e}. "
                    "Falling back to local."
                )

        # Dev/local fallback
        local_base = local_dir or self.default_local_dir
        os.makedirs(local_base, exist_ok=True)
        local_dest = Path(local_base) / safe_name
        if str(path.resolve()) != str(local_dest.resolve()):
            local_dest.write_bytes(path.read_bytes())
        self.logger.info(f"[{self.__class__.__name__}] Saved locally: {local_dest} (fallback)")
        return {
            "filename": safe_name,
            "download_url": f"/files/outputs/{safe_name}",
            "path": f"local://{safe_name}",
        }

    def sign_bucket_path(self, remote_path: str) -> Optional[str]:
        """
        Create a signed URL for an existing object path in the bucket (private buckets).
        Returns signed URL string or None.
        """
        if not self.client:
            return None
        try:
            # Include a download hint so the filename is respected by the browser
            file_name = Path(remote_path).name
            signed = self.client.storage.from_(self.bucket).create_signed_url(
                remote_path,
                self.sign_ttl,
                {"download": file_name},  # or True if you don't care about filename
            )
            if isinstance(signed, dict):
                return signed.get("signedURL") or signed.get("signedUrl") or signed.get("signed_url")
            return str(signed)
        except Exception as e:
            self.logger.error(f"[{self.__class__.__name__}] ❌ create_signed_url failed: {e}")
            return None

    def get_public_url(self, remote_path: str) -> Optional[str]:
        """Get public URL for an existing object path in a public bucket."""
        if not self.client:
            return None
        try:
            res = self.client.storage.from_(self.bucket).get_public_url(remote_path)
            if isinstance(res, dict):
                return res.get("publicURL") or res.get("public_url")
            return str(res)
        except Exception as e:
            self.logger.error(f"[{self.__class__.__name__}] ❌ get_public_url failed: {e}")
            return None

    # ──────────────────────────────────────────────────────────────────────────
    # Internals
    # ──────────────────────────────────────────────────────────────────────────
    def _safe_filename(self, filename: Optional[str], ext: Optional[str]) -> str:
        base = (filename or f"{uuid.uuid4().hex}{ext or ''}").strip()
        if ext and not base.lower().endswith(ext.lower()):
            base = f"{base}{ext}"
        # sanitize path separators and weird chars
        base = base.replace("/", "_").replace("\\", "_")
        return base

    def _remote_path(self, user_id: str, filename: str, *, prefix: str = "artifacts") -> str:
        # date-based namespacing keeps the bucket tidy
        today = datetime.now(timezone.utc)
        return f"{prefix}/{user_id}/{today:%Y/%m/%d}/{filename}"

    def _upload_bytes_to_supabase(
        self,
        data: bytes,
        remote_path: str,
        mime_hint: Optional[str] = None,
    ) -> Tuple[bool, Optional[str], str, Optional[str]]:
        """
        Upload bytes to Supabase Storage, handling SDK variants that require a path.
        Returns (ok, error_message, url_kind, url_value) where url_kind ∈ {"signed_url","public_url"}.
        """
        if not self.client:
            return False, "Supabase client not configured", "signed_url", None
    
        file_opts = {
            "contentType": str(_guess_mime(mime_hint or remote_path)),
            "cacheControl": "3600",
            "upsert": "true",
        }
    
        # Strategy 1: pass raw bytes (works on newer supabase-py)
        try:
            self.client.storage.from_(self.bucket).upload(
                path=remote_path,
                file=data,  # <- bytes, not BytesIO
                file_options=file_opts,
            )
        except TypeError as e:
            # Strategy 2: some SDK builds expect a filesystem path
            if "os.PathLike" not in str(e):
                return False, str(e), "signed_url", None
            try:
                import tempfile
                from pathlib import Path as _Path
    
                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    tmp.write(data)
                    tmp_path = tmp.name
                try:
                    self.client.storage.from_(self.bucket).upload(
                        path=remote_path,
                        file=tmp_path,  # <- path-like
                        file_options=file_opts,
                    )
                finally:
                    try:
                        _Path(tmp_path).unlink(missing_ok=True)  # py>=3.8
                    except Exception:
                        pass
            except Exception as e2:
                return False, f"{e}; tmpfile fallback failed: {e2}", "signed_url", None
        except Exception as e:
            return False, str(e), "signed_url", None
    
        # URL resolution
        if self.public_bucket:
            public_url = self.get_public_url(remote_path)
            if not public_url:
                return False, "Failed to get public URL", "public_url", None
            return True, None, "public_url", public_url
    
        signed_url = self.sign_bucket_path(remote_path)
        if not signed_url:
            return False, "Failed to create signed URL", "signed_url", None
        return True, None, "signed_url", signed_url

