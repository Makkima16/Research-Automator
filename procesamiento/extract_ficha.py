"""
Arma una "ficha" por paper: un resumen con lo más importante, a partir de
solo cinco piezas del paper en vez del texto completo:

    abstract · penúltimo y último párrafo de la introducción · conclusiones · tablas

Flujo por paper:
1. Estructura (tabla `estructuras`): Europe PMC si el paper está ahí (XML
   gratis) y, si no, su PDF de acceso abierto leído con Nemotron Parse
   (lento, por eso el resultado se guarda y no se repite). Los papers sin PDF accesible quedan con ficha "parcial": solo el
   abstract que ya está en la base.
2. Ficha (tabla `fichas`): Nemotron (NVIDIA) lee esas piezas, varios
   papers por solicitud, y devuelve resumen, objetivo, conclusiones, hallazgos
   clave y qué aporta cada tabla. Es incremental: si las piezas no cambiaron,
   no se vuelve a llamar al modelo.

    python extract_ficha.py --top 20 --tema "biochar para mejorar suelos ácidos"
    python extract_ficha.py --forzar
"""

import argparse
import hashlib
import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit
from xml.etree.ElementTree import ParseError

import requests
from pydantic import BaseModel, Field, ValidationError

import config_proc as config  # noqa: F401  (primero: agrega ../busqueda a la ruta de importación)
import completar_abstracts
import database_proc as database
import lectura_pdf
import llm_nvidia
from llm_nvidia import ErrorFatal

EUROPEPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
OPENALEX = "https://api.openalex.org/works"
CABECERAS = {"User-Agent": f"Mozilla/5.0 (proyecto academico Selema; mailto:{config.CONTACT_EMAIL})"}
PAUSA_S = 0.3
MIN_PALABRAS_ABSTRACT = 30     # menos que esto no es un abstract


def _get(url, **kwargs):
    return requests.get(url, headers=CABECERAS, timeout=60, **kwargs)


UNPAYWALL = "https://api.unpaywall.org/v2"
RE_META_PDF = re.compile(r"<meta[^>]+?(?:name|property)=[\"']citation_pdf_url[\"'][^>]*?content=[\"']([^\"']+)[\"']"
                         r"|<meta[^>]+?content=[\"']([^\"']+)[\"'][^>]*?(?:name|property)=[\"']citation_pdf_url[\"']", re.I)


def _json(url, **params):
    try:
        resp = _get(url, params=params)
        return resp.json() if resp.status_code == 200 else None
    except (requests.RequestException, ValueError):
        return None


def _doi_pelado(doi):
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", doi or "").strip()


def enlaces_candidatos(paper):
    """Enlaces donde puede estar el PDF, uno a uno y sin repetidos (las
    consultas a OpenAlex y Unpaywall solo se hacen si los anteriores no
    sirvieron): el que ya registró la búsqueda, las ubicaciones abiertas de
    OpenAlex, las de Unpaywall y, al final, las páginas del paper, donde
    _pdf_de_pagina busca el enlace al PDF. Todo es acceso abierto."""
    vistos = set()

    def nuevos(urls):
        for url in urls:
            if url and url not in vistos:
                vistos.add(url)
                yield url

    yield from nuevos([paper["pdf_url"]])
    paginas = []
    if paper["openalex_id"]:
        datos = _json(f"{OPENALEX}/{paper['openalex_id'].rsplit('/', 1)[-1]}",
                      mailto=config.CONTACT_EMAIL, select="locations,best_oa_location")
        locs = [(datos or {}).get("best_oa_location") or {}] + ((datos or {}).get("locations") or [])
        yield from nuevos(loc.get("pdf_url") for loc in locs)
        paginas += [loc.get("landing_page_url") for loc in locs]
    doi = _doi_pelado(paper["doi"])
    if doi:
        datos = _json(f"{UNPAYWALL}/{doi}", email=config.CONTACT_EMAIL)
        locs = (datos or {}).get("oa_locations") or []
        yield from nuevos(loc.get("url_for_pdf") for loc in locs)
        paginas += [loc.get("url_for_landing_page") for loc in locs]
    yield from nuevos([paper["oa_url"]] + paginas)


def _pdf_de_pagina(resp):
    """Enlace al PDF que declara la página HTML del paper (meta citation_pdf_url), o None."""
    m = RE_META_PDF.search(resp.text[:200000])
    return urljoin(resp.url, html.unescape(m.group(1) or m.group(2))) if m else None


