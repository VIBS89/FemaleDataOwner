"""`converdata eval discovery`: corre el set de evaluación y calcula las métricas de salida de la fase 1a.

| Métrica | Criterio (OP-01) |
|---|---|
| Hit@1 / Hit@3 sobre preguntas con respuesta | D1: ≥ 65 % / ≥ 85 % |
| Calibración: candidatos principales con confianza ≥ 0.8 que son correctos | D2: ≥ 85 % |
| Brechas correctas: preguntas sin respuesta disponible que terminan en `knowledge_gap` sin candidato ≥ 0.6 | — |
| Fugas: textos prohibidos (objetos fuera de la visibilidad) en la respuesta | D6: 0 |
| Objetos inventados en la narrativa | 0 |
| Latencia p50 / p95 | D5: < 5 s / < 10 s |
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from converdata.bootstrap import user_with_databases
from converdata.discovery.engine import narrative_mentions_ok
from converdata.flows.discover import DiscoverService


class EvalCase(BaseModel):
    id: str
    question: str
    type: str = "A"  # A directa · B vocabulario · C varios saltos · D entidad entre BDs · E exploración · G sin respuesta
    expected: list[str] = Field(default_factory=list)
    expected_related: list[str] = Field(default_factory=list)  # tablas que deben aparecer en relaciones/caminos
    databases: list[str] | None = None
    groups: list[str] = Field(default_factory=list)
    expect_gap: bool = False
    forbidden: list[str] = Field(default_factory=list)


def load_cases(path: str | Path) -> list[EvalCase]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    defaults = data.get("defaults", {})
    return [EvalCase.model_validate({**defaults, **c}) for c in data["cases"]]


@dataclass
class CaseResult:
    case: EvalCase
    ranked: list[str]
    top_confidence: float
    hit1: bool
    hit3: bool
    gap_ok: bool | None
    leaks: list[str]
    invented: bool
    latency_ms: int
    status: str
    steps: list[str] = field(default_factory=list)
    related_ok: bool | None = None  # C: las tablas esperadas aparecen en relaciones o caminos de unión
    duplicates: list[str] = field(default_factory=list)  # D: copias de la misma entidad mostradas por separado

    @property
    def ok(self) -> bool:
        if self.case.expect_gap:
            return bool(self.gap_ok) and not self.leaks
        return self.hit1 and not self.leaks and not self.invented and self.related_ok is not False


@dataclass
class EvalReport:
    results: list[CaseResult]

    def _answerable(self):
        return [r for r in self.results if not r.case.expect_gap]

    def by_type(self) -> dict[str, dict[str, float]]:
        out = {}
        for t in sorted({r.case.type for r in self.results}):
            rs = [r for r in self.results if r.case.type == t]
            ans = [r for r in rs if not r.case.expect_gap]
            row = {"n": len(rs), "ok": _pct(sum(r.ok for r in rs), len(rs))}
            if ans:
                row["hit@1"] = _pct(sum(r.hit1 for r in ans), len(ans))
                row["hit@3"] = _pct(sum(r.hit3 for r in ans), len(ans))
            rel = [r for r in rs if r.related_ok is not None]
            if rel:
                row["related"] = _pct(sum(bool(r.related_ok) for r in rel), len(rel))
            row["dups"] = sum(len(r.duplicates) for r in rs)
            out[t] = row
        return out

    @property
    def metrics(self) -> dict[str, float]:
        ans = self._answerable()
        gaps = [r for r in self.results if r.case.expect_gap]
        confident = [r for r in ans if r.top_confidence >= 0.8]
        lat = sorted(r.latency_ms for r in self.results)
        p95 = lat[min(len(lat) - 1, int(round(0.95 * (len(lat) - 1))))] if lat else 0
        return {
            "cases": len(self.results),
            "hit@1": _pct(sum(r.hit1 for r in ans), len(ans)),
            "hit@3": _pct(sum(r.hit3 for r in ans), len(ans)),
            "calibration@0.8": _pct(sum(r.hit1 for r in confident), len(confident)),
            "confident_answers": len(confident),
            "gap_ok": _pct(sum(bool(r.gap_ok) for r in gaps), len(gaps)),
            "leaks": sum(len(r.leaks) for r in self.results),
            "duplicates": sum(len(r.duplicates) for r in self.results),
            "invented": sum(r.invented for r in self.results),
            "p50_ms": int(statistics.median(lat)) if lat else 0,
            "p95_ms": p95,
        }

    def render(self) -> str:
        m = self.metrics
        lines = [
            f"Casos: {m['cases']} · Hit@1 {m['hit@1']} % · Hit@3 {m['hit@3']} % · "
            f"Calibración≥0.8 {m['calibration@0.8']} % (n={m['confident_answers']}) · Brechas correctas {m['gap_ok']} % · "
            f"Fugas {m['leaks']} · Inventados {m['invented']} · p50 {m['p50_ms']} ms · p95 {m['p95_ms']} ms",
            "Por tipo: " + " · ".join(
                f"{t} {v['ok']} % (n={v['n']}" + (f", related {v['related']} %" if "related" in v else "")
                + (f", dups {v['dups']}" if v["dups"] else "") + ")"
                for t, v in self.by_type().items()
            ),
            "",
        ]
        for r in self.results:
            mark = "OK " if r.ok else "ERR"
            got = ", ".join(r.ranked[:3]) or "(sin candidatos)"
            extra = f" fugas={r.leaks}" if r.leaks else ""
            extra += " inventado" if r.invented else ""
            extra += " sin_camino" if r.related_ok is False else ""
            extra += f" duplicados={r.duplicates}" if r.duplicates else ""
            lines.append(f"{mark} {r.case.id:<7} conf={r.top_confidence:.2f} → {got}{extra}")
        return "\n".join(lines)


def _pct(n: int, d: int) -> float:
    return round(100.0 * n / d, 1) if d else 0.0


def evaluate(service: DiscoverService, cases: list[EvalCase]) -> EvalReport:
    results = []
    for case in cases:
        user = user_with_databases(service, f"eval:{case.id}", case.databases, case.groups)
        env = service.run(case.question, user, client="api")
        disc = env.discovery
        ranked = []
        if disc:
            ranked = [c.asset_key for c in disc.candidates] + [a.asset_key for a in disc.alternatives]
        top_conf = disc.candidates[0].confidence if disc and disc.candidates else 0.0
        expected = set(case.expected)
        dump = env.model_dump_json(by_alias=True)
        leaks = [f for f in case.forbidden if f in dump]
        invented = bool(disc) and not narrative_mentions_ok(env.answer_text, disc, service.deps.catalog)
        gap_ok = None
        if case.expect_gap:
            gap_ok = bool(disc) and disc.knowledge_gap and top_conf < 0.6
        record = service.deps.audit.records[-1] if getattr(service.deps.audit, "records", None) else None
        related_ok = None
        if case.expected_related:
            shown = set()
            if disc:
                for r in disc.related:
                    shown.update({r.from_, r.to})
                for path in getattr(disc, "join_paths", []):
                    shown.update(path.tables)
            related_ok = set(case.expected_related) <= shown
        duplicates = _entity_duplicates(ranked, service)
        results.append(
            CaseResult(
                case=case,
                ranked=ranked,
                top_confidence=top_conf,
                hit1=bool(ranked) and ranked[0] in expected,
                hit3=bool(expected.intersection(ranked[:3])),
                gap_ok=gap_ok,
                leaks=leaks,
                invented=invented,
                latency_ms=env.timings_ms.get("total", 0),
                status=env.status,
                steps=[f"{s.step}:{s.detail or s.error or 'ok'}" for s in record.steps] if record else [],
                related_ok=related_ok,
                duplicates=duplicates,
            )
        )
    return EvalReport(results)


def _entity_duplicates(ranked: list[str], service: DiscoverService) -> list[str]:
    """Columnas con el mismo nombre en tablas de la misma entidad de negocio mostradas más de una vez (F19)."""
    graph = service.deps.graph
    if graph is None:
        return []
    seen, dups = set(), []
    for key in ranked:
        sig = graph.entity_signature(key)  # misma entidad, misma tabla, misma columna = copia del mismo dato
        if sig is None:
            continue
        if sig in seen:
            dups.append(key)
        seen.add(sig)
    return dups
