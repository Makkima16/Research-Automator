"""
Puntúa los papers recolectados para que el equipo revise primero los más
prometedores. La puntuación combina: citas (peso alto pero en escala
logarítmica, para que un paper con 500 citas no aplaste el resto),
recencia, si es de acceso abierto (más fácil de conseguir el texto
completo) y coincidencia de palabras clave en título/abstract.

Ajusta los pesos aquí si el equipo prefiere otro criterio.
"""

import math
import re

CITATION_WEIGHT = 2.0
RECENCY_WEIGHT = 0.2
OPEN_ACCESS_BONUS = 1.0
KEYWORD_WEIGHT = 1.5
BASE_YEAR = 2015


def palabras_clave(cadenas):
    """Términos de las cadenas de búsqueda (frases entre comillas enteras),
    sin operadores ni comillas sueltas. La usan main.py y servidor.py; antes
    cada uno armaba las keywords a su modo y main.py puntuaba también
    "AND"/"OR"/"NOT" como si fueran palabras del tema."""
    claves = []
    for cadena in cadenas:
        for frase, palabra in re.findall(r'"([^"]+)"|([^\s()"]+)', cadena):
            termino = frase or palabra
            if termino not in ("AND", "OR", "NOT") and termino not in claves:
                claves.append(termino)
    return claves


def score_paper(row, keywords):
    score = 0.0

    citations = row.get("cited_by_count") or 0
    score += math.log1p(citations) * CITATION_WEIGHT

    year = row.get("year")
    if year:
        score += max(0, (year - BASE_YEAR)) * RECENCY_WEIGHT

    if row.get("is_oa"):
        score += OPEN_ACCESS_BONUS

    text = f"{row.get('title') or ''} {row.get('abstract') or ''}".lower()
    matches = sum(1 for kw in keywords if kw.lower() in text)
    score += matches * KEYWORD_WEIGHT

    return round(score, 3)


def rank_papers(rows, keywords):
    for row in rows:
        row["score"] = score_paper(row, keywords)
    return sorted(rows, key=lambda r: r["score"], reverse=True)