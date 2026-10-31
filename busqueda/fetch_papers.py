"""
Recolecta papers académicos desde OpenAlex (https://openalex.org), un índice
abierto y gratuito con más de 270 millones de trabajos científicos. Funciona
sin key (con el "polite pool" vía mailto); con OPENALEX_API_KEY en ../.env se
usa una cuota propia y se evita el HTTP 429 del presupuesto compartido.

Las queries (config.PAPER_QUERIES) se escriben con una sintaxis booleana
simple, como en la búsqueda avanzada de ScienceDirect:

    "frase exacta" OR otro término AND tercer término AND NOT "excluir esto"

- AND / OR / NOT van en mayúsculas, separados por espacios.
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

Dos decisiones medidas contra el banco de pruebas `pruebas/cadenas/amplitud.py`
(8 temas, 37 cadenas, juez GPT-5.5 sobre los primeros títulos):
- Las comillas se ignoran al traducir (cada frase se manda como palabras
  sueltas): encontró de un 15 % a nueve veces más papers con la misma
  precisión (0,67 estricta / 0,99 laxa contra 0,66 / 0,97 con frase exacta).
- Si la búsqueda en título y abstract trae menos de UMBRAL_RESCATE_FULLTEXT
  resultados, se aplican dos rescates y se fusiona lo nuevo: primero cada par
  de grupos AND (con 3 o más grupos; la variante de mejor precisión medida:
  0,73 estricta) y después el texto completo (default.search), que rescata
  cadenas que devolvían 0 resultados; los papers que agrega están relacionados
  con el tema (laxa 0,98), aunque no todos lo tratan de frente (estricta 0,21).
"""

import re
import time

import requests

import config
import limites_motores

OPENALEX_URL = "https://api.openalex.org/works"


def construir_filtro(query):
    """Traduce una query en la sintaxis AND/OR/NOT de arriba al filtro real
    de OpenAlex (`title_and_abstract.search`, con comas/pipes/! estables).
    Las comillas de las frases exactas se quitan: medido en el banco de
    pruebas, buscar las palabras por separado encuentra más papers sin perder
    precisión (ver el docstring del módulo)."""
    query = query.replace("(", "").replace(")", "")
    clausulas = []
    for grupo in re.split(r"\s+AND\s+", query):
        grupo = grupo.strip()
        negar = re.match(r"(?i)^NOT\s+", grupo)
        if negar:
            grupo = grupo[negar.end():].strip()
        terminos = [t.strip().strip('"') for t in re.split(r"\s+OR\s+", grupo) if t.strip().strip('"')]
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


# Si la búsqueda en título y abstract trae menos resultados que esto, se repite
# en texto completo (default.search) y se fusionan los nuevos (ver el docstring
# del módulo). Con menos de esto, el usuario se queda casi sin papers.
UMBRAL_RESCATE_FULLTEXT = 15


def _paginar(filtro, query, email, max_results, per_page):
    """Corre una solicitud de OpenAlex (filtro ya armado) y pagina con cursor
    hasta max_results. Devuelve (resultados, error): error es True cuando la
    solicitud no se pudo completar (red o 429 persistente), para no confundir
    "0 resultados" con "no se pudo buscar"."""
    results = []
    cursor = "*"
    params = {
        "filter": filtro,
        "per-page": min(per_page, 200, max_results),
        "mailto": email,
    }
    if config.OPENALEX_API_KEY:
        params["api_key"] = config.OPENALEX_API_KEY

    while len(results) < max_results:
        params["cursor"] = cursor
        data = _solicitar(params, query)
        if data is None:
            return results, True
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

    return results, False


def _pares_de(efectiva):
    """[cada par de grupos AND positivos de la cadena] o [] si tiene menos de
    3 grupos. Medido en el banco de pruebas: cada par exige solo dos conceptos
    y encuentra más papers que la cadena completa con la MEJOR precisión de
    todas las variantes (0,73 estricta contra 0,66 de la cadena completa)."""
    grupos = limites_motores.parsear(efectiva)
    positivos = [t for negar, t in grupos if not negar]
    if len(positivos) < 3:
        return []
    return [limites_motores.unir([(False, positivos[i]), (False, positivos[j])])
            for i in range(len(positivos)) for j in range(i + 1, len(positivos))]


def fetch_openalex(query, email, min_year=None, max_results=100, per_page=200):
    """Busca una query en OpenAlex (título y abstract), paginando con cursor
    hasta max_results. Si trae menos de UMBRAL_RESCATE_FULLTEXT resultados,
    aplica dos rescates y fusiona lo nuevo, deduplicado por DOI (o id de
    OpenAlex si no tiene DOI):
    1. Pares de grupos (solo con 3 o más grupos AND): cada par es más preciso
       que el texto completo (ver _pares_de).
    2. Texto completo (default.search): lo más amplio; rescata cadenas que
       devuelven 0 resultados en título y abstract."""
    efectiva, recortada = limites_motores.ajustar(query, "openalex", construir_filtro)
    if recortada:
        print(f"  [aviso] la cadena era demasiado larga para OpenAlex; se recortaron alternativas: {efectiva!r}")
    filtro = construir_filtro(efectiva)
    if min_year:
        filtro += f",from_publication_date:{min_year}-01-01"

    results, error = _paginar(filtro, query, email, max_results, per_page)
    if error or len(results) >= UMBRAL_RESCATE_FULLTEXT:
        return results
    base = len(results)

    vistos = {r["doi"] or r["openalex_id"] for r in results}
    por_pares = 0
    for par in _pares_de(efectiva):
        if len(results) >= max_results:
            break
        filtro_par = construir_filtro(par)
        if min_year:
            filtro_par += f",from_publication_date:{min_year}-01-01"
        extra, _ = _paginar(filtro_par, query, email, max_results, per_page)
        for row in extra:
            key = row["doi"] or row["openalex_id"]
            if key not in vistos:
                vistos.add(key)
                results.append(row)
                por_pares += 1
                if len(results) >= max_results:
                    break
        if len(results) >= UMBRAL_RESCATE_FULLTEXT:
            break

    por_fulltext = 0
    if len(results) < UMBRAL_RESCATE_FULLTEXT:
        filtro_fulltext = filtro.replace("title_and_abstract.search:", "default.search:")
        extra, _ = _paginar(filtro_fulltext, query, email, max_results, per_page)
        for row in extra:
            key = row["doi"] or row["openalex_id"]
            if key not in vistos:
                vistos.add(key)
                results.append(row)
                por_fulltext += 1
                if len(results) >= max_results:
                    break

    if por_pares or por_fulltext:
        detalle = []
        if por_pares:
            detalle.append(f"{por_pares} por pares de grupos")
        if por_fulltext:
            detalle.append(f"{por_fulltext} en el texto completo")
        print(f"  [aviso] {query!r} trajo solo {base} resultados en título y abstract; "
              f"se agregaron {' y '.join(detalle)}")
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