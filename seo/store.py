"""Small JSON store kept in data/ and committed by the workflow, so history survives between runs."""
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("SEO_DATA_DIR", ROOT / "data"))


def load_config(path=None):
    with open(path or os.environ.get("SEO_CONFIG", ROOT / "config.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def today() -> str:
    return date.today().isoformat()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json(rel: str, obj) -> Path:
    p = DATA / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    return p


def read_json(rel: str, default=None):
    p = DATA / rel
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def write_text(rel: str, text: str) -> Path:
    p = DATA / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def list_dated(folder: str):
    """Sorted list of YYYY-MM-DD stems in data/<folder>."""
    d = DATA / folder
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.json"))


def previous_audit(before: str):
    days = [d for d in list_dated("audits") if d < before]
    return read_json(f"audits/{days[-1]}.json") if days else None


def audit_on_or_before(day: str):
    days = [d for d in list_dated("audits") if d <= day]
    return read_json(f"audits/{days[-1]}.json") if days else None
