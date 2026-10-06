"""
Busca papers en Semantic Scholar (https://www.semanticscholar.org), una base
académica gratuita e independiente de OpenAlex, del Allen Institute for AI.
Se usa como segunda fuente para encontrar más papers y, sobre todo, para los
que ya trajo OpenAlex: cuando su PDF de acceso abierto está bloqueado,
Semantic Scholar a veces indexa un enlace distinto (otro repositorio) que sí
funciona.

Importante: esto NO evade bloqueos de copyright. Solo busca copias de acceso
abierto alternativas y legales (otro repositorio que sí autoriza la
descarga). Si ninguna fuente tiene una copia accesible, el paper queda
marcado como bloqueado para que se revise a mano (ver revisar_acceso_pdf).

Sin API key el límite es bajo y compartido entre todos los usuarios sin key
(suele alcanzar para este proyecto, pero con 429 "Too Many Requests"
frecuentes bajo carga). Pide una gratis en
https://www.semanticscholar.org/product/api#api-key-form y ponla en
SEMANTIC_SCHOLAR_API_KEY (config.py) para una cuota propia más alta.
"""

import re
import time

import requests

import config

SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
BULK_URL = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"
DOI_URL = "https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}"
CAMPOS = "title,year,abstract,externalIds,citationCount,isOpenAccess,openAccessPdf,venue"


def _doi_pelado(doi):
    """OpenAlex (y la base de datos del proyecto) guardan el DOI como
    'https://doi.org/10.xxxx'; Semantic Scholar necesita el DOI sin ese
    prefijo."""
    if not doi:
        return None
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.I)


def _cabeceras(api_key):
    return {"x-api-key": api_key} if api_key else {}


# Tope a cuánto se espera por un 429, aunque el servidor pida más en
# "Retry-After": si la cuota está realmente agotada puede pedir minutos u
# horas, y dormir eso bloquearía el script por mucho tiempo. Si pide más que
# esto, se da por perdida esa solicitud de una vez.
MAX_ESPERA_S = 30


def _solicitar(url, params, api_key, timeout=30, reintentos=3):
    """GET con reintentos: Semantic Scholar devuelve 429 seguido cuando
    muchas personas comparten la misma cuota sin API key."""
    for intento in range(1, reintentos + 1):
        config.esperar_turno()
        try:
            resp = requests.get(url, params=params, headers=_cabeceras(api_key), timeout=timeout)
        except requests.RequestException as exc:
            print(f"  [aviso] Semantic Scholar falló: {exc}")
            return None
        if resp.status_code == 429:
            espera = int(resp.headers.get("Retry-After", 5 * intento))
            if espera > MAX_ESPERA_S:
                print(f"  [aviso] Semantic Scholar pide esperar {espera}s; se omite esta solicitud "
                      "en vez de esperar tanto")
                return None
            if intento < reintentos:
                print(f"  [aviso] Semantic Scholar saturado (429), reintentando en {espera}s...")
                time.sleep(espera)
                continue
            print("  [aviso] Semantic Scholar sigue saturado; se omite esta solicitud")
            return None
        try:
            resp.raise_for_status()
        except requests.RequestException as exc:
            print(f"  [aviso] Semantic Scholar falló: {exc}")
            return None
        return resp.json()
    return None


def parse_result(record, matched_query):
    pdf = record.get("openAccessPdf") or {}
    doi_pelado = (record.get("externalIds") or {}).get("DOI")
    return {
        "openalex_id": None,
        # Mismo formato que usa OpenAlex (y la base de datos del proyecto),
        # para que un paper encontrado por las dos plataformas se fusione
        # bien en fusionar_por_doi en vez de quedar duplicado.
        "doi": f"https://doi.org/{doi_pelado}" if doi_pelado else None,
        "title": record.get("title"),
        "year": record.get("year"),
        "cited_by_count": record.get("citationCount") or 0,
        "is_oa": record.get("isOpenAccess", False),
        "oa_url": pdf.get("url"),
        "source": record.get("venue"),
        "abstract": record.get("abstract") or "",
        "matched_query": matched_query,
        "motor_busqueda": "semantic_scholar",
    }