def _descargar_pdf(paper):
    """(bytes, url) del primer PDF de acceso abierto descargable, o (None, motivo)
    con por qué fallaron los enlaces probados."""
    motivos = []

    def intentar(url):
        try:
            resp = _get(url, allow_redirects=True)
        except requests.RequestException as exc:
            motivos.append(f"{type(exc).__name__} en {urlsplit(url).hostname}")
            return None
        if resp.status_code == 200 and resp.content.startswith(b"%PDF"):
            return resp.content
        if resp.status_code == 200 and "html" in resp.headers.get("content-type", ""):
            return resp                      # página del paper: puede declarar el enlace al PDF
        motivos.append(f"{resp.status_code} en {urlsplit(url).hostname}")
        return None

    for url in enlaces_candidatos(paper):
        encontrado = intentar(url)
        if isinstance(encontrado, bytes):
            return encontrado, url
        if encontrado is not None:           # HTML: se sigue el enlace de la página, una sola vez
            directo = _pdf_de_pagina(encontrado)
            if directo and directo != url:
                time.sleep(PAUSA_S)
                pdf = intentar(directo)
                if isinstance(pdf, bytes):
                    return pdf, directo
            motivos.append(f"HTML sin PDF en {urlsplit(url).hostname}")
        time.sleep(PAUSA_S)
    return None, "; ".join(dict.fromkeys(motivos)) or "sin enlaces"


SYSTEM_PROMPT = """Eres un investigador que prepara fichas de lectura rápida de papers científicos.

Te llegarán varios papers por solicitud, cada uno con un identificador (P1, P2...) y solo estas piezas:
el abstract, el penúltimo y el último párrafo de la introducción (donde los autores plantean el
problema y declaran su objetivo), las conclusiones, y los nombres de las tablas con los atributos (encabezados de columna) de cada una.
Algunas piezas pueden faltar: no las inventes.

Para CADA paper devuelve un elemento en `papers` con su `paper_ref` y estos campos, en español:
- es_relevante: false si el paper no tiene relación con el TEMA DE LA INVESTIGACIÓN (si no se da tema,
  true).
- resumen: 2 a 3 frases con lo esencial del estudio (qué se hizo y qué se encontró).
- objetivo: el objetivo que declaran los autores (se apoya en los últimos párrafos de la introducción);
  null si no está.
- conclusiones: hasta 5 conclusiones concretas, una por elemento, fieles al texto de las conclusiones
  (o del abstract si no hay conclusiones). Lista vacía si no hay de dónde sacarlas.
- hallazgos_clave: hasta 6 resultados o datos concretos y verificables en el texto (incluye cifras,
  unidades y comparaciones SOLO si aparecen en el texto dado). Lista vacía si no hay.
- tablas: una por cada tabla dada, con `nombre`, `atributos` (copiados tal cual) y `que_aporta`: una
  frase sobre qué información entrega la tabla, deducida SOLO de su nombre y sus atributos. No
  inventes valores de las tablas: no los conoces.

REGLAS
- Trata cada paper por separado: nunca mezcles datos de uno con otro.
- Usa solo lo que dicen las piezas. Si algo no aparece, déjalo en null o en lista vacía.
- Prioriza lo importante para quien decide qué papers leer completos: qué se probó, bajo qué condiciones
  y qué se concluyó."""


class TablaFicha(BaseModel):
    nombre: str
    atributos: list[str] = Field(default_factory=list)
    que_aporta: str | None = None


class FichaPaper(BaseModel):
    paper_ref: str
    es_relevante: bool = True
    resumen: str | None = None
    objetivo: str | None = None
    conclusiones: list[str] = Field(default_factory=list)
    hallazgos_clave: list[str] = Field(default_factory=list)
    tablas: list[TablaFicha] = Field(default_factory=list)


class FichasLote(BaseModel):
    papers: list[FichaPaper]


SISTEMA_CON_ESQUEMA = (SYSTEM_PROMPT + "\n\nResponde SOLO con un objeto JSON que cumpla este JSON Schema:\n"
                       + json.dumps(FichasLote.model_json_schema(), ensure_ascii=False, separators=(",", ":")))
# Si cambia el prompt o el esquema, las fichas guardadas se regeneran
VERSION_FICHA = hashlib.sha256(SISTEMA_CON_ESQUEMA.encode()).hexdigest()[:12]


def ahora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- estructura

