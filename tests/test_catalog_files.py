"""Caracterización de la carga del catálogo desde YAML (F1, F23) antes de moverla al adaptador `FileCatalogStore` (OP-09 §Puertos que faltan).

Los resúmenes (hash) se calcularon con `load_catalog`/`load_knowledge` de `catalog.store` antes del cambio: el adaptador
debe devolver exactamente lo mismo que el código anterior.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from converdata.catalog.files import FileCatalogStore
from converdata.config import load_inventory

FIXTURES = Path(__file__).parent / "fixtures"

# (objetos, hash del catálogo, hash del conocimiento) calculados con el código previo al puerto
ESPERADO = {
    "bancos": (42, "bac2557b9636fc1e", "ee9be231cc240ed0"),
    "vbank": (7, "092be5a57666d5f9", "1c545beeb2f7335a"),
}


def _resumen(datos) -> str:
    return hashlib.sha256(json.dumps(datos, sort_keys=True).encode()).hexdigest()[:16]


@pytest.mark.parametrize("fixture", sorted(ESPERADO))
def test_el_adaptador_de_archivos_carga_los_fixtures_igual_que_antes(fixture):
    root = FIXTURES / fixture
    store = FileCatalogStore(root)
    catalog = store.load_catalog(load_inventory(root / "config" / "databases.yaml"))
    kb = store.load_knowledge()

    n, hash_catalogo, hash_conocimiento = ESPERADO[fixture]
    assert len(catalog.objects) == n
    assert _resumen([o.model_dump(mode="json") for o in sorted(catalog.objects, key=lambda o: o.id)]) == hash_catalogo
    conocimiento = {
        nombre: [x.model_dump(mode="json") for x in getattr(kb, nombre)]
        for nombre in ("rules", "lineage", "golden", "items", "entities")
    }
    assert _resumen(conocimiento) == hash_conocimiento


def test_un_yaml_invalido_falla_nombrando_el_archivo(tmp_path):
    (tmp_path / "catalog" / "dev").mkdir(parents=True)
    malo = tmp_path / "catalog" / "dev" / "dbo.Roto.yaml"
    malo.write_text("id: 1\nextra_inventado: true\n", encoding="utf-8")
    inventario = load_inventory(FIXTURES / "vbank" / "config" / "databases.yaml")

    with pytest.raises(ValueError, match="dbo.Roto.yaml"):
        FileCatalogStore(tmp_path).load_catalog(inventario)


def test_un_directorio_sin_catalogo_ni_conocimiento_carga_vacio(tmp_path):
    store = FileCatalogStore(tmp_path)
    inventario = load_inventory(FIXTURES / "vbank" / "config" / "databases.yaml")

    assert store.load_catalog(inventario).objects == []
    assert store.load_knowledge().all_items() == []
