"""Los mismos puertos sobre archivos, para desarrollo, pruebas y el modo demo (sin BD `DiscoveryDataAgent`).

- `FileKnowledgeWriter`: edita el directorio del catálogo (`catalog/*.yaml`, `knowledge/rules/curadas.yaml`,
  `knowledge/golden/confirmaciones_usuarios.yaml`).
- `FileCurationRepository`: `stewards.yaml`, `requests.json` y `feedback.jsonl`.
- `FileInventoryStore`: `inventory.yaml`, el inventario de servidores con sus hosts.

En qa y prod la API exige `DISCOVERY_DATA_AGENT_DB`: nada de esto se usa con datos reales.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
from pathlib import Path

import yaml

from discovery_data_agent.builder.catalog_builder import SNAPSHOT_FILES, object_path
from discovery_data_agent.catalog.store import load_objects
from discovery_data_agent.config import ServerConfig
from discovery_data_agent.curation import DescriptionEdit
from discovery_data_agent.models.knowledge import BusinessRule, GoldenDiscovery


def _read_yaml(path: Path, default):
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or default) if path.is_file() else default


def _write_yaml(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


class FileKnowledgeWriter:
    def __init__(self, data_root: Path):
        self.root = Path(data_root)
        self._lock = threading.RLock()

    def write_descriptions(self, edits: list[DescriptionEdit], *, by: str, reason: str) -> int:
        if not edits:
            return 0
        changed = 0
        with self._lock:
            objects = {o.id: o for o in load_objects(self.root / "catalog")}
            for e in edits:
                obj = objects.get(e.physical_id)
                path = object_path(self.root, obj) if obj else None
                if path is None or not path.is_file():
                    continue
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                target = data if e.column is None else next(
                    (c for c in data.get("columns", []) if c["name"].lower() == e.column.lower()), None)
                if target is None or (e.keep_human and target.get("description_source") == "human"):
                    continue
                target["description"], target["description_source"] = e.description, e.source
                target["reviewed"] = e.reviewed
                if e.synonyms is not None:
                    target["synonyms"] = list(e.synonyms)
                _write_yaml(path, data)
                changed += 1
        return changed

    # --- reglas de los responsables ----------------------------------------------------------------
    def _rules_path(self) -> Path:
        return self.root / "knowledge" / "rules" / SNAPSHOT_FILES["rules"]

    def _rules(self) -> list[BusinessRule]:
        return [BusinessRule.model_validate(r) for r in _read_yaml(self._rules_path(), [])]

    def upsert_rule(self, rule: BusinessRule, *, by: str) -> None:
        with self._lock:
            rules = [r for r in self._rules() if r.id != rule.id] + [rule]
            _write_yaml(self._rules_path(), [r.model_dump(exclude_none=True) for r in rules])

    def delete_rule(self, rule_id: str, *, by: str) -> bool:
        with self._lock:
            rules = self._rules()
            kept = [r for r in rules if r.id != rule_id]
            if len(kept) == len(rules):
                return False
            _write_yaml(self._rules_path(), [r.model_dump(exclude_none=True) for r in kept])
            return True

    # --- confirmaciones ----------------------------------------------------------------------------
    def upsert_golden(self, golden: GoldenDiscovery, *, by: str, question: str | None = None) -> None:
        path = self.root / "knowledge" / "golden" / SNAPSHOT_FILES["golden"]
        with self._lock:
            items = [g for g in _read_yaml(path, []) if g.get("id") != golden.id] + [golden.model_dump()]
            _write_yaml(path, items)


class FileCurationRepository:
    def __init__(self, curation_dir: Path):
        self.dir = Path(curation_dir)
        self._lock = threading.RLock()

    # --- responsables ------------------------------------------------------------------------------
    def stewards(self) -> list[dict]:
        return [{"login": str(s["login"]), "domains": list(s.get("domains") or ["*"])}
                for s in _read_yaml(self.dir / "stewards.yaml", [])]

    def save_stewards(self, items: list[dict], *, by: str) -> None:
        _write_yaml(self.dir / "stewards.yaml", [{"login": i["login"], "domains": i["domains"]} for i in items])

    # --- dudas escaladas ---------------------------------------------------------------------------
    def _requests_path(self) -> Path:
        return self.dir / "requests.json"

    def requests(self) -> list[dict]:
        path = self._requests_path()
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []

    def _save_requests(self, items: list[dict]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self._requests_path().write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")

    def add_requests(self, items: list[dict]) -> list[dict]:
        with self._lock:
            current, out = self.requests(), []
            for r in items:
                existing = next((c for c in current if c["trace_id"] == r["trace_id"] and c["user_id"] == r["user_id"]), None)
                if existing is None:
                    current.append(r)
                out.append(existing or r)
            self._save_requests(current)
            return out

    def answer_request(self, request_id: str, status: str, answer: dict) -> dict:
        with self._lock:
            items = self.requests()
            req = next((r for r in items if r["id"] == request_id), None)
            if req is None:
                raise KeyError(request_id)
            req["status"], req["answer"] = status, answer
            self._save_requests(items)
            return req

    # --- votos -------------------------------------------------------------------------------------
    def add_vote(self, vote: dict) -> dict[str, str]:
        path = self.dir / "feedback.jsonl"
        row = {"ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), **vote}
        with self._lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            votes: dict[str, str] = {}
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    if r.get("golden_id") == vote["golden_id"]:
                        votes[r["user_id"]] = r["verdict"]
            return votes


class FileInventoryStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def inventory(self) -> list[ServerConfig]:
        data = _read_yaml(self.path, {})
        return [ServerConfig.model_validate(s) for s in data.get("servers") or []]

    def save_inventory(self, servers: list[ServerConfig], *, by: str) -> None:
        _write_yaml(self.path, {"servers": [s.model_dump(exclude_none=True) for s in servers]})
