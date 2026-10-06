"""
Genera cadenas de búsqueda a partir de un tema escrito en lenguaje natural
(lo usa la interfaz web, ver servidor.py). Las cadenas salen en la misma
sintaxis AND / OR / NOT de config.PAPER_QUERIES (ver fetch_papers.py).

Usa un modelo de Gemini (Google AI Studio) por medio de LangChain
(config.LLM_MODELO, key en ../.env como LLM_API_KEY). Si no hay key o el LLM
falla, arma cadenas básicas con las palabras del tema y devuelve un aviso,
para que la interfaz siga funcionando y el usuario las edite a mano.
"""

import re

from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field

import config

MAX_CADENAS = 12

IDIOMAS = {
    "es": "español",
    "en": "inglés",
    "ambos": "inglés y español: en cada grupo pon los términos en inglés y, como "
             "alternativas con OR, sus equivalentes en español",
}

INSTRUCCIONES = """Eres un bibliotecario experto en búsquedas bibliográficas. A partir del tema \
del usuario escribe {n} cadenas de búsqueda distintas y complementarias (cada una cubre un ángulo \
diferente del tema) para bases académicas (OpenAlex, Semantic Scholar, Scopus).

Sintaxis obligatoria de cada cadena:
- Operadores AND, OR y NOT en mayúsculas, separados por espacios.
- "frase exacta" entre comillas dobles para los términos de más de una palabra.
- AND separa grupos de conceptos que el paper debe tener todos; OR une sinónimos dentro de un \
grupo. Es decir, A OR B AND C OR D significa (A OR B) AND (C OR D). No uses paréntesis.
- NOT solo admite un término o una frase, y va como último grupo: ... AND NOT "término".
- Entre 2 y 3 grupos AND por cadena, con 2 a 4 alternativas por grupo.
- Sin filtros de fecha, de campo ni comodines.

Idioma de los términos: {idioma}."""


class Cadenas(BaseModel):
    """Forma de la respuesta que se le pide al modelo."""
    cadenas: list[str] = Field(description="Las cadenas de búsqueda, una por elemento")

# Palabras que no sirven como término de búsqueda en las cadenas básicas
_VACIAS = set("""de del la las el los un una unos unas en con por para sobre entre y o que como
su sus al lo se es son más menos muy the of in on and or for with to from by a an at into
efecto efectos estudio estudios últimos ultimos años anos effects effect study studies""".split())


def _limpiar(cadenas, n):
    limpias = []
    for c in cadenas:
        if not isinstance(c, str):
            continue
        c = " ".join(c.replace("(", "").replace(")", "").split())
        if c and c not in limpias:
            limpias.append(c)
    return limpias[:n]


def _llamar_llm(tema, n, idioma):
    if not config.LLM_API_KEY:
        raise ValueError("falta LLM_API_KEY en ../.env")
    modelo = ChatGoogleGenerativeAI(
        model=config.LLM_MODELO, google_api_key=config.LLM_API_KEY,
        temperature=0.3, timeout=60, max_retries=1,
    )
    # with_structured_output hace que el modelo responda con el esquema Cadenas
    respuesta = modelo.with_structured_output(Cadenas).invoke([
        ("system", INSTRUCCIONES.format(n=n, idioma=IDIOMAS[idioma])),
        ("human", f"Tema: {tema}"),
    ])
    cadenas = _limpiar(respuesta.cadenas if respuesta else [], n)
    if not cadenas:
        raise ValueError("el modelo no devolvió ninguna cadena")
    return cadenas


def cadenas_basicas(tema, n):
    """Respaldo sin LLM: combina las palabras con contenido del tema."""
    palabras = []
    for p in re.findall(r"[^\W\d_]{3,}", tema.lower()):
        if p not in _VACIAS and p not in palabras:
            palabras.append(p)
    palabras = palabras[:6] or ["tema"]
    nucleo = " AND ".join(palabras[:3])
    candidatas = [
        nucleo,
        f'{nucleo} AND review OR "systematic review" OR meta-analysis',
        " AND ".join(palabras[:2]),
        " AND ".join(palabras[:4]),
        " OR ".join(palabras[:2]) + (" AND " + " OR ".join(palabras[2:4]) if len(palabras) > 2 else ""),
        " AND ".join(palabras[1:4]),
        f'{" AND ".join(palabras[:2])} AND "clinical trial" OR "randomized"',
        " AND ".join(palabras[2:5]),
    ]
    return _limpiar(candidatas, n)


def generar(tema, n, idioma="es"):
    """Devuelve (cadenas, aviso). `aviso` es None si las generó el LLM."""
    n = max(1, min(int(n), MAX_CADENAS))
    if idioma not in IDIOMAS:
        idioma = "es"
    try:
        return _llamar_llm(tema, n, idioma), None
    except Exception as exc:  # LangChain y la API de Google lanzan errores de muchos tipos
        motivo = str(exc).replace(config.LLM_API_KEY or "\0", "<key>").splitlines()[0][:200] if str(exc) else type(exc).__name__
        print(f"  [aviso] no se pudieron generar las cadenas con el LLM: {type(exc).__name__}: {motivo}")
        return cadenas_basicas(tema, n), (
            f"No se pudo usar el LLM ({motivo}). Estas son cadenas básicas armadas con las "
            "palabras del prompt: revísalas y edítalas antes de buscar."
        )