def _xml_europepmc(doi):
    """(bytes del XML, url) del paper en Europe PMC, o (None, None)."""
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi or "")
    if not doi:
        return None, None
    base = EUROPEPMC
    resp = _get(f"{base}/search", params={"query": f'DOI:"{doi}"', "format": "json",
                                                          "resultType": "lite"})
    resp.raise_for_status()
    pmcid = next((r.get("pmcid") for r in resp.json().get("resultList", {}).get("result", [])
                  if r.get("pmcid") and r.get("isOpenAccess") == "Y"), None)
    if not pmcid:
        return None, None
    time.sleep(PAUSA_S)
    url = f"{base}/{pmcid}/fullTextXML"
    resp = _get(url)
    return (resp.content, url) if resp.status_code == 200 else (None, None)


def _guardar_estructura(conn, paper_id, estado, fuente=None, url=None, estructura=None, error=None):
    with conn:
        conn.execute("INSERT OR REPLACE INTO estructuras VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (paper_id, estado, fuente, url,
                      json.dumps(estructura, ensure_ascii=False) if estructura else None, error, ahora()))


def obtener_estructura(conn, paper, forzar=False):
    """Estructura del paper (dict) desde la caché o la fuente; None si no hay.
    Lanza lectura_pdf.ErrorLecturaPDF si fatal. Solo se buscan los papers de
    acceso abierto: no se intenta saltar muros de pago."""
    previa = conn.execute("SELECT * FROM estructuras WHERE paper_id = ?", (paper["paper_id"],)).fetchone()
    # Un PDF resuelto por Sci-Hub trae pdf_url aunque is_oa sea 0: se intenta igual
    sin_acceso = not paper["is_oa"] and not paper["pdf_url"]
    if previa and not forzar and previa["estado"] in ("ok", "no_disponible"):
        # Se reintentan los que antes no tenían de dónde leer (ahora puede haber pdf_url o más enlaces)
        if sin_acceso and previa["error"] != "sin PDF descargable" \
                or previa["error"] not in ("no es de acceso abierto", "sin PDF descargable"):
            return json.loads(previa["estructura_json"]) if previa["estructura_json"] else None
    if sin_acceso:
        _guardar_estructura(conn, paper["paper_id"], "no_disponible", error="no es de acceso abierto")
        return None
    try:
        xml, url = _xml_europepmc(paper["doi"])
        if xml:
            estructura = lectura_pdf.estructura_europepmc(xml, url)
        else:
            time.sleep(PAUSA_S)
            pdf, url = _descargar_pdf(paper)
            if not pdf:         # `url` trae aquí el motivo
                _guardar_estructura(conn, paper["paper_id"], "no_disponible", error=f"sin PDF descargable ({url})"[:300])
                return None
            estructura = lectura_pdf.estructura_hibrida(pdf, url, abstract_conocido=_tiene_abstract(paper["abstract"]))
    except lectura_pdf.ErrorLecturaPDF as exc:
        if exc.fatal:
            raise
        _guardar_estructura(conn, paper["paper_id"], "error", error=str(exc)[:300])
        return None
    except (requests.RequestException, ParseError) as exc:
        _guardar_estructura(conn, paper["paper_id"], "error", error=str(exc)[:300])
        return None
    _guardar_estructura(conn, paper["paper_id"], "ok", estructura["fuente"], url, estructura)
    return estructura


# --------------------------------------------------------------------- ficha

def _tiene_abstract(texto):
    return len((texto or "").split()) >= MIN_PALABRAS_ABSTRACT


def texto_paper(paper, estructura):
    estructura = estructura or {}
    abstract = estructura.get("abstract") or paper["abstract"] or ""
    partes = [f"Título: {paper['title']}", f"Abstract: {abstract[:config.MAX_CARACTERES_ABSTRACT]}"]
    if estructura.get("intro_penultimo_parrafo"):
        partes.append(f"Penúltimo párrafo de la introducción: {estructura['intro_penultimo_parrafo']}")
    if estructura.get("intro_ultimo_parrafo"):
        partes.append(f"Último párrafo de la introducción: {estructura['intro_ultimo_parrafo']}")
    if estructura.get("conclusion"):
        partes.append(f"Conclusiones: {estructura['conclusion']}")
    for n, t in enumerate(estructura.get("tablas") or [], 1):
        partes.append(f"Tabla {n}: {t['nombre']} | atributos: {'; '.join(t['atributos']) or '(no detectados)'}")
    return "\n".join(partes)


def _cobertura(estructura):
    return "completa" if estructura and (estructura.get("conclusion") or estructura.get("intro_ultimo_parrafo")
                                         or estructura.get("tablas")) else "parcial"


def _hash(paper, estructura):
    return hashlib.sha256(f"{texto_paper(paper, estructura)}\n{VERSION_FICHA}".encode()).hexdigest()


