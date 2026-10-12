"""Per-Deal JSON storage with atomic writes and an append-only audit trail (Req 22, 27.1)."""
from __future__ import annotations

import json
import os
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path

from .security import redact_obj
from .settings import get_settings

SECTION_ORDER = ["s2a", "s2b", "s3", "s4", "s5"]
_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


class AppError(Exception):
    """Error returned to the Frontend as {error_code, message, fields?}."""

    def __init__(self, status: int, code: str, message: str, fields: list | None = None, details=None):
        super().__init__(message)
        self.status, self.code, self.message, self.fields, self.details = status, code, message, fields, details


def now_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def deal_lock(deal_id: str) -> threading.RLock:
    with _locks_guard:
        return _locks.setdefault(deal_id, threading.RLock())


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{uuid.uuid4().hex[:6]}.tmp")
    with tmp.open("wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


class Repo:
    def __init__(self):
        s = get_settings()
        self.root = s.data_dir / "deals"
        self.secrets = s.secrets()
        self.root.mkdir(parents=True, exist_ok=True)

    # ---- paths -------------------------------------------------------------
    def deal_dir(self, deal_id: str) -> Path:
        if not deal_id or not deal_id.isalnum():
            raise AppError(404, "deal_not_found", "Deal not found.")
        return self.root / deal_id

    def path(self, deal_id: str, *parts: str) -> Path:
        return self.deal_dir(deal_id).joinpath(*parts)

    # ---- JSON io -----------------------------------------------------------
    def read(self, deal_id: str, name: str, default=None):
        p = self.path(deal_id, name)
        if not p.exists():
            return default
        return json.loads(p.read_text(encoding="utf-8"))

    def write(self, deal_id: str, name: str, obj) -> None:
        data = json.dumps(redact_obj(obj, self.secrets), indent=1, ensure_ascii=False, default=str)
        _atomic_write_bytes(self.path(deal_id, name), data.encode("utf-8"))

    def write_bytes(self, deal_id: str, name: str, data: bytes) -> Path:
        p = self.path(deal_id, name)
        _atomic_write_bytes(p, data)
        return p

    # ---- deals -------------------------------------------------------------
    def create_deal(self, intake: dict) -> dict:
        deal_id = uuid.uuid4().hex[:12]
        d = self.deal_dir(deal_id)
        d.mkdir(parents=True)
        deal = {
            "deal_id": deal_id,
            "created_at": now_iso(),
            "intake": intake,
            "next_doc_seq": 1,
            "next_ev_seq": 1,
            "documents": [],
            "financial": {"status": "not_loaded", "source": None, "confirmed": False},
            "sections": {k: {"status": "not_run", "message": None, "errors": [], "updated_at": None} for k in SECTION_ORDER + ["s6_support"]},
            "s3_approved": False,
        }
        self.write(deal_id, "deal.json", deal)
        self.write(deal_id, "audit_trail.json", [])
        self.write(deal_id, "evidence.json", {})
        return deal

    def get_deal(self, deal_id: str) -> dict:
        deal = self.read(deal_id, "deal.json")
        if deal is None:
            raise AppError(404, "deal_not_found", "Deal not found.")
        return deal

    def save_deal(self, deal: dict) -> None:
        self.write(deal["deal_id"], "deal.json", deal)

    def list_deals(self) -> list[dict]:
        out = []
        for p in sorted(self.root.glob("*/deal.json")):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                out.append({"deal_id": d["deal_id"], "created_at": d["created_at"], "borrower": d["intake"]["DI-BORROWER"]["value"],
                            "facility_type": d["intake"]["DI-FACILITY_TYPE"]["value"]})
            except Exception:
                continue
        return sorted(out, key=lambda x: x["created_at"], reverse=True)

    # ---- audit trail (append-only) ------------------------------------------
    def append_audit(self, deal_id: str, entry: dict) -> dict:
        """Append one entry; raises on failure so callers apply changes only after the audit write (Req 22.8)."""
        with deal_lock(deal_id):
            trail = self.read(deal_id, "audit_trail.json", [])
            entry = {"seq": len(trail) + 1, "timestamp": now_iso(), **entry}
            trail.append(entry)
            try:
                self.write(deal_id, "audit_trail.json", trail)
            except Exception as exc:  # pragma: no cover - disk failure
                raise AppError(500, "audit_write_failed", "The audit entry was not saved, so the change was not applied.") from exc
            return entry

    def audit(self, deal_id: str) -> list[dict]:
        return self.read(deal_id, "audit_trail.json", [])

    # ---- section state ------------------------------------------------------
    @staticmethod
    def set_section(deal: dict, key: str, status: str, message: str | None = None, errors: list | None = None) -> None:
        deal["sections"][key] = {"status": status, "message": message, "errors": errors or [], "updated_at": now_iso()}

    @staticmethod
    def mark_later_stale(deal: dict, key: str) -> None:
        """A successful re-run of a section makes later completed sections out of date."""
        # 2A and 2B are independent; both feed Section 3 onward. A CSV reload ("financial") also feeds Section 3 onward.
        start = max(SECTION_ORDER.index(key) + 1, 2) if key in SECTION_ORDER else 2
        later = SECTION_ORDER[start:]
        for k in later:
            if deal["sections"][k]["status"] == "completed":
                deal["sections"][k]["status"] = "stale"
                deal["sections"][k]["message"] = "Out of date: an earlier section was re-run."
        if "s3" in later or key == "s3":
            deal["s3_approved"] = False

    def delete_tree(self, path: Path) -> None:
        if path.exists():
            shutil.rmtree(path)