def construir_consulta(query):
    """Traduce una query de config.PAPER_QUERIES (AND / OR / NOT, ver
    fetch_papers.py) a la sintaxis de la búsqueda "bulk" de Semantic Scholar:
    `+` = AND, `|` = OR, `-` = NOT, con cada bloque entre paréntesis."""
    query = query.replace("(", "").replace(")", "")
    expresiones = []
    for grupo in re.split(r"\s+AND\s+", query):
        grupo = grupo.strip()
        negar = re.match(r"(?i)^NOT\s+", grupo)
        if negar:
            grupo = grupo[negar.end():].strip()
        terminos = [t.strip() for t in re.split(r"\s+OR\s+", grupo) if t.strip()]
        expresion = "(" + " | ".join(terminos) + ")"
        expresiones.append(("-" if negar else "") + expresion)
    return " + ".join(expresiones)


def buscar_semantic_scholar(query, api_key, min_year=None, max_results=100):
    """Busca una query en Semantic Scholar y devuelve los `max_results` papers
    más citados. Usa la búsqueda "bulk" porque es la única que entiende
    operadores booleanos: la búsqueda por relevancia (SEARCH_URL) toma la
    query como una lista de palabras sueltas y con las cadenas del proyecto
    devuelve 0 resultados. La bulk no ordena por relevancia, así que se
    ordena por número de citas."""
    resultados = []
    token = None
    params_base = {"query": construir_consulta(query), "fields": CAMPOS, "sort": "citationCount:desc"}
    if min_year:
        params_base["year"] = f"{min_year}-"

    while len(resultados) < max_results:
        params = {**params_base, "token": token} if token else params_base
        data = _solicitar(BULK_URL, params, api_key)
        if data is None:
            break
        items = data.get("data") or []
        if not items:
            break
        for item in items:
            resultados.append(parse_result(item, query))
            if len(resultados) >= max_results:
                break
        token = data.get("token")
        if not token:
            break

    return resultados


def fetch_all(queries, api_key, min_year, max_results_per_query):
    """Corre todas las queries y deduplica por DOI. Los resultados sin DOI se
    descartan (la base del proyecto identifica cada paper por su DOI)."""
    seen = {}
    sin_doi = 0
    for q in queries:
        print(f"  Buscando en Semantic Scholar: {q!r}")
        rows = buscar_semantic_scholar(q, api_key, min_year, max_results_per_query)
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
        print(f"  ({sin_doi} resultados de Semantic Scholar sin DOI se descartaron)")
    return list(seen.values())


def fusionar_por_doi(principal, secundarios, nombre="Semantic Scholar"):
    """Combina dos listas de papers ya deduplicadas por DOI (una por fuente).
    Si un paper aparece en las dos, se queda con los datos de `principal`
    (OpenAlex: trae citas y abstract) y junta qué motores lo encontraron en
    `motor_busqueda`. `nombre` solo se usa en el mensaje de consola."""
    por_doi = {p["doi"]: p for p in principal if p.get("doi")}
    sin_doi = [p for p in principal if not p.get("doi")]
    agregados = 0
    for s in secundarios:
        doi = s.get("doi")
        if not doi:
            continue
        if doi in por_doi:
            existente = por_doi[doi]
            motores = set(existente.get("motor_busqueda", "openalex").split("; "))
            motores.add(s.get("motor_busqueda", "semantic_scholar"))
            existente["motor_busqueda"] = "; ".join(sorted(motores))
            for q in s["matched_query"].split("; "):
                if q not in existente["matched_query"]:
                    existente["matched_query"] += f"; {q}"
        else:
            por_doi[doi] = s
            agregados += 1
    print(f"  {agregados} papers nuevos que {nombre} encontró y las fuentes anteriores no")
    return list(por_doi.values()) + sin_doi


