"""Motor de deteccion de huecos.

"Tienes un auto pero ninguna poliza asociada." Esto vale mas que un
recordatorio, porque avisa de lo que el usuario NO sabe que le falta, que es
justo el punto ciego de cualquier sistema de este tipo.
"""

from __future__ import annotations

import logging

from ..registry import registry
from ..scoping import use_household

logger = logging.getLogger(__name__)


def run_all(household) -> list:
    findings = []
    with use_household(household):
        for check in registry.checks.values():
            try:
                findings.extend(check.run(household) or [])
            except Exception:
                logger.exception("Fallo el check %s", check.key)
    order = {"critical": 0, "high": 1, "normal": 2, "low": 3}
    return sorted(findings, key=lambda f: order.get(f.severity, 9))
