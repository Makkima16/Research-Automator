"""
Completa por DOI el abstract de los papers que llegaron sin él.

Scopus no entrega el abstract en su búsqueda, y Semantic Scholar y OpenAlex a
veces tampoco (derechos de autor). Sin abstract el paper se rankea peor y no
hay de dónde armar su ficha. Para cada paper con DOI y sin abstract se prueban,
en orden y gratis (sin API key), OpenAlex, Crossref y Europe PMC; la primera
fuente que devuelve un abstract completo gana.
"""

import html
import re
from urllib.parse import quote

import requests

import config
import fetch_papers

MIN_PALABRAS = 30     # menos que esto no se considera un abstract
OPENALEX = "https://api.openalex.org/works/doi:"
CROSSREF = "https://api.crossref.org/works/"
EUROPEPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
CABECERAS = {"User-Agent": f"Mozilla/5.0 (proyecto academico; mailto:{config.CONTACT_EMAIL})"}


def tiene_abstract(texto):
    return len((texto or "").split()) >= MIN_PALABRAS


def necesita_abstract(paper):
    return bool(paper.get("doi")) and not tiene_abstract(paper.get("abstract"))


def _doi_pelado(doi):
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", doi or "").strip()


def _limpiar(texto):
    """Quita las etiquetas (JATS/HTML) y el encabezado 'Abstract' que algunas fuentes agregan."""
    texto = html.unescape(re.sub(r"<[^>]+>", " ", texto or ""))
    texto = re.sub(r"\s+", " ", texto).strip()
    return re.sub(r"^abstract[\s:.\-–—]*", "", texto, flags=re.I)


def _json(url, **params):
    config.esperar_turno()
    try:
        resp = requests.get(url, params=params, headers=CABECERAS, timeout=20)
        return resp.json() if resp.status_code == 200 else None
    except (requests.RequestException, ValueError):
        return None


def _openalex(doi):
    datos = _json(OPENALEX + quote(doi, safe="/"), select="abstract_inverted_index", mailto=config.CONTACT_EMAIL)
    return fetch_papers.reconstruct_abstract((datos or {}).get("abstract_inverted_index"))


def _crossref(doi):
    datos = _json(CROSSREF + quote(doi, safe="/"), mailto=config.CONTACT_EMAIL)
    return _limpiar(((datos or {}).get("message") or {}).get("abstract"))


def _europepmc(doi):
    datos = _json(EUROPEPMC, query=f'DOI:"{doi}"', format="json", resultType="core", pageSize=1)
    resultados = ((datos or {}).get("resultList") or {}).get("result") or []
    return _limpiar(resultados[0].get("abstractText")) if resultados else ""


FUENTES = (_openalex, _crossref, _europepmc)


def abstract_por_doi(doi):
    """Abstract del paper (texto plano) o '' si ninguna fuente lo tiene completo."""
    doi = _doi_pelado(doi)
    if not doi:
        return ""
    for fuente in FUENTES:
        texto = fuente(doi)
        if tiene_abstract(texto):
            return texto
    return ""


def completar(papers, al_avanzar=None):
    """Pone el abstract en los papers (dicts) que no lo tienen. `al_avanzar(n, total)`
    se llama antes de cada paper. Devuelve cuántos completó."""
    pendientes = [p for p in papers if necesita_abstract(p)]
    completados = 0
    for n, paper in enumerate(pendientes, start=1):
        if al_avanzar:
            al_avanzar(n, len(pendientes))
        texto = abstract_por_doi(paper["doi"])
        if texto:
            paper["abstract"] = texto
            completados += 1
    return completados