def verificar_pdf(url, timeout=10):
    """Intenta acceder al PDF sin descargarlo completo (HEAD y, si el
    servidor no lo soporta, un GET que se cierra de inmediato). Devuelve
    'disponible', 'bloqueado' (403/406/999, típico de editoriales que
    bloquean descargas automáticas) o 'desconocido' (timeout u otro error)."""
    if not url:
        return None
    cabeceras = {"User-Agent": "Mozilla/5.0 (compatible; investigación académica)"}
    try:
        resp = requests.head(url, headers=cabeceras, timeout=timeout, allow_redirects=True)
        if resp.status_code >= 400:
            resp = requests.get(url, headers=cabeceras, timeout=timeout, stream=True)
            resp.close()
        if resp.status_code in (403, 406, 999):
            return "bloqueado"
        return "disponible" if resp.status_code < 400 else "desconocido"
    except (requests.RequestException, UnicodeError):
        # UnicodeError: algunos servidores mandan el header Location en latin-1
        # (p. ej. "ó") y requests falla al seguir la redirección; no debe
        # tumbar toda la corrida por un solo paper.
        return "desconocido"


def _pdf_alterno_por_doi(doi, api_key):
    doi_pelado = _doi_pelado(doi)
    if not doi_pelado:
        return None
    data = _solicitar(DOI_URL.format(doi=doi_pelado), {"fields": "openAccessPdf"}, api_key, reintentos=1)
    if not data:
        return None
    return (data.get("openAccessPdf") or {}).get("url")


def _revisar_un_paper(paper, api_key, usar_alterna):
    url_original = paper.get("oa_url")
    estado = verificar_pdf(url_original)

    if estado == "disponible":
        paper["motor_pdf"] = paper.get("motor_busqueda", "openalex").split("; ")[0]
        paper["pdf_url"] = url_original
        paper["pdf_bloqueado"] = "no"
    else:
        alterna = (_pdf_alterno_por_doi(paper.get("doi"), api_key)
                   if usar_alterna and paper.get("doi") else None)
        if alterna and alterna != url_original:
            estado_alterna = verificar_pdf(alterna)
            paper["motor_pdf"] = "semantic_scholar"
            paper["pdf_url"] = alterna
            paper["pdf_bloqueado"] = "no" if estado_alterna == "disponible" else "si"
        elif url_original:
            paper["motor_pdf"] = paper.get("motor_busqueda", "openalex").split("; ")[0]
            paper["pdf_url"] = url_original
            paper["pdf_bloqueado"] = "si" if estado == "bloqueado" else None
        else:
            paper["motor_pdf"] = "ninguno"
            paper["pdf_url"] = None
            paper["pdf_bloqueado"] = None


def revisar_acceso_pdf(papers, api_key, max_papers=None, pausa=0.5, usar_alterna=True):
    """Revisa el acceso al PDF de los papers mejor rankeados (en orden), hasta
    reunir `max_papers` revisados con éxito. Para cada paper: revisa si el PDF
    que ya se tenía (de OpenAlex o Semantic Scholar) funciona; si está
    bloqueado o no existe y `usar_alterna` es True, busca en Semantic Scholar
    una copia alternativa (por DOI) y la revisa también. Con
    `usar_alterna=False` (por ejemplo, mientras Semantic Scholar está
    desactivado en config.py) no se hace ninguna solicitud a Semantic
    Scholar: solo se revisa el enlace original. Agrega a cada paper:
      - motor_pdf:      qué plataforma dio el enlace que se terminó usando
                         (openalex | semantic_scholar | ninguno)
      - pdf_url:        ese enlace
      - pdf_bloqueado:  'si' | 'no' | None (no se encontró ningún PDF)

    Si la revisión de un paper falla por cualquier error, sus tres campos
    quedan en None, no cuenta hacia `max_papers` y se pasa al siguiente: así
    un paper problemático no tumba la corrida ni deja un hueco en el
    resultado. Devuelve la lista de papers revisados con éxito.
    """
    revisados = []
    for paper in papers:
        if max_papers and len(revisados) >= max_papers:
            break
        try:
            _revisar_un_paper(paper, api_key, usar_alterna)
        except Exception as exc:
            print(f"  [aviso] no se pudo revisar el PDF de {paper.get('doi') or paper.get('title')!r} "
                  f"({type(exc).__name__}: {exc}); se deja en blanco y se revisa el siguiente")
            paper["motor_pdf"] = None
            paper["pdf_url"] = None
            paper["pdf_bloqueado"] = None
        else:
            revisados.append(paper)
            if len(revisados) % 25 == 0:
                print(f"  Revisado el acceso al PDF de {len(revisados)}/{max_papers or len(papers)} papers")
        time.sleep(pausa if api_key else max(pausa, 1.1))
    return revisados
