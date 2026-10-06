"""
Descarga el texto completo de los papers de acceso abierto y selecciona los
fragmentos con condiciones de proceso para el LLM (tabla `textos_completos`).

    python fetch_fulltext.py               # top config.MAX_PAPERS_TEXTO_COMPLETO del ranking
    python fetch_fulltext.py --top 50
    python fetch_fulltext.py --forzar      # volver a descargar aunque ya estén

Los abstracts casi nunca dan la temperatura, el tiempo, el pH o la composición
exactos; los métodos y resultados del paper sí. Fuentes, en orden:
1. Europe PMC (https://europepmc.org): texto completo en XML, por secciones,
   para los papers que están en PubMed Central. Es gratis y sin API key.
2. El PDF de acceso abierto (oa_url o los enlaces PDF que registra OpenAlex).
   Muchas editoriales bloquean las descargas automáticas (error 403): esos
   papers quedan como no_disponible.

El LLM no recibe el paper entero (no cabe en la cuota): recibe las frases con
más datos de proceso, priorizando la sección de métodos, hasta
config.MAX_CARACTERES_TEXTO_COMPLETO caracteres. Siguiente paso:
python extract_llm_insights.py (solo re-extrae los papers que ganaron texto).
"""

import argparse
import io
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

import config_proc as config
import database_proc as database

EUROPEPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
OPENALEX = "https://api.openalex.org/works"
CABECERAS = {"User-Agent": f"Mozilla/5.0 (proyecto academico Selema; mailto:{config.CONTACT_EMAIL})"}
PAUSA_S = 0.3

# Secciones que no aportan condiciones del estudio
SECCIONES_EXCLUIDAS = re.compile(
    r"acknowledg|funding|conflicts? of interest|author contributions?|references|abbreviations|"
    r"supplementary|data availability|ethics", re.I)
SECCION_METODOS = re.compile(r"method|material|experimental|procedure|processing|sampl|design", re.I)
SECCION_RESULTADOS = re.compile(r"result", re.I)
SECCION_INTRO = re.compile(r"introduc|background", re.I)

# Datos de proceso y composición: cada coincidencia suma puntos a la frase
PATRONES_NUMERICOS = [
    r"\d+(?:\.\d+)?\s*(?:°|º|˚)\s*C\b",                                  # temperatura
    r"\d+(?:\.\d+)?\s*(?:s|sec|seconds?|min|minutes?|h|hours?)\b",       # tiempo
    r"\bpH\s*(?:of|=|was|:)?\s*\d",                                      # pH
    r"\d+(?:\.\d+)?\s*%",                                                # porcentajes
    r"\d+(?:\.\d+)?\s*(?:days?|d)\b(?!\w)",                              # vida útil / almacenamiento
    r"\d+(?:\.\d+)?\s*(?:×|x)?\s*10\s*\^?\s*\d+\s*(?:cells|CFU|cfu)",     # recuentos
    r"\d+(?:\.\d+)?\s*(?:MPa|bar|rpm)\b",                                # presión, homogeneización
]
PALABRAS_CLAVE = re.compile(
    r"pasteuri|\bUHT\b|ultra[- ]?high|steriliz|heat[- ]?treat|homogeni|stored|storage|shelf[- ]?life|"
    r"\bfat\b|protein|lactose|total solids|somatic|\bbreed|holstein|jersey|pasture|grazing|confine|"
    r"\bA2\b|beta[- ]?casein|β-casein|probiotic|lactobacillus|fermentat|yog(h)?urt|hydrolys|lactase", re.I)
MAX_CARACTERES_FRASE = 400


def ahora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _get(url, **kwargs):
    return requests.get(url, headers=CABECERAS, timeout=60, **kwargs)


# ------------------------------------------------------------------- fuentes

def _texto_nodo(nodo):
    return re.sub(r"\s+", " ", " ".join(nodo.itertext())).strip()


