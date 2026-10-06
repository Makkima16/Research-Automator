"""
Sci-Hub como cuarto motor, con la librería `scihub` (pip install scihub).

Sci-Hub NO tiene búsqueda por palabras clave: solo resuelve un identificador
(DOI) al PDF del paper. Por eso este motor no recibe las cadenas de
config.PAPER_QUERIES como los otros tres, sino los papers que ellos ya
encontraron: para los que quedaron sin PDF accesible (sin enlace de acceso
abierto, o con el enlace bloqueado) pregunta a Sci-Hub por su DOI. Los que
están quedan con motor_pdf = "scihub", su enlace en pdf_url y "scihub" sumado
a motor_busqueda.

Adaptación de la librería (su única versión, 0.0.1, es de 2018 y declara
Python 3.3 a 3.6). Se importa bien en Python 3.12, pero su método fetch() ya
no sirve tal cual:
- su lista de mirrors (sci-hub.tw, sci-hub.cc…) está caída: aquí se
  reemplaza por config.SCIHUB_MIRRORS;
- solo busca el PDF en un <iframe>; los mirrors actuales también usan <embed>
  u <object>, a veces con ruta relativa (ver _enlace_pdf);
- hace un "ping" con timeout de 1 s, descarga el PDF entero y al fallar un
  mirror no vuelve a usarlo ni reinicia la lista: aquí solo se pide la página
  del paper y se saca el enlace, sin descargar el PDF;
- usa verify=False (por eso los scripts que la usan importan urllib3, para
  callar sus avisos): con los mirrors actuales el certificado valida bien,
  así que se deja la verificación normal;
- al importarse pone su logger en DEBUG: aquí se baja a WARNING.
De la librería se usa su clase SciHub: la sesión HTTP y la lista de mirrors.

Límites: Sci-Hub dejó de incorporar papers hacia 2021, así que los más
recientes no están. Los mirrors cambian y a veces responden con una
verificación anti-robot: en ese caso se prueba el siguiente y, si ninguno
responde, el paper queda como estaba.

Importante: a diferencia de las otras fuentes, Sci-Hub no es acceso abierto
legal; reparte copias sin permiso de las editoriales y usarlo puede infringir
derechos de autor según el país y la institución. Se apaga con
config.USAR_SCIHUB = False.
"""

import logging
import re
from urllib.parse import urldefrag, urljoin

import requests
from bs4 import BeautifulSoup
from scihub import SciHub

import config

logging.getLogger("scihub").setLevel(logging.WARNING)

TIMEOUT_S = 20
CABECERAS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"}


def _doi_pelado(doi):
    """La base guarda el DOI como 'https://doi.org/10.xxxx'; Sci-Hub lo
    recibe sin ese prefijo."""
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.I)


def _cliente(mirrors):
    sh = SciHub()
    sh.available_base_url_list = list(mirrors)
    sh.session.headers = dict(CABECERAS)
    return sh


def _enlace_pdf(pagina, base):
    """Sci-Hub muestra el PDF incrustado en la página del paper. Devuelve su
    enlace absoluto, o None si la página no trae ninguno."""
    for etiqueta in pagina.find_all(["embed", "iframe", "object"]):
        # Quita el "#view=FitH" del visor y resuelve "//host/..." y "/storage/..."
        enlace = urldefrag(urljoin(base, etiqueta.get("src") or etiqueta.get("data") or "")).url
        # Solo un .pdf: un dominio de Sci-Hub ya vencido puede responder con
        # una página de publicidad que también trae un <iframe>
        if enlace.lower().split("?")[0].endswith(".pdf"):
            return enlace
    return None


def _no_esta(pagina):
    """True si la página dice que el paper no está en la base de Sci-Hub
    ("статья отсутствует в базе"); una verificación anti-robot no cuenta."""
    titulo = pagina.title.get_text() if pagina.title else ""
    return "отсутствует" in titulo or "not found" in titulo.lower()


def buscar_pdf(sh, doi):
    """Enlace al PDF de un DOI en Sci-Hub, o None si no está (o si ningún
    mirror respondió). Un mirror caído se descarta para el resto de la corrida."""
    doi = _doi_pelado(doi)
    for mirror in list(sh.available_base_url_list):
        base = f"https://{mirror}/"
        config.esperar_turno()
        try:
            resp = sh.session.get(base + doi, timeout=TIMEOUT_S)
            resp.raise_for_status()
        except requests.RequestException as exc:
            print(f"  [aviso] Sci-Hub: {mirror} no responde ({type(exc).__name__}); no se vuelve a usar")
            sh.available_base_url_list.remove(mirror)
            continue
        pagina = BeautifulSoup(resp.content, "html.parser")
        enlace = _enlace_pdf(pagina, base)
        if enlace:
            return enlace
        if _no_esta(pagina):
            return None
        # Verificación anti-robot: se prueba el siguiente mirror
    return None


def _necesita_pdf(paper):
    if not paper.get("doi") or paper.get("pdf_bloqueado") == "no":
        return False
    return paper.get("pdf_bloqueado") == "si" or not paper.get("oa_url")


def completar(papers, mirrors, max_papers, al_avanzar=None):
    """Busca en Sci-Hub, por DOI, los primeros `max_papers` papers de la lista
    (se espera ya rankeada) que no tienen un PDF accesible. A los que
    encuentra les pone motor_pdf = "scihub", pdf_url y pdf_bloqueado = None
    (ese enlace no se revisa), y suma "scihub" a motor_busqueda.
    `al_avanzar(n, total)` se llama antes de cada paper. Devuelve cuántos
    encontró."""
    candidatos = [p for p in papers if _necesita_pdf(p)][:max_papers]
    if not candidatos:
        return 0
    sh = _cliente(mirrors)
    encontrados = 0
    for n, paper in enumerate(candidatos, start=1):
        if al_avanzar:
            al_avanzar(n, len(candidatos))
        if not sh.available_base_url_list:
            print("  [aviso] Sci-Hub: no quedó ningún mirror disponible (revisa config.SCIHUB_MIRRORS)")
            break
        enlace = buscar_pdf(sh, paper["doi"])
        if not enlace:
            continue
        motores = set((paper.get("motor_busqueda") or "").split("; ")) - {""}
        paper["motor_busqueda"] = "; ".join(sorted(motores | {"scihub"}))
        paper["motor_pdf"] = "scihub"
        paper["pdf_url"] = enlace
        paper["pdf_bloqueado"] = None
        encontrados += 1
    return encontrados
