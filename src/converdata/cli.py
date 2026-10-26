"""CLI `converdata`. Por ahora: `converdata discover "<pregunta>"` contra un directorio de catálogo y conocimiento."""

from __future__ import annotations

import argparse
import json
import sys

from converdata.bootstrap import build_service, user_with_databases

ENV_LABEL = {"produccion": "Producción", "qa": "QA", "desarrollo": "Desarrollo", "dr": "DR"}
SOURCE_LABEL = {
    "human": "revisada por un responsable",
    "data_dictionary": "diccionario de datos",
    "ms_description": "MS_Description",
    "document": "documento",
    "generated": "sugerida por IA, sin revisar",
}


def render(envelope) -> str:
    """Tarjetas de candidatos con el formato de la propuesta (F12 §Respuestas de descubrimiento)."""
    lines = [envelope.answer_text, *(f"Nota: {a}" for a in envelope.assumptions), ""]
    disc = envelope.discovery
    if not disc:
        return "\n".join(lines)
    if disc.candidates:
        lines.append("Posibles coincidencias")
    for c in disc.candidates:
        name = c.column or c.table
        lines.append(f"\n{c.rank}. {name:<58} Confianza: {round(c.confidence * 100)} %")
        for loc in c.locations:
            lines.append(
                f"   Base de datos: {c.database} · Tabla: {c.schema_}.{c.table} · "
                f"Ambiente: {ENV_LABEL.get(loc.environment, loc.environment)} · Servidor: {loc.server}"
            )
        if c.drift_warning:
            lines.append(f"   ⚠ {c.drift_warning}")
        lines.append(f"   Descripción: {c.description or '—'}  [{SOURCE_LABEL[c.description_source]}]")
        for r in c.business_rules:
            lines.append(f"   Regla: {r.id} · {r.text}{'' if r.reviewed else ' (sugerida, sin revisar)'}")
        if c.owners.business or c.owners.technical:
            lines.append(f"   Responsables: {c.owners.business or '—'} / {c.owners.technical or '—'}")
        if c.lineage.upstream or c.lineage.downstream:
            lines.append(f"   Linaje: ← {', '.join(c.lineage.upstream) or '—'} · → {', '.join(c.lineage.downstream) or '—'}")
        lines.append(f"   Por qué: {c.why}")
    if disc.alternatives:
        alts = " · ".join(f"{a.asset_key} ({round(a.confidence * 100)} %)" for a in disc.alternatives)
        lines.append(f"\nAlternativas: {alts}")
    if disc.related:
        rel = " · ".join(f"{r.from_} → {r.to} ({r.relation}{': ' + (r.on or r.via) if (r.on or r.via) else ''})" for r in disc.related)
        lines.append(f"Relacionadas: {rel}")
    if disc.knowledge_gap:
        lines.append("\n[Preguntar al responsable del dominio]")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="converdata")
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("discover", help="DiscoverFlow (F22) sobre un catálogo local")
    d.add_argument("question")
    d.add_argument("--root", default="tests/fixtures/vbank", help="Directorio con config/, catalog/ y knowledge/")
    d.add_argument("--databases", help="BDs visibles para el usuario de desarrollo (coma); por defecto todas")
    d.add_argument("--groups", default="", help="Grupos de AD del usuario de desarrollo (coma)")
    d.add_argument("--models", help="config/models.yaml para usar el gateway de LLM (NIM o Bedrock); sin él, modo determinista")
    d.add_argument("--json", action="store_true", help="Imprime el AnswerEnvelope completo")
    d.add_argument("--embeddings-only", action="store_true", help="Del gateway solo usa los embeddings (sin nodos LLM)")
    llm = sub.add_parser("llm", help="Gateway de LLM (F16)")
    llm_sub = llm.add_subparsers(dest="llm_command", required=True)
    smoke = llm_sub.add_parser("smoke", help="Prueba cada rol contra su proveedor (salida estructurada y embeddings)")
    smoke.add_argument("--models", default="config/models.yaml")
    ev = sub.add_parser("eval", help="Evaluación offline (F25)")
    ev_sub = ev.add_subparsers(dest="eval_command", required=True)
    evd = ev_sub.add_parser("discovery", help="Set de evaluación del DiscoverFlow: Hit@k, calibración, brechas, fugas, latencia")
    evd.add_argument("--root", default="tests/fixtures/vbank")
    evd.add_argument("--cases", help="YAML de casos; por defecto <root>/eval/discovery.yaml")
    evd.add_argument("--models", help="config/models.yaml para evaluar con el gateway de LLM")
    evd.add_argument(
        "--patterns", default="all",
        help="Patrones activos: all | none | lista separada por comas (query_expansion,grade,review,cascade)",
    )
    evd.add_argument("--embeddings-only", action="store_true", help="Del gateway solo usa los embeddings (sin nodos LLM)")
    evd.add_argument("--min-hit3", type=float, help="Sale con código 1 si Hit@3 queda por debajo (alerta de regresión, OP-05)")
    cat = sub.add_parser("catalog", help="Catalog Builder (F1): descubre los esquemas con el login de metadatos")
    cat_sub = cat.add_subparsers(dest="catalog_command", required=True)
    cb = cat_sub.add_parser("build", help="Extrae metadatos, enriquece y escribe el catálogo (también refresca)")
    cb.add_argument("--config", default="config/databases.local.yaml", help="Inventario de servidores")
    cb.add_argument("--out", default="data/catalog_local", help="Directorio de salida (raíz para `discover --root`)")
    cb.add_argument("--models", help="config/models.yaml: enriquece descripciones con el rol planner del gateway")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.command == "llm":
        return llm_smoke(args.models)
    if args.command == "eval":
        return eval_discovery(args)
    if args.command == "catalog":
        return catalog_build(args)
    service = build_service(args.root, models_path=args.models, llm_nodes=not args.embeddings_only)
    dbs = args.databases.split(",") if args.databases else None
    user = user_with_databases(service, "dev", dbs, [g for g in args.groups.split(",") if g])
    envelope = service.run(args.question, user, client="cli")
    print(json.dumps(envelope.model_dump(by_alias=True), ensure_ascii=False, indent=2) if args.json else render(envelope))
    return 0