def _tokens(texto):
    return len(texto) // 4


def armar_lotes(items):
    fijo = _tokens(SISTEMA_CON_ESQUEMA) + 300
    lotes, actual, usados = [], [], fijo
    for item in items:
        costo = _tokens(item["texto"]) + 20
        if actual and (len(actual) >= config.PAPERS_POR_LOTE_FICHA or usados + costo > config.MAX_TOKENS_ENTRADA_FICHA):
            lotes.append(actual)
            actual, usados = [], fijo
        actual.append(item)
        usados += costo
    if actual:
        lotes.append(actual)
    return lotes


def parsear_respuesta(texto):
    texto = texto.strip()
    if texto.startswith("```"):
        texto = texto.split("\n", 1)[1].rsplit("```", 1)[0]
    papers = []
    for p in json.loads(texto).get("papers", []):
        try:
            papers.append(FichaPaper.model_validate(p))
        except ValidationError:
            continue
    return {p.paper_ref.strip(): p for p in papers}


def llamar_llm(lote, tema):
    cabecera = f"TEMA DE LA INVESTIGACIÓN: {tema}\n\n" if tema else ""
    mensaje = cabecera + "\n\n".join(f"=== {ref} ===\n{item['texto']}" for ref, item in lote.items())
    return parsear_respuesta(llm_nvidia.chat_json(SISTEMA_CON_ESQUEMA, mensaje)), config.NVIDIA_MODELO


def _guardar_ficha(conn, paper_id, estado, cobertura, modelo, texto_hash, ficha=None, error=None):
    with conn:
        conn.execute("INSERT OR REPLACE INTO fichas VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (paper_id, estado, cobertura, modelo, texto_hash,
                      json.dumps(ficha, ensure_ascii=False) if ficha is not None else None, error, ahora()))


def _completar_abstracts(conn, papers, reportar):
    """Pide por DOI el abstract de los papers que no lo tienen (ver
    busqueda/completar_abstracts.py), lo guarda en la base y devuelve los
    papers con el abstract ya puesto."""
    faltan = [d for d in map(dict, papers) if completar_abstracts.necesita_abstract(d)]
    if not faltan:
        return papers
    reportar(f"{len(faltan)} papers sin abstract; buscándolo por DOI…")
    n = completar_abstracts.completar(faltan)
    nuevos = {p["paper_id"]: p["abstract"] for p in faltan if completar_abstracts.tiene_abstract(p["abstract"])}
    with conn:
        conn.executemany("UPDATE papers SET abstract = ? WHERE paper_id = ?",
                         [(abstract, pid) for pid, abstract in nuevos.items()])
    reportar(f"  {n} abstracts completados.")
    return [conn.execute("SELECT * FROM papers WHERE paper_id = ?", (p["paper_id"],)).fetchone()
            if p["paper_id"] in nuevos else p for p in papers]


