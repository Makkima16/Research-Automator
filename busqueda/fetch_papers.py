"""
Recolecta papers académicos desde OpenAlex (https://openalex.org), un índice
abierto y gratuito con más de 270 millones de trabajos científicos. No
requiere API key.

Las queries (config.PAPER_QUERIES) se escriben con una sintaxis booleana
simple, como en la búsqueda avanzada de ScienceDirect:

    "frase exacta" OR otro término AND tercer término AND NOT "excluir esto"

- AND / OR / NOT van en mayúsculas, separados por espacios.
- Las comillas marcan frase exacta; sin comillas, cada palabra se busca por
  separado (con su raíz: "digestibility" también encuentra "digestible").
- Los paréntesis son solo para que la leas más fácil: se ignoran al traducir
  la query (ver construir_filtro), así que no agregan ni quitan precedencia.
- Precedencia real: AND separa "grupos"; dentro de cada grupo, OR une
  alternativas. Es decir, `A OR B AND C OR D` se traduce a `(A OR B) AND (C
  OR D)`, nunca a `A OR (B AND C) OR D`.
- NOT solo admite un término o una frase (no una lista con OR adentro).

Por qué así: el parámetro `search=` de OpenAlex interpreta AND/OR/NOT de
forma inconsistente (la misma query a veces los respeta y a veces no,
verificado en vivo). El filtro `title_and_abstract.search:` sí es estable:
coma = AND entre cláusulas, `|` = OR dentro de una cláusula, `!` = NOT.
Esta función traduce la sintaxis de arriba a ese filtro.
"""

import re
import time

import requests

import config

OPENALEX_URL = "https://api.openalex.org/works"


def construir_filtro(query):
    """Traduce una query en la sintaxis AND/OR/NOT de arriba al filtro real
    de OpenAlex (`title_and_abstract.search`, con comas/pipes/! estables)."""
    query = query.replace("(", "").replace(")", "")
    clausulas = []
    for grupo in re.split(r"\s+AND\s+", query):
        grupo = grupo.strip()
        negar = re.match(r"(?i)^NOT\s+", grupo)
        if negar:
            grupo = grupo[negar.end():].strip()
        terminos = [t.strip() for t in re.split(r"\s+OR\s+", grupo) if t.strip()]
        valor = "|".join(terminos)
        if negar:
            valor = f"!{valor}"
        clausulas.append(f"title_and_abstract.search:{valor}")
    return ",".join(clausulas)


def reconstruct_abstract(inverted_index):
    """OpenAlex no entrega el abstract como texto plano (por temas de
    derechos de autor), sino como un 'índice invertido': {palabra: [posiciones]}.
    Esta función lo reconstruye a texto legible."""
    if not inverted_index:
        return ""
    max_pos = max(pos for positions in inverted_index.values() for pos in positions)
    words = [""] * (max_pos + 1)
    for word, positions in inverted_index.items():
        for pos in positions:
            words[pos] = word
    return " ".join(words)


def parse_openalex_work(work, matched_query):
    oa = work.get("open_access") or {}
    primary_location = work.get("primary_location") or {}
    source = (primary_location.get("source") or {}).get("display_name")
    return {
        "openalex_id": work.get("id"),
        "doi": work.get("doi"),
        "title": work.get("title"),
        "year": work.get("publication_year"),
        "cited_by_count": work.get("cited_by_count", 0),
        "is_oa": oa.get("is_oa", False),
        "oa_url": oa.get("oa_url"),
        "source": source,
        "abstract": reconstruct_abstract(work.get("abstract_inverted_index")),
        "matched_query": matched_query,
        "motor_busqueda": "openalex",
    }


# Tope a cuánto se espera por un 429, aunque el servidor pida más en
# "Retry-After": OpenAlex puede pedir miles de segundos (cuota de créditos
# agotada, no un simple "espera un poco"), y dormir eso bloquearía el script
# por horas. Si pide más que esto, se da por perdida esa búsqueda de una vez.
MAX_ESPERA_S = 30


def _solicitar(params, query, reintentos=3):
    """GET con reintentos: OpenAlex a veces devuelve 429 (saturado, sobre
    todo con mucho tráfico compartido) o fallas de red pasajeras."""
    for intento in range(1, reintentos + 1):
        config.esperar_turno()
        try:
            resp = requests.get(OPENALEX_URL, params=params, timeout=30)
        except requests.RequestException as exc:
            print(f"  [aviso] falló la solicitud para {query!r}: {exc}")
            return None
        if resp.status_code == 429:
            espera = int(resp.headers.get("Retry-After", 5 * intento))
            if espera > MAX_ESPERA_S:
                print(f"  [aviso] OpenAlex pide esperar {espera}s (cuota agotada, no un simple pico de "
                      f"tráfico); se omite esta búsqueda en vez de esperar tanto")
                return None
            if intento < reintentos:
                print(f"  [aviso] OpenAlex saturado (429), reintentando en {espera}s...")
                time.sleep(espera)
                continue
            print(f"  [aviso] OpenAlex sigue saturado (429) para {query!r}; se omite esta búsqueda")
            return None
        try:
            resp.raise_for_status()
        except requests.RequestException as exc:
            print(f"  [aviso] falló la solicitud para {query!r}: {exc}")
            return None
        return resp.json()
    return None


def fetch_openalex(query, email, min_year=None, max_results=100, per_page=200):
    """Busca una query en OpenAlex, paginando con cursor hasta max_results."""
    results = []
    cursor = "*"
    filtro = construir_filtro(query)
    if min_year:
        filtro += f",from_publication_date:{min_year}-01-01"
    params = {
        "filter": filtro,
        "per-page": min(per_page, 200, max_results),
        "mailto": email,
    }

    while len(results) < max_results:
        params["cursor"] = cursor
        data = _solicitar(params, query)
        if data is None:
            break
        page_results = data.get("results", [])
        if not page_results:
            break

        for work in page_results:
            results.append(parse_openalex_work(work, query))
            if len(results) >= max_results:
                break

        cursor = data.get("meta", {}).get("next_cursor")
        if not cursor:
            break

    return results


def fetch_all(queries, email, min_year, max_results_per_query):
    """Corre todas las queries y deduplica por DOI (o por id de OpenAlex si
    el paper no tiene DOI)."""
    seen = {}
    for q in queries:
        print(f"  Buscando en OpenAlex: {q!r}")
        rows = fetch_openalex(q, email, min_year, max_results_per_query)
        for row in rows:
            key = row["doi"] or row["openalex_id"]
            if key in seen:
                if q not in seen[key]["matched_query"]:
                    seen[key]["matched_query"] += f"; {q}"
            else:
                seen[key] = row
    return list(seen.values())