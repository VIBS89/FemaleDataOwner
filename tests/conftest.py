from pathlib import Path

import pytest

from converdata.bootstrap import build_service, user_with_databases
from situaciones import MARCAS, motivo_de_omision

FIXTURE = Path(__file__).parent / "fixtures" / "vbank"
ONBOARDING_Q = "Necesito encontrar el identificador único del cliente utilizado en procesos de onboarding digital."


@pytest.fixture
def service():
    return build_service(FIXTURE)


@pytest.fixture
def analyst(service):
    """Analista con acceso a las BDs del dominio clientes/onboarding y al DWH (no a RRHH)."""
    return user_with_databases(service, "analista", ["VBank_ING", "Onboarding", "DWH"])


@pytest.fixture
def rrhh_user(service):
    """Usuario que solo puede leer RRHH: no debe descubrir nada de VBank_ING (F14, F22-CA4)."""
    return user_with_databases(service, "rrhh", ["RRHH"], groups=["GG-RRHH"])


def pytest_collection_modifyitems(config, items):
    """OP-09: un test con marca de situación y sin su infraestructura queda omitido con el motivo, nunca en verde silencioso."""
    import os

    for item in items:
        for marca in MARCAS:
            if item.get_closest_marker(marca):
                motivo = motivo_de_omision(marca, os.environ)
                if motivo:
                    item.add_marker(pytest.mark.skip(reason=motivo))
