"""
Ajusta cada cadena de búsqueda a los límites del motor al que se envía. El
usuario (y el LLM) escriben la cadena completa; aquí se recorta solo lo que no
cabe, sin que nadie tenga que pensar en esto.

Qué dice la documentación de cada motor (consultada el 2026-10-16):
- OpenAlex: la URL de la solicitud tiene un tope de ~4 KB (help.openalex.org,
  guía "Searching": las consultas booleanas largas deben partirse) y un filtro
  admite hasta 100 valores unidos con `|` (guía "Filtering").
- Scopus: sin tope explícito de largo ni de operadores, pero Elsevier
  recomienda no pasar de 50 operadores booleanos por consulta y avisó (2025)
  que su analizador puede rechazar consultas muy complejas por "ambiguas".
- Semantic Scholar (búsqueda bulk): la documentación de la API no publica tope
  de largo para `query`; se aplica el mismo tope prudente de URL.

Los topes de URL de Scopus y Semantic Scholar y el margen de OpenAlex NO son
cifras publicadas: son un valor conservador propio (MAX_QUERY_CODIFICADA).

Recorte: mientras no quepa, se quita la última alternativa (OR) del grupo AND
que más alternativas tenga, dejando siempre al menos una por grupo. Así se
pierden primero los sinónimos del final (los que el LLM puso de último son los
menos centrales) y se conservan todos los conceptos. Si aun así no cabe, se
descartan los grupos AND de atrás hacia adelante, conservando el primero.
"""

import re
from urllib.parse import quote_plus

# Largo máximo de la consulta ya traducida y codificada para URL. OpenAlex
# admite ~4096 en total; el resto lo ocupan cursor, mailto, per-page y fecha.
MAX_QUERY_CODIFICADA = 3000

LIMITES = {
    "openalex": {"max_alternativas_por_grupo": 100, "max_operadores": None},
    "scopus": {"max_alternativas_por_grupo": None, "max_operadores": 50},
    "semantic_scholar": {"max_alternativas_por_grupo": None, "max_operadores": None},
}


def parsear(query):
    """[(es_not, [términos])] a partir de una cadena AND / OR / NOT."""
    query = query.replace("(", "").replace(")", "")
    grupos = []
    for grupo in re.split(r"\s+AND\s+", query):
        grupo = grupo.strip()
        negar = re.match(r"(?i)^NOT\s+", grupo)
        if negar:
            grupo = grupo[negar.end():].strip()
        terminos = [t.strip() for t in re.split(r"\s+OR\s+", grupo) if t.strip()]
        if terminos:
            grupos.append((bool(negar), terminos))
    return grupos


def unir(grupos):
    return " AND ".join(("NOT " if negar else "") + " OR ".join(terminos) for negar, terminos in grupos)


def contar_operadores(grupos):
    return sum(len(terminos) - 1 for _, terminos in grupos) + max(len(grupos) - 1, 0)


def _cabe(grupos, motor, construir):
    limites = LIMITES[motor]
    if limites["max_operadores"] and contar_operadores(grupos) > limites["max_operadores"]:
        return False
    tope_or = limites["max_alternativas_por_grupo"]
    if tope_or and any(len(terminos) > tope_or for _, terminos in grupos):
        return False
    return len(quote_plus(construir(unir(grupos)))) <= MAX_QUERY_CODIFICADA


def ajustar(query, motor, construir):
    """Devuelve (query_ajustada, recortada). `construir(query)` es la función
    del motor que traduce la cadena a su sintaxis (se usa para medir el largo
    real que se enviará). `recortada` es True si hubo que quitar términos."""
    grupos = parsear(query)
    if not grupos or _cabe(grupos, motor, construir):
        return query, False
    grupos = [(negar, list(terminos)) for negar, terminos in grupos]
    while not _cabe(grupos, motor, construir):
        candidatos = [i for i, (negar, terminos) in enumerate(grupos) if not negar and len(terminos) > 1]
        if candidatos:
            i = max(candidatos, key=lambda k: len(grupos[k][1]))
            grupos[i][1].pop()
            continue
        # Cada grupo ya tiene una sola alternativa: quitar el último grupo (que no sea el primero)
        if len(grupos) > 1:
            grupos.pop()
            continue
        break
    return unir(grupos), True
