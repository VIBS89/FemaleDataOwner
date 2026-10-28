"""Contrato del puerto `CatalogStore` (OP-09 §Puertos que faltan, HU-06, HU-09).

La batería corre con cada adaptador. `sqlserver` queda declarado y se omite con motivo hasta tener SD-3 (S1-B);
entonces solo se le quita la marca de omisión, sin tocar los tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from converdata.builder import catalog_builder as cb
from converdata.catalog.files import FileCatalogStore
from converdata.config import load_inventory
from converdata.models.catalog import CatalogObject

FIXTURE = Path(__file__).parent / "fixtures" / "vbank"


def _almacen_de_archivos(tmp_path):
    return FileCatalogStore(tmp_path)


def _almacen_sqlserver(tmp_path):  # pragma: no cover - se activa en SD-3 (S1-B)
    raise NotImplementedError("adaptador sqlserver del catálogo: llega con HU-06")


ADAPTADORES = [
    pytest.param(_almacen_de_archivos, id="files"),
    pytest.param(_almacen_sqlserver, id="sqlserver", marks=pytest.mark.sqlserver),
]


@pytest.fixture(params=ADAPTADORES)
def almacen(request, tmp_path):
    return request.param(tmp_path)


@pytest.fixture
def inventario():
    return load_inventory(FIXTURE / "config" / "databases.yaml")


@pytest.fixture
def objetos(inventario):
    return FileCatalogStore(FIXTURE).load_catalog(inventario).objects


def _tabla_con_columnas(objetos) -> CatalogObject:
    return next(o for o in objetos if o.kind == "table" and o.columns)


def test_lo_guardado_se_carga_igual(almacen, inventario, objetos):
    almacen.save_catalog(inventario, objetos, [], [])

    cargado = almacen.load_catalog(inventario)

    esperado = {o.id: o.model_dump(mode="json") for o in objetos}
    assert {o.id: o.model_dump(mode="json") for o in cargado.objects} == esperado


def test_guardar_dos_veces_lo_mismo_no_reescribe_nada(almacen, inventario, objetos):
    """F1-CA2: sin cambios no se reescribe."""
    assert almacen.save_catalog(inventario, objetos, [], []) == len(objetos)
    assert almacen.save_catalog(inventario, objetos, [], []) == 0


def test_una_descripcion_humana_sobrevive_al_refresco(almacen, inventario, objetos):
    """F24-CA3 / HU-06: el refresco no pisa una edición `human`."""
    tabla = _tabla_con_columnas(objetos).model_copy(deep=True)
    tabla.description, tabla.description_source, tabla.reviewed = "Descripción del steward", "human", True
    almacen.save_catalog(inventario, [tabla], [], [])

    # el catálogo vuelve a extraerse de la BD con la estructura cambiada y una descripción generada
    nueva = tabla.model_copy(deep=True)
    nueva.schema_hash = "otro-hash"
    nueva.description, nueva.description_source, nueva.reviewed = "Texto generado por IA", "generated", False
    fusionada, _ = cb.merge_existing(nueva, almacen.load_existing().get(nueva.id))
    almacen.save_catalog(inventario, [fusionada], [], [])

    cargado = {o.id: o for o in almacen.load_catalog(inventario).objects}[tabla.id]
    assert (cargado.description, cargado.description_source, cargado.reviewed) == ("Descripción del steward", "human", True)


def test_un_objeto_que_ya_no_esta_en_la_bd_sale_del_catalogo(almacen, inventario, objetos):
    almacen.save_catalog(inventario, objetos, [], [])

    almacen.save_catalog(inventario, objetos[:-1], [], [])

    assert objetos[-1].id not in {o.id for o in almacen.load_catalog(inventario).objects}


def test_load_existing_indexa_por_id(almacen, inventario, objetos):
    almacen.save_catalog(inventario, objetos, [], [])

    assert set(almacen.load_existing()) == {o.id for o in objetos}


def test_un_almacen_vacio_no_tiene_objetos_ni_conocimiento(almacen, inventario):
    assert almacen.load_catalog(inventario).objects == []
    assert almacen.load_existing() == {}
    assert almacen.load_knowledge().all_items() == []


def test_el_modelo_rechaza_valores_de_datos(objetos):
    """F1, F17: el catálogo guarda metadatos; un campo de muestra de valores no existe ni se acepta."""
    datos = _tabla_con_columnas(objetos).model_dump(mode="json")
    datos["sample_values"] = ["00000000-0"]

    with pytest.raises(ValidationError):
        CatalogObject.model_validate(datos)
