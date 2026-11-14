"""
Formato único de los DOI en todo el proyecto.

Los DOI no distinguen mayúsculas de minúsculas (10.1109/ICETAS... y
10.1109/icetas... son el mismo paper), pero cada motor los entrega a su
manera. La deduplicación compara cadenas exactas, así que todos se guardan
con el mismo formato: "https://doi.org/" + DOI en minúsculas. Ese formato es
también el `paper_id` de la base cuando el paper tiene DOI.
"""

import re

PREFIJO = "https://doi.org/"
_RE_PREFIJO = re.compile(r"^\s*(?:https?://)?(?:dx\.)?doi\.org/|^\s*doi:\s*", re.I)


def pelado(doi):
    """DOI sin prefijo y en minúsculas ("10.xxxx/yyyy"), o None si viene vacío."""
    if not doi:
        return None
    texto = _RE_PREFIJO.sub("", str(doi)).strip().lower()
    return texto or None


def normalizar(doi):
    """DOI como URL canónica ("https://doi.org/10.xxxx/yyyy"), o None."""
    texto = pelado(doi)
    return PREFIJO + texto if texto else None