def secciones_europepmc(doi):
    """[(título, texto)] del cuerpo del paper en Europe PMC, o None si no está."""
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi or "")
    if not doi:
        return None, None
    resp = _get(f"{EUROPEPMC}/search", params={"query": f'DOI:"{doi}"', "format": "json", "resultType": "lite"})
    resp.raise_for_status()
    resultados = resp.json().get("resultList", {}).get("result", [])
    pmcid = next((r.get("pmcid") for r in resultados if r.get("pmcid") and r.get("isOpenAccess") == "Y"), None)
    if not pmcid:
        return None, None
    time.sleep(PAUSA_S)
    url = f"{EUROPEPMC}/{pmcid}/fullTextXML"
    resp = _get(url)
    if resp.status_code != 200:
        return None, None
    cuerpo = ET.fromstring(resp.content).find(".//body")
    if cuerpo is None:
        return None, None
    secciones = []
    for sec in cuerpo.findall("./sec"):
        titulo = (sec.findtext("title") or "").strip()
        if SECCIONES_EXCLUIDAS.search(titulo):
            continue
        # Las subsecciones heredan el título de la sección (ej. "Materials and Methods")
        secciones.append((titulo, _texto_nodo(sec)))
    sueltos = " ".join(_texto_nodo(p) for p in cuerpo.findall("./p"))
    if sueltos:
        secciones.insert(0, ("", sueltos))
    return (secciones or None), url


def urls_pdf(paper):
    """Enlaces PDF candidatos: los que registra OpenAlex y el oa_url."""
    urls = []
    if paper["openalex_id"]:
        try:
            resp = _get(f"{OPENALEX}/{paper['openalex_id'].rsplit('/', 1)[-1]}",
                        params={"mailto": config.CONTACT_EMAIL, "select": "locations,best_oa_location"})
            if resp.ok:
                datos = resp.json()
                for loc in [datos.get("best_oa_location") or {}] + (datos.get("locations") or []):
                    if loc.get("pdf_url"):
                        urls.append(loc["pdf_url"])
        except requests.RequestException:
            pass
    if paper["oa_url"]:
        urls.append(paper["oa_url"])
    return list(dict.fromkeys(urls))  # sin repetidos, en orden


def secciones_pdf(paper):
    """[(título, texto)] a partir del primer PDF descargable, o None."""
    from pypdf import PdfReader

    for url in urls_pdf(paper):
        try:
            resp = _get(url, allow_redirects=True)
        except requests.RequestException:
            continue
        if resp.status_code != 200 or not resp.content.startswith(b"%PDF"):
            continue
        try:
            lector = PdfReader(io.BytesIO(resp.content))
            texto = "\n".join(pagina.extract_text() or "" for pagina in lector.pages)
        except Exception:
            continue
        # Sin estructura: se corta en "References" y se separan métodos/resultados por sus títulos
        texto = re.split(r"\n\s*(?:references|bibliography|literature cited)\s*\n", texto, flags=re.I)[0]
        texto = re.sub(r"-\n(?=[a-z])", "", texto)  # palabras cortadas al final de línea
        texto = re.sub(r"\s+", " ", texto)
        partes = re.split(r"(?i)\b((?:\d\.?\s*)?(?:materials? and methods?|methods|results(?: and discussion)?|"
                          r"discussion|conclusions?))\b(?=\s+[A-Z0-9])", texto)
        secciones, titulo = [], ""
        for i, parte in enumerate(partes):
            if i % 2 == 1:
                titulo = parte
            elif parte.strip():
                secciones.append((titulo, parte.strip()))
        if sum(len(t) for _, t in secciones) > 2000:
            return secciones, url
    return None, None


# ------------------------------------------------------------ fragmentos

def puntaje(frase, titulo):
    numericos = sum(len(re.findall(p, frase)) for p in PATRONES_NUMERICOS)
    if numericos == 0:
        return 0  # sin ningún dato numérico no aporta condiciones de proceso
    puntos = 2 * numericos + len(PALABRAS_CLAVE.findall(frase))
    if SECCION_METODOS.search(titulo):
        puntos *= 1.5
    elif SECCION_RESULTADOS.search(titulo):
        puntos *= 1.2
    elif SECCION_INTRO.search(titulo):
        puntos *= 0.5  # la introducción cita datos de otros estudios
    return puntos


