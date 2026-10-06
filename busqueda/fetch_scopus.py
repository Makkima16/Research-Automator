"""
Busca papers en Scopus (Elsevier) con su API oficial de búsqueda. Es una
tercera fuente, junto a OpenAlex y Semantic Scholar: indexa las revistas de
Elsevier y las de la mayoría de las demás editoriales, y trae el número de
citas.

Necesita una API key gratis en https://dev.elsevier.com (va en ../.env como
SCOPUS_API_KEY; ver config.py). Sin key, este módulo se salta la búsqueda con
un aviso. Se usa Scopus y no la búsqueda de ScienceDirect porque esa solo se
habilita para instituciones suscritas (con la key sola responde 401).

Las queries de config.PAPER_QUERIES usan la misma sintaxis que
fetch_papers.py (AND / OR / NOT). Aquí se traducen a la sintaxis de Scopus
agrupando cada bloque entre paréntesis, para que la precedencia sea la misma
(AND entre grupos, OR dentro de cada grupo), y se buscan en título, abstract
y palabras clave (TITLE-ABS-KEY).

Límites a tener en cuenta: sin suscripción la API devuelve como máximo 25
resultados por solicitud y no permite paginar más allá de ~5000 por consulta.
La búsqueda no entrega el abstract ni el enlace al PDF; por eso los papers de
Scopus que también están en OpenAlex conservan los de OpenAlex al fusionarse
(ver fusionar_por_doi).
"""

import re
import time

import requests

import config

SEARCH_URL = "https://api.elsevier.com/content/search/scopus"
MAX_COUNT = 25        # tope de resultados por solicitud
MAX_START = 5000      # la API no pagina más allá de este desplazamiento
MAX_ESPERA_S = 30     # tope de espera ante un 429 (ver fetch_papers.py)


def construir_query(query, min_year=None):
    """Traduce una query de config.PAPER_QUERIES a la sintaxis de Scopus,
    poniendo cada bloque entre paréntesis."""
    query = query.replace("(", "").replace(")", "")
    expresiones = []
    for grupo in re.split(r"\s+AND\s+", query):
        grupo = grupo.strip()
        negar = re.match(r"(?i)^NOT\s+", grupo)
        if negar:
            grupo = grupo[negar.end():].strip()
        terminos = [t.strip() for t in re.split(r"\s+OR\s+", grupo) if t.strip()]
        expresion = "(" + " OR ".join(terminos) + ")"
        # En Scopus el operador de exclusión es AND NOT
        expresiones.append(("AND NOT " if negar else "AND ") + expresion)
    consulta = "TITLE-ABS-KEY(" + " ".join(expresiones)[len("AND "):] + ")"
    if min_year:
        consulta += f" AND PUBYEAR > {min_year - 1}"
    return consulta


def _solicitar(params, api_key, reintentos=3):
    """GET con reintentos ante 429. Un 401/403 (clave inválida o sin permiso)
    no se reintenta: se avisa una vez y se devuelve None."""
    cabeceras = {"X-ELS-APIKey": api_key, "Accept": "application/json"}
    for intento in range(1, reintentos + 1):
        config.esperar_turno()
        try:
            resp = requests.get(SEARCH_URL, params=params, headers=cabeceras, timeout=30)
        except requests.RequestException as exc:
            print(f"  [aviso] Scopus falló: {exc}")
            return None
        if resp.status_code in (401, 403):
            print(f"  [aviso] Scopus rechazó la clave ({resp.status_code}); revisa SCOPUS_API_KEY")
            return None
        if resp.status_code == 429:
            espera = int(resp.headers.get("Retry-After", 5 * intento))
            if espera > MAX_ESPERA_S:
                print(f"  [aviso] Scopus pide esperar {espera}s; se omite esta solicitud")
                return None
            if intento < reintentos:
                print(f"  [aviso] Scopus saturado (429), reintentando en {espera}s...")
                time.sleep(espera)
                continue
            print("  [aviso] Scopus sigue saturado; se omite esta solicitud")
            return None
        try:
            resp.raise_for_status()
        except requests.RequestException as exc:
            print(f"  [aviso] Scopus falló: {exc}")
            return None
        return resp.json()
    return None


def _entero(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return 0


def parse_entry(entry, matched_query):
    doi = entry.get("prism:doi")
    doi_url = f"https://doi.org/{doi}" if doi else None
    es_oa = bool(entry.get("openaccessFlag"))
    return {
        "openalex_id": None,
        # Mismo formato que OpenAlex y Semantic Scholar, para fusionar por DOI
        "doi": doi_url,
        "title": entry.get("dc:title"),
        "year": _entero((entry.get("prism:coverDate") or "")[:4]) or None,
        "cited_by_count": _entero(entry.get("citedby-count")),
        "is_oa": es_oa,
        # Scopus no da el enlace al PDF: si es de acceso abierto, queda el DOI
        "oa_url": doi_url if es_oa else None,
        "source": entry.get("prism:publicationName"),
        "abstract": "",
        "matched_query": matched_query,
        "motor_busqueda": "scopus",
    }


def buscar_scopus(query, api_key, min_year=None, max_results=100):
    """Busca una query en Scopus (por relevancia), paginando con `start`."""
    resultados = []
    start = 0
    params_base = {"query": construir_query(query, min_year), "count": min(MAX_COUNT, max_results),
                   "sort": "relevancy"}

    while len(resultados) < max_results and start < MAX_START:
        data = _solicitar({**params_base, "start": start}, api_key)
        if data is None:
            break
        busqueda = data.get("search-results") or {}
        # Una búsqueda sin resultados devuelve una entrada con la clave "error"
        entradas = [e for e in (busqueda.get("entry") or []) if "error" not in e]
        if not entradas:
            break
        for entrada in entradas:
            resultados.append(parse_entry(entrada, query))
            if len(resultados) >= max_results:
                break
        start += len(entradas)
        if start >= _entero(busqueda.get("opensearch:totalResults")):
            break

    return resultados


def fetch_all(queries, api_key, min_year, max_results_per_query):
    """Corre todas las queries y deduplica por DOI. Los resultados sin DOI se
    descartan (la base del proyecto identifica cada paper por su DOI)."""
    if not api_key:
        print("  [aviso] Scopus sin SCOPUS_API_KEY; se omite esta fuente")
        return []
    seen = {}
    sin_doi = 0
    for q in queries:
        print(f"  Buscando en Scopus: {q!r}")
        rows = buscar_scopus(q, api_key, min_year, max_results_per_query)
        for row in rows:
            key = row["doi"]
            if not key:
                sin_doi += 1
                continue
            if key in seen:
                if q not in seen[key]["matched_query"]:
                    seen[key]["matched_query"] += f"; {q}"
            else:
                seen[key] = row
    if sin_doi:
        print(f"  ({sin_doi} resultados de Scopus sin DOI se descartaron)")
    return list(seen.values())