def catalog_build(args) -> int:
    from pathlib import Path

    from converdata.config import load_inventory
    from converdata.flows.catalog_build import build_catalog

    enricher = None
    if args.models:
        from converdata.llm.gateway import LLMGateway
        from converdata.llm.nodes import LlmEnricher

        enricher = LlmEnricher(LLMGateway.from_file(args.models).chat("planner"))
    report = build_catalog(load_inventory(args.config), Path(args.out), enricher=enricher)
    print(report.render())
    return 1 if not report.servers_ok else 0


def eval_discovery(args) -> int:
    from pathlib import Path

    from converdata.evaluation.discovery_eval import evaluate, load_cases

    service = build_service(args.root, models_path=args.models, llm_nodes=not args.embeddings_only)
    apply_patterns(service, args.patterns)
    report = evaluate(service, load_cases(args.cases or Path(args.root) / "eval" / "discovery.yaml"))
    print(report.render())
    if args.min_hit3 is not None and report.metrics["hit@3"] < args.min_hit3:
        return 1
    return 0


def apply_patterns(service, spec: str) -> None:
    """Activa solo los patrones pedidos (para comparar contra la línea base)."""
    patterns = getattr(service.deps.settings, "patterns", None)
    if patterns is None:
        return
    names = list(type(patterns).model_fields)
    wanted = set(names) if spec == "all" else set() if spec == "none" else {s.strip() for s in spec.split(",")}
    unknown = wanted - set(names)
    if unknown:
        raise SystemExit(f"Patrones desconocidos: {', '.join(sorted(unknown))}; válidos: {', '.join(names)}")
    for name in names:
        setattr(patterns, name, name in wanted)
    service.rebuild()


def llm_smoke(models_path: str, gateway=None) -> int:
    """F16-CA2: cada rol de chat devuelve salida estructurada parseable; `embed` devuelve la dimensión configurada."""
    import time

    from langchain_core.messages import HumanMessage
    from pydantic import BaseModel

    from converdata.llm.gateway import LLMGateway

    class Ping(BaseModel):
        intent: str
        business_context: str | None = None

    gw = gateway or LLMGateway.from_file(models_path)
    print(f"data_mode={gw.config.data_mode}")
    failures = 0
    question = "Clasifica: '¿dónde está el DUI del cliente en préstamos?'. intent=discovery|data_query; business_context=área."
    for role in gw.config.roles:
        t0 = time.perf_counter()
        try:
            if role == "embed":
                vec = gw.embeddings().embed_query("identificador único del cliente")
                expected = gw.config.roles[role].dimensions
                ok = expected is None or len(vec) == expected
                detail = f"dim={len(vec)}" + ("" if ok else f" (esperada {expected})")
                label = gw.embed_model
            else:
                out = gw.chat(role).with_structured_output(Ping).invoke([HumanMessage(question)])
                ok, detail, label = isinstance(out, Ping), f"intent={getattr(out, 'intent', '?')}", gw.labels[role]
        except Exception as exc:  # se informa y se sigue con el resto de roles
            ok, detail, label = False, f"{type(exc).__name__}: {str(exc)[:160]}", gw.config.roles[role].model
        failures += not ok
        print(f"{'OK ' if ok else 'ERR'} {role:<8} {label:<60} {int((time.perf_counter() - t0) * 1000):>6} ms  {detail}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