def procesar(conn, paper_ids=None, top=None, tema="", forzar=False, avance=None, al_terminar_paper=None,
             relanzar_fatal=False):
    """Genera las fichas de `paper_ids` (o de los `top` mejores del ranking).
    Devuelve {estado: nº de papers}. `avance(msg)` recibe cada línea de progreso;
    `al_terminar_paper(paper, estado)` se llama una vez por paper resuelto.
    Con `relanzar_fatal`, un error irrecuperable se vuelve a lanzar después de
    avisar (lo ya guardado se conserva)."""
    def reportar(msg):
        print(msg)
        if avance:
            avance(msg)

    def terminado(paper, estado):
        conteo[estado] = conteo.get(estado, 0) + 1
        if al_terminar_paper:
            al_terminar_paper(paper, estado)

    columnas = "paper_id, title, abstract, doi, openalex_id, oa_url, pdf_url, is_oa"
    if paper_ids:
        marcadores = ", ".join("?" for _ in paper_ids)
        papers = conn.execute(f"SELECT {columnas} FROM papers WHERE paper_id IN ({marcadores})", paper_ids).fetchall()
    else:
        papers = conn.execute(f"SELECT {columnas} FROM papers ORDER BY score DESC LIMIT ?", (top or 20,)).fetchall()
    conteo = {}
    if not papers:
        reportar("No hay papers en la base.")
        return conteo

    papers = _completar_abstracts(conn, papers, reportar)

    pendientes = []
    try:
        reportar(f"Leyendo la estructura de {len(papers)} papers (abstract, introducción, conclusiones, tablas)…")
        for n, paper in enumerate(papers, 1):
            estructura = obtener_estructura(conn, paper, forzar)
            cobertura = _cobertura(estructura)
            texto_hash = _hash(paper, estructura)
            previa = conn.execute("SELECT * FROM fichas WHERE paper_id = ?", (paper["paper_id"],)).fetchone()
            if not forzar and previa and previa["texto_hash"] == texto_hash and previa["estado"] != "error":
                terminado(paper, "cache")
            elif cobertura == "parcial" and not _tiene_abstract((estructura or {}).get("abstract") or paper["abstract"]):
                _guardar_ficha(conn, paper["paper_id"], "sin_abstract", cobertura, None, texto_hash)
                terminado(paper, "sin_abstract")
            else:
                pendientes.append({"paper": paper, "estructura": estructura, "cobertura": cobertura,
                                   "hash": texto_hash, "texto": texto_paper(paper, estructura)})
            reportar(f"  [{n}/{len(papers)}] {(estructura or {}).get('fuente') or 'solo abstract':<22} "
                     f"{(paper['title'] or '')[:70]}")
    except (lectura_pdf.ErrorLecturaPDF, ErrorFatal) as exc:
        reportar(f"Deteniendo: {exc}")
        if relanzar_fatal:
            raise
        return conteo

    lotes = armar_lotes(pendientes)
    reportar(f"{conteo.get('cache', 0)} fichas ya hechas; {len(pendientes)} por generar en {len(lotes)} solicitudes.")
    for inicio in range(0, len(lotes), config.HILOS_LOTES_FICHA):
        grupo = list(enumerate(lotes[inicio:inicio + config.HILOS_LOTES_FICHA], inicio + 1))
        for n, lote in grupo:
            reportar(f"Lote {n}/{len(lotes)}…")
        # Las llamadas al LLM van en paralelo; lo demás (base de datos, avance) se hace aquí, en orden
        with ThreadPoolExecutor(len(grupo)) as pool:
            futuros = [(n, lote, pool.submit(llamar_llm, {f"P{i}": item for i, item in enumerate(lote, 1)}, tema))
                       for n, lote in grupo]
        for n, lote, futuro in futuros:
            por_ref = {f"P{i}": item for i, item in enumerate(lote, 1)}
            try:
                resultados, modelo = futuro.result()
            except ErrorFatal as exc:
                reportar(f"Deteniendo: {exc}")
                if relanzar_fatal:
                    raise
                return conteo
            except Exception as exc:
                for item in lote:
                    _guardar_ficha(conn, item["paper"]["paper_id"], "error", item["cobertura"], None, item["hash"],
                                   error=str(exc)[:300])
                    terminado(item["paper"], "error")
                reportar(f"  -> lote fallido: {str(exc)[:150]}")
                continue
            for ref, item in por_ref.items():
                ficha, paper = resultados.get(ref), item["paper"]
                if ficha is None:
                    _guardar_ficha(conn, paper["paper_id"], "error", item["cobertura"], modelo, item["hash"],
                                   error="el modelo no devolvió este paper en el lote")
                    estado = "error"
                else:
                    estado = "ok" if ficha.es_relevante else "no_relevante"
                    _guardar_ficha(conn, paper["paper_id"], estado, item["cobertura"], modelo, item["hash"],
                                   ficha.model_dump(mode="json", exclude={"paper_ref"}))
                reportar(f"  {estado:<13} {item['cobertura']:<8} {(paper['title'] or '')[:70]}")
                terminado(paper, estado)
        if inicio + config.HILOS_LOTES_FICHA < len(lotes):
            time.sleep(config.PAUSA_LLM_S)
    return conteo


def verificar_configuracion():
    faltan = []
    if not lectura_pdf.configurado():
        faltan.append("NVIDIA_PARSE_API_KEY")
    if not llm_nvidia.configurado():
        faltan.append("NVIDIA_API_KEY")
    if faltan:
        print("ERROR: falta en el archivo .env: " + "; ".join(faltan))
    return not faltan


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--top", type=int, default=config.MAX_PAPERS_TO_EXTRACT)
    parser.add_argument("--tema", default="", help="tema de la investigación (para marcar papers no relevantes)")
    parser.add_argument("--forzar", action="store_true", help="volver a leer y a generar aunque ya existan")
    args = parser.parse_args()
    if not verificar_configuracion():
        return
    conn = database.conectar(config.DB_PATH)
    print(f"\nResumen por paper: {procesar(conn, top=args.top, tema=args.tema, forzar=args.forzar)}")


if __name__ == "__main__":
    main()
