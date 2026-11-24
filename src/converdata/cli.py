"""CLI `converdata`: descubrimiento, evaluación y compuerta, Builder del catálogo, BD `ConverData` y auditoría."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from converdata.bootstrap import (build_service, build_service_from_db, build_service_with_knowledge,
                                  user_with_databases)

GATE_SUITES = ("calidad", "permisos", "inyeccion", "guardas", "robustez", "determinismo", "auditoria")
DEFAULT_GATE_ROOTS = ("tests/fixtures/vbank", "tests/fixtures/bancos")
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


def load_dotenv(path: str | Path = ".env") -> None:
    """Carga `CLAVE=valor` de un `.env` local (ignorado por git). No pisa variables ya definidas en el entorno."""
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip("'\"")
        if key and value and key not in os.environ:
            os.environ[key] = value


def use_system_certificates() -> None:
    """Valida TLS con el almacén del sistema operativo (antivirus o proxy que inspeccionan HTTPS) en vez de certifi."""
    try:
        import truststore
    except ImportError:
        return
    truststore.inject_into_ssl()


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    use_system_certificates()
    parser = argparse.ArgumentParser(prog="converdata")
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("discover", help="DiscoverFlow (F22) sobre un catálogo local")
    d.add_argument("question")
    d.add_argument("--root", default="tests/fixtures/vbank", help="Directorio con config/, catalog/ y knowledge/")
    d.add_argument("--db", action="store_true", help=DB_HELP + " en lugar de --root")
    d.add_argument("--databases", help="BDs visibles para el usuario de desarrollo (coma); por defecto todas")
    d.add_argument("--groups", default="", help="Grupos de AD del usuario de desarrollo (coma)")
    d.add_argument("--models", help="config/models.yaml para usar el gateway de LLM; sin él, modo determinista")
    d.add_argument("--json", action="store_true", help="Imprime el AnswerEnvelope completo")
    d.add_argument("--figures", metavar="INVENTARIO", help="Activa las cifras agregadas (solo totales) y las calcula en "
                   "los servidores de este inventario, p. ej. config/databases.local.yaml")
    llm = sub.add_parser("llm", help="Gateway de LLM (F16)")
    llm_sub = llm.add_subparsers(dest="llm_command", required=True)
    smoke = llm_sub.add_parser("smoke", help="Prueba cada rol contra su proveedor (salida estructurada)")
    smoke.add_argument("--models", default="config/models.yaml")
    ev = sub.add_parser("eval", help="Evaluación offline (F25)")
    ev_sub = ev.add_subparsers(dest="eval_command", required=True)
    evd = ev_sub.add_parser("discovery", help="Set de evaluación del DiscoverFlow: Hit@k, calibración, brechas, fugas, latencia")
    evd.add_argument("--root", default="tests/fixtures/vbank")
    evd.add_argument("--db", action="store_true", help=DB_HELP + "; `--root` aporta los casos y los ajustes")
    evd.add_argument("--cases", help="YAML de casos; por defecto <root>/eval/discovery.yaml")
    evd.add_argument("--models", help="config/models.yaml para evaluar con el gateway de LLM")
    evd.add_argument(
        "--patterns", default="all",
        help="Patrones activos: all | none | lista separada por comas (query_expansion,grade,review,cascade)",
    )
    evd.add_argument("--knowledge", help="Directorio con fuentes de conocimiento (items/, rules/, golden/, lineage/) que se "
                                         "añaden al catálogo de --root: mide cuánto aportan sin tocar el catálogo")
    evd.add_argument("--min-hit3", type=float, help="Sale con código 1 si Hit@3 queda por debajo (alerta de regresión, OP-05)")
    evg = ev_sub.add_parser("gate", help="Compuerta de calidad: calidad, permisos, inyección, robustez, determinismo y auditoría")
    evg.add_argument("--root", action="append", help="Directorio de catálogo; se puede repetir. Por defecto los dos fixtures")
    evg.add_argument("--db", action="store_true",
                     help=DB_HELP + "; `--root` (uno solo) aporta los casos, la línea base y los umbrales")
    evg.add_argument("--cases", help="YAML de casos (solo con un --root); por defecto <root>/eval/discovery.yaml")
    evg.add_argument("--models", help="config/models.yaml para correr la compuerta con el gateway de LLM")
    evg.add_argument("--suites", default="all", help="all o lista separada por comas: " + ",".join(GATE_SUITES))
    evg.add_argument("--out", help="Directorio donde escribir la evidencia (gate-<catálogo>.json y .md)")
    evg.add_argument("--write-baseline", action="store_true", help="Guarda el resultado de calidad como nueva línea base")
    aud = sub.add_parser("audit", help="Auditoría (F11, OP-05)")
    aud_sub = aud.add_subparsers(dest="audit_command", required=True)
    av = aud_sub.add_parser("verify", help="Comprueba la integridad de la auditoría: cadena de hashes (archivos) o permisos (BD)")
    av.add_argument("--dir", default="data/audit", help="Directorio con audit-AAAA-MM-DD.jsonl")
    av.add_argument("--db", action="store_true", help="Auditoría en la BD ConverData (CONVERDATA_DB): la cuenta no puede modificarla")
    ap = aud_sub.add_parser("purge", help="Purga por retención de la auditoría en la BD ConverData (rol converdata_maintenance)")
    ap.add_argument("--keep-days", type=int, default=180, help="Días que se conservan; el mínimo es 180 (OP-05)")
    dbp = sub.add_parser("db", help="BD ConverData (OP-02): migraciones")
    db_sub = dbp.add_subparsers(dest="db_command", required=True)
    dm = db_sub.add_parser("migrate", help="Aplica las migraciones pendientes de db/converdata (cada una en una transacción)")
    dm.add_argument("--dir", default="db/converdata", help="Directorio con NNN_descripcion.sql")
    dm.add_argument("--status", action="store_true", help="Solo muestra lo pendiente, sin aplicar")
    cat = sub.add_parser("catalog", help="Catalog Builder (F1): descubre los esquemas con el login de metadatos")
    cat_sub = cat.add_subparsers(dest="catalog_command", required=True)
    cb = cat_sub.add_parser("build", help="Extrae metadatos, enriquece y escribe el catálogo (también refresca)")
    cb.add_argument("--config", help="Inventario de servidores en YAML. Por defecto config/databases.local.yaml; con "
                                     "--db, el inventario guardado en la BD (el que administra la API)")
    cb.add_argument("--out", help="Directorio de salida (raíz para `discover --root`); por defecto data/catalog_local. "
                                  "Con --db es solo el área de trabajo y por defecto es temporal")
    cb.add_argument("--models", help="config/models.yaml: enriquece descripciones con el rol planner del gateway")
    cb.add_argument("--db", action="store_true",
                    help="Parte del catálogo publicado en la BD ConverData (CONVERDATA_DB) y publica el resultado en ella")
    cp = cat_sub.add_parser("publish", help="Publica un directorio de catálogo en la BD ConverData (importación inicial)")
    cp.add_argument("--root", required=True, help="Directorio con config/, catalog/ y knowledge/")
    cp.add_argument("--by", default="cli", help="Quién publica (queda en modified_by, en catalog_version y en la auditoría)")
    cp.add_argument("--force", action="store_true",
                    help="Reemplaza un catálogo ya publicado: borra de la BD lo que no esté en el directorio, "
                         "incluidas reglas, confirmaciones y responsables")
    ce = cat_sub.add_parser("export", help="Exporta el catálogo de la BD ConverData a un directorio YAML (revisión en git)")
    ce.add_argument("--out", required=True, help="Directorio de salida")
    ce.add_argument("--with-questions", action="store_true",
                    help="Incluye las confirmaciones, que llevan el texto de las preguntas (no apto para git)")
    mcp = sub.add_parser("mcp", help="converdata-mcp (F12) para Claude y otros agentes")
    mcp_sub = mcp.add_subparsers(dest="mcp_command", required=True)
    ms = mcp_sub.add_parser("serve", help="Servidor MCP por stdio sobre un catálogo local (solo local/dev)")
    ms.add_argument("--root", default="tests/fixtures/vbank", help="Directorio con config/, catalog/ y knowledge/")
    ms.add_argument("--databases", help="BDs visibles para el usuario de desarrollo (coma); por defecto todas")
    ms.add_argument("--groups", default="", help="Grupos de AD del usuario de desarrollo (coma)")
    ms.add_argument("--user", default="dev", help="user_id de desarrollo que queda en la auditoría")
    ms.add_argument("--models", help="config/models.yaml para usar el gateway de LLM; sin él, modo determinista")
    args = parser.parse_args(argv)

    if args.command == "mcp":  # stdout es el canal del protocolo: nada más puede escribir en él
        from converdata.integration.mcp.stdio import serve

        return serve(args)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.command == "llm":
        return llm_smoke(args.models)
    if args.command == "eval":
        return eval_gate(args) if args.eval_command == "gate" else eval_discovery(args)
    if args.command == "audit":
        return audit_purge(args) if args.audit_command == "purge" else audit_verify(args)
    if args.command == "db":
        return db_migrate(args)
    if args.command == "catalog":
        return {"build": catalog_build, "publish": catalog_publish, "export": catalog_export}[args.catalog_command](args)
    if args.db:
        service = build_service_from_db(db_connect(), models_path=args.models)
    else:
        service = build_service(args.root, models_path=args.models)
    dbs = args.databases.split(",") if args.databases else None
    user = user_with_databases(service, "dev", dbs, [g for g in args.groups.split(",") if g])
    executor = None
    if args.figures:
        # Cifras agregadas en desarrollo: con el login de metadatos del inventario (en la API, con el de cada usuario).
        from converdata.config import load_inventory
        from converdata.metadata.sqlserver import SqlServerMetadata

        inventory = load_inventory(args.figures)
        if any(server.environment == "produccion" for server in inventory.servers):
            # Aquí se usa el login de metadatos y no hay auditoría durable: contra producción, solo por la API.
            raise SystemExit("--figures es solo para desarrollo: el inventario tiene servidores de producción")
        service.deps.settings.features.ask_flow = True

        def executor(server_id: str, database: str, sql: str):
            conn = SqlServerMetadata(inventory.server(server_id))._pyodbc_connect(database)
            try:
                return [tuple(row) for row in conn.cursor().execute(sql).fetchmany(50)]
            finally:
                conn.close()

    envelope = service.run(args.question, user, client="cli", executor=executor)
    print(json.dumps(envelope.model_dump(by_alias=True), ensure_ascii=False, indent=2) if args.json else render(envelope))
    return 0


DB_HELP = "Usa el catálogo publicado en la BD ConverData (variable CONVERDATA_DB)"


def db_connect():
    """Conexión a la BD `ConverData` según `CONVERDATA_DB`; termina con un mensaje claro si no está definida."""
    from converdata.storage.connection import ENV_VAR, connection_string, connector

    conn_str = connection_string()
    if conn_str is None:
        raise SystemExit(f"Define {ENV_VAR} con la cadena ODBC de la BD ConverData "
                         "(p. ej. SERVER=<servidor>;DATABASE=ConverData;Trusted_Connection=yes;Encrypt=yes)")
    return connector(conn_str)


def db_migrate(args) -> int:
    from converdata.storage.migrations import MigrationError, migrate, pending

    connect = db_connect()
    try:
        todo = pending(connect, args.dir) if args.status else migrate(connect, args.dir)
    except MigrationError as exc:
        print(f"ERROR: {exc}")
        return 1
    verb = "Pendientes" if args.status else "Aplicadas"
    print(f"{verb}: {', '.join(m.path.name for m in todo) or 'ninguna (la BD está al día)'}")
    return 0


def audit_event(connect, kind: str, user_id: str, **data) -> None:
    """Deja constancia en `audit.audit_event` de lo que la CLI escribe en la BD (misma auditoría que la API)."""
    from converdata.audit.sqlserver import SqlServerAuditSink

    SqlServerAuditSink(connect).event(kind, user_id, client="cli", **data)


def catalog_publish(args) -> int:
    from converdata.catalog.store import load_snapshot
    from converdata.storage.catalog_repository import SqlServerCatalogRepository

    connect = db_connect()
    repository = SqlServerCatalogRepository(connect)
    current = repository.version()
    if current is not None and not args.force:
        print(f"La BD ConverData ya tiene un catálogo publicado (versión {current}). Publicar un directorio lo reemplaza "
              "entero: borra lo que no esté en él, incluidas reglas, confirmaciones y responsables. Para un refresco usa "
              "`catalog build --db`; si de verdad quieres reemplazarlo, repite con --force.")
        return 1
    snapshot = load_snapshot(args.root)
    audit_event(connect, "catalog_publish_started", args.by, objects=len(snapshot.objects), replaced_version=current)
    result = repository.publish(snapshot, published_by=args.by, reason="import")
    print(f"Versión {result.version} · " + (", ".join(f"{k}={v}" for k, v in sorted(result.counts.items()))
                                            if result.changed else "sin cambios"))
    return 0


def catalog_export(args) -> int:

    from converdata.builder.catalog_builder import write_snapshot
    from converdata.storage.catalog_repository import SqlServerCatalogRepository

    loaded = SqlServerCatalogRepository(db_connect()).load()
    if loaded is None:
        print("La BD ConverData no tiene ningún catálogo publicado")
        return 1
    snapshot, version = loaded
    write_snapshot(Path(args.out), snapshot, include_questions=args.with_questions)
    print(f"Versión {version}: {len(snapshot.objects)} objetos exportados a {args.out}"
          + ("" if args.with_questions else " (sin las confirmaciones, que llevan preguntas)"))
    return 0


def audit_purge(args) -> int:
    conn = db_connect()()
    try:
        conn.autocommit = True
        row = conn.cursor().execute("EXEC audit.usp_purge @keep_days = ?", args.keep_days).fetchone()
        print(f"Purgadas {row[0]} preguntas, {row[1]} eventos, {row[3]} dudas escaladas y {row[4]} textos originales "
              f"de confirmaciones anteriores a {row[2]:%Y-%m-%d %H:%M} UTC")
        return 0
    except Exception as exc:
        print(f"ERROR: {str(exc)[:300]}")
        return 1
    finally:
        conn.close()


def catalog_build(args) -> int:
    import shutil
    import tempfile

    from converdata.application.catalog_refresh import refresh_catalog
    from converdata.config import Inventory, load_inventory
    from converdata.metadata.sqlserver import SqlServerMetadata

    enricher = None
    if args.models:
        from converdata.llm.gateway import LLMGateway
        from converdata.llm.nodes import build_enricher

        enricher = build_enricher(LLMGateway.from_file(args.models))
    if not args.db:
        result = refresh_catalog(load_inventory(args.config or "config/databases.local.yaml"),
                                 Path(args.out or "data/catalog_local"), source_factory=SqlServerMetadata, enricher=enricher)
        print(result.report.render())
        return 0 if result.report.servers_ok else 1

    from converdata.storage.catalog_repository import SqlServerCatalogRepository
    from converdata.storage.connection import connection_string, describe

    connect = db_connect()
    repository = SqlServerCatalogRepository(connect)
    if args.config:
        inventory = load_inventory(args.config)
    else:
        # El inventario que administra la API guarda cómo entran los usuarios (login SQL). El Builder es una tarea
        # programada: entra con la cuenta del proceso (gMSA), salvo que el servidor declare su propio login de metadatos.
        inventory = Inventory(servers=[s if s.metadata_user_env else s.model_copy(update={"auth": "windows"})
                                       for s in repository.inventory()])
        if not inventory.servers:
            print("La BD ConverData no tiene inventario de servidores: regístralos desde Administración o pasa --config.")
            return 1
        refused = builder_hosts_refused(inventory.servers)
        if refused:
            print("ERROR: " + refused)
            return 1
    scratch = None if args.out else tempfile.mkdtemp(prefix="converdata-build-")
    audit_event(connect, "catalog_build_started", "builder", enrich=enricher is not None)
    try:
        # El Builder no lee lo curado (las confirmaciones salen de preguntas de usuarios): parte de `scope="build"`.
        result = refresh_catalog(inventory, Path(args.out or scratch), source_factory=SqlServerMetadata, enricher=enricher,
                                 repository=repository, published_by="builder", scope="build",
                                 own_databases={describe(connection_string()).split("/")[-1]})
    except Exception as exc:
        audit_event(connect, "catalog_build_finished", "builder", status="error", error_type=type(exc).__name__)
        raise
    finally:
        if scratch:
            shutil.rmtree(scratch, ignore_errors=True)
    report, published = result.report, result.published
    print(report.render())
    if published is not None:
        print(f"BD ConverData: versión {published.version}" + ("" if published.changed else " (sin cambios)")
              + (f", antes {result.previous_version}" if result.previous_version and published.changed else ""))
    audit_event(connect, "catalog_build_finished", "builder", status="ok" if report.servers_ok else "error",
                objects=report.objects, servers_failed=sorted(report.servers_failed), version=result.version)
    return 0 if report.servers_ok else 1


def builder_hosts_refused(servers) -> str | None:
    """El inventario de la BD lo edita un administrador desde la web y el Builder entra a esos hosts con la cuenta del
    servicio. `CONVERDATA_BUILDER_HOSTS` (hosts o sufijos como `.banco.local`, separados por coma) limita a dónde puede
    ir; en qa y prod es obligatoria. Devuelve el motivo del rechazo, o None."""
    import re

    allowed = [h.strip().lower() for h in os.environ.get("CONVERDATA_BUILDER_HOSTS", "").split(",") if h.strip()]
    if not allowed:
        if os.environ.get("CONVERDATA_ENV", "dev").strip().lower() in ("qa", "prod"):
            return ("Define CONVERDATA_BUILDER_HOSTS con los servidores (o sufijos de dominio) a los que la tarea "
                    "puede conectarse con la cuenta del servicio")
        return None

    def permitted(host: str) -> bool:
        name = re.split(r"[,\\:]", (host or "").strip().lower())[0]  # sin puerto ni instancia
        return any(name == a or (a.startswith(".") and name.endswith(a)) for a in allowed)

    outside = sorted(s.id for s in servers if not permitted(s.host))
    return (f"Servidores del inventario fuera de CONVERDATA_BUILDER_HOSTS: {', '.join(outside)}. No se conecta a "
            "ninguno hasta que se corrija el inventario o la lista") if outside else None


def eval_discovery(args) -> int:
    from pathlib import Path

    from converdata.evaluation.discovery_eval import evaluate, load_cases

    if args.db and args.knowledge:
        raise SystemExit("--knowledge se usa con el catálogo de --root, sin --db")
    if args.db:
        service = build_service_from_db(db_connect(), settings_path=Path(args.root) / "config" / "settings.yaml",
                                        models_path=args.models)
    elif args.knowledge:
        service = build_service_with_knowledge(args.root, args.knowledge, models_path=args.models)
    else:
        service = build_service(args.root, models_path=args.models)
    apply_patterns(service, args.patterns)
    report = evaluate(service, load_cases(args.cases or Path(args.root) / "eval" / "discovery.yaml"))
    print(report.render())
    if args.min_hit3 is not None and report.metrics["hit@3"] < args.min_hit3:
        return 1
    return 0


def eval_gate(args) -> int:
    """Sale con 0 solo si todas las suites aprueban en todos los catálogos."""
    from converdata.evaluation import gate
    from converdata.evaluation.discovery_eval import load_cases

    roots = args.root or list(DEFAULT_GATE_ROOTS)
    if args.cases and len(roots) > 1:
        raise SystemExit("--cases solo se puede usar con un único --root")
    if args.db and (not args.root or len(roots) > 1):
        raise SystemExit("--db necesita un único --root, que aporta los casos, la línea base y los umbrales")
    if args.db and args.write_baseline:
        raise SystemExit("La línea base se escribe con el catálogo del directorio, sin --db")
    suites = GATE_SUITES if args.suites == "all" else tuple(x.strip() for x in args.suites.split(",") if x.strip())
    approved = True
    for root in roots:
        root = Path(root)
        if args.db:
            service = build_service_from_db(db_connect(), settings_path=root / "config" / "settings.yaml",
                                            models_path=args.models)
        else:
            service = build_service(root, models_path=args.models)
        cases = load_cases(args.cases or root / "eval" / "discovery.yaml")
        llm = bool(args.models)
        report, quality = gate.run_gate(service, cases, root=root, llm=llm, thresholds=gate.load_thresholds(root),
                                        baseline=None if args.write_baseline else gate.load_baseline(root), suites=suites)
        print(report.render())
        if args.write_baseline and quality is not None:
            print(f"Línea base escrita en {gate.write_baseline(root, gate.baseline_from(quality))}")
        if args.out:
            json_path, md_path = gate.write_reports(report, args.out)
            print(f"Evidencia: {json_path} · {md_path}")
        print()
        approved = approved and report.ok
    return 0 if approved else 1


def audit_verify(args) -> int:
    from converdata.audit.chain import verify_directory

    if args.db:
        from converdata.audit.sqlserver import SqlServerAuditSink

        report = SqlServerAuditSink(db_connect()).verify()
        check = report.files[0]
        print(f"Auditoría en la BD ConverData: {check.rows} registros")
        for error in check.errors:
            print(f"  ERROR: {error}")
        print("La cuenta solo puede insertar y leer: íntegra" if report.ok else "NO APTA PARA PRODUCCIÓN")
        return 0 if report.ok else 1
    report = verify_directory(args.dir)
    print(report.render())
    return 0 if report.ok else 1


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
    """F16-CA2: cada rol devuelve salida estructurada parseable."""
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
            out = gw.chat(role).with_structured_output(Ping).invoke([HumanMessage(question)])
            ok, detail, label = isinstance(out, Ping), f"intent={getattr(out, 'intent', '?')}", gw.labels[role]
        except Exception as exc:  # se informa y se sigue con el resto de roles
            ok, detail, label = False, f"{type(exc).__name__}: {str(exc)[:160]}", gw.config.roles[role].model
        failures += not ok
        print(f"{'OK ' if ok else 'ERR'} {role:<8} {label:<60} {int((time.perf_counter() - t0) * 1000):>6} ms  {detail}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