def seleccionar_fragmentos(secciones, max_caracteres=config.MAX_CARACTERES_TEXTO_COMPLETO):
    """Las frases con más datos de proceso, en su orden original y marcadas
    con su sección, hasta `max_caracteres`."""
    frases = []
    for titulo, texto in secciones:
        for frase in re.split(r"(?<=[.!?])\s+(?=[A-Z(])", texto):
            frase = frase.strip()
            if len(frase) < 30:
                continue
            p = puntaje(frase, titulo)
            if p >= 3:
                frases.append((p, len(frases), titulo, frase[:MAX_CARACTERES_FRASE]))
    elegidas, usados = [], 0
    for p, orden, titulo, frase in sorted(frases, key=lambda f: -f[0]):
        if usados + len(frase) > max_caracteres:
            continue
        elegidas.append((orden, titulo, frase))
        usados += len(frase) + 1
    partes, titulo_actual = [], None
    for _, titulo, frase in sorted(elegidas):
        if titulo != titulo_actual:
            partes.append(f"[{titulo or 'texto'}]")
            titulo_actual = titulo
        partes.append(frase)
    return "\n".join(partes)


# ---------------------------------------------------------------- principal

def guardar(conn, paper_id, estado, fuente=None, url=None, texto=None, fragmentos=None, error=None):
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO textos_completos VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (paper_id, estado, fuente, url, texto, fragmentos, len(texto) if texto else None, error, ahora()),
        )


def procesar(conn, paper):
    try:
        secciones, url = secciones_europepmc(paper["doi"])
        fuente = "europepmc"
        if not secciones:
            time.sleep(PAUSA_S)
            secciones, url = secciones_pdf(paper)
            fuente = "pdf"
    except (requests.RequestException, ET.ParseError) as exc:
        guardar(conn, paper["paper_id"], "error", error=str(exc)[:300])
        return "error"
    if not secciones:
        guardar(conn, paper["paper_id"], "no_disponible")
        return "no_disponible"
    texto = "\n\n".join(f"{t}\n{x}" if t else x for t, x in secciones)
    guardar(conn, paper["paper_id"], "ok", fuente, url, texto, seleccionar_fragmentos(secciones))
    return f"ok_{fuente}"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--top", type=int, default=config.MAX_PAPERS_TEXTO_COMPLETO)
    parser.add_argument("--forzar", action="store_true", help="volver a descargar los ya procesados")
    args = parser.parse_args()

    conn = database.conectar(config.DB_PATH)
    papers = conn.execute(
        """SELECT p.paper_id, p.openalex_id, p.doi, p.oa_url, p.title, t.estado
           FROM papers p LEFT JOIN textos_completos t USING (paper_id)
           WHERE p.is_oa = 1 ORDER BY p.score DESC LIMIT ?""", (args.top,)).fetchall()
    pendientes = [p for p in papers if args.forzar or p["estado"] in (None, "error")]
    print(f"{len(papers)} papers de acceso abierto en el top {args.top}; {len(pendientes)} por descargar.")

    conteo = {}
    for n, paper in enumerate(pendientes, 1):
        estado = procesar(conn, paper)
        conteo[estado] = conteo.get(estado, 0) + 1
        print(f"  [{n}/{len(pendientes)}] {estado:<13} {(paper['title'] or '')[:80]}")
        time.sleep(PAUSA_S)

    print(f"\nResumen: {conteo}")
    total = conn.execute("SELECT estado, COUNT(*) FROM textos_completos GROUP BY estado").fetchall()
    print("En la base:", {r[0]: r[1] for r in total})
    print("Siguiente paso: python extract_llm_insights.py (re-extrae solo los papers con texto nuevo)")


if __name__ == "__main__":
    main()
