"""
Configuración de la búsqueda de papers (OpenAlex, Semantic Scholar, Scopus y
Sci-Hub).
Edita las cadenas de búsqueda y los parámetros según el tema que investigues.

La configuración del procesamiento de los papers (LLM, texto completo,
normatividad) está en ../procesamiento/config_proc.py.
"""

import os
import threading
import time


def _leer_env(ruta):
    """Lee un archivo .env (CLAVE=valor, una por línea) sin depender de
    python-dotenv. Si el archivo no existe, devuelve un diccionario vacío."""
    valores = {}
    try:
        with open(ruta, encoding="utf-8") as f:
            for linea in f:
                linea = linea.strip()
                if not linea or linea.startswith("#") or "=" not in linea:
                    continue
                clave, valor = linea.split("=", 1)
                valores[clave.strip()] = valor.strip().strip('"').strip("'")
    except OSError:
        pass
    return valores


# Las claves se leen de ../.env (el de proyecto_cafe/automatización) o de las
# variables de entorno; así no quedan escritas en este archivo.
_ENV = _leer_env(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))


def _clave(nombre):
    return os.environ.get(nombre) or _ENV.get(nombre, "")


# Tu correo se usa como parámetro "mailto" en OpenAlex: entra al "polite pool"
# (respuestas más rápidas y estables). No implica ningún registro.
CONTACT_EMAIL = "andres.padilla34809@ucaldas.edu.co"

# Búsquedas de papers en OpenAlex, con la sintaxis booleana de
# fetch_papers.py (AND / OR / NOT, igual que en la búsqueda avanzada de
# ScienceDirect; ver el docstring de ese archivo para el detalle). Importa
# más la precisión de cada búsqueda que la cantidad: pocas búsquedas bien
# armadas, con AND entre los conceptos que un paper relevante SÍ debe tener
# juntos, encuentran menos ruido que muchas búsquedas cortas sueltas. Los
# resultados de todas se combinan y se deduplican por DOI.
PAPER_QUERIES = [
    # Ejemplos genéricos: reemplázalos por las cadenas de tu tema (o genéralas
    # desde la interfaz web con servidor.py)
    # Concepto principal AND variable de interés
    '"machine learning" OR "deep learning" '
    'AND diagnosis OR prediction OR "risk assessment"',

    # Intervención AND resultado, limitando a revisiones
    '"intervention" OR "treatment" '
    'AND "systematic review" OR meta-analysis',
]

# Año mínimo de publicación a considerar (None = sin límite inferior)
MIN_PUBLICATION_YEAR = 2015

# Papers que se traen por cada cadena de búsqueda en cada plataforma (OpenAlex,
# Semantic Scholar y Scopus): con N cadenas y 3 plataformas, hasta N × 3 × este
# valor antes de deduplicar por DOI.
MAX_RESULTS_PER_QUERY = 10

# Segundos que se dejan pasar entre una solicitud y la siguiente a las
# plataformas de papers (las tres de arriba y Sci-Hub), sin importar a cuál
# vayan, para no saturarlas
PAUSA_ENTRE_PETICIONES_S = 2

_candado_ritmo = threading.Lock()
_ultima_peticion = 0.0


def esperar_turno():
    """Llamar justo antes de cada solicitud: duerme lo que falte para cumplir
    la pausa desde la solicitud anterior (también cuenta los reintentos)."""
    global _ultima_peticion
    with _candado_ritmo:  # servidor.py busca en hilos: que no se cuelen dos a la vez
        falta = _ultima_peticion + PAUSA_ENTRE_PETICIONES_S - time.monotonic()
        if falta > 0:
            time.sleep(falta)
        _ultima_peticion = time.monotonic()


# Palabras clave para buscar productos/alimentos lácteos en USDA FoodData Central
USDA_QUERIES = [
    "A2 milk",
    "milk beta casein",
    "whole milk",
    "yogurt",
    "cheese",
    "lactose free milk",
    "grass fed milk",
    "organic milk",
    "UHT milk",
    "goat milk",
    "kefir",
]

# Consigue tu API key gratis e instantánea en:
# https://fdc.nal.usda.gov/api-key-signup
# DEMO_KEY funciona pero con un límite muy bajo (30 solicitudes/hora).
USDA_API_KEY = _clave("USDA_API_KEY")

# Semantic Scholar (https://www.semanticscholar.org): segunda fuente de
# papers, independiente de OpenAlex. Se usa para encontrar más papers y,
# sobre todo, para los que ya trajo OpenAlex con el PDF bloqueado: a veces
# tiene un enlace a otro repositorio que sí funciona (ver
# fetch_semantic_scholar.py).
#
# Sin key su cuota es muy baja y compartida (muchos 429; el código los salta
# con un aviso). Cuando llegue la key, ponla abajo.
USAR_SEMANTIC_SCHOLAR = True
SEMANTIC_SCHOLAR_API_KEY = _clave("SEMANTIC_SCHOLAR_API_KEY")

# Scopus (Elsevier): tercera fuente. Key gratis en https://dev.elsevier.com
# (ver fetch_scopus.py). Sin key se salta con un aviso. La key es la misma de
# Elsevier que antes se usaba para ScienceDirect, así que también se acepta
# con su nombre anterior en ../.env.
USAR_SCOPUS = True
SCOPUS_API_KEY = _clave("SCOPUS_API_KEY") or _clave("SCIENCEDIRECT_API_KEY")

# Sci-Hub: cuarto motor (ver fetch_scihub.py). No busca por palabras clave:
# resuelve por DOI el PDF de los papers que los otros motores dejaron sin PDF
# accesible. No es acceso abierto legal (ver el aviso en fetch_scihub.py);
# ponlo en False para no usarlo.
USAR_SCIHUB = True
# Dominios de Sci-Hub, en el orden en que se prueban. Cambian con el tiempo:
# si uno deja de responder, quítalo o reemplázalo.
SCIHUB_MIRRORS = ["sci-hub.ru", "sci-hub.ee", "sci-hub.ren"]
# Cuántos de los papers mejor rankeados sin PDF accesible se buscan en
# Sci-Hub (hasta una solicitud por mirror por cada paper)
MAX_PAPERS_SCIHUB = 30

# Cuántos de los papers mejor rankeados se revisan contra bloqueo de PDF
# (una o dos solicitudes HTTP por paper; con muchos se vuelve lento)
MAX_PAPERS_VERIFICAR_PDF = 30

# Las rutas se calculan desde esta carpeta, así los scripts funcionan sin
# importar desde qué directorio se ejecuten
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

# Base de datos SQLite donde se guarda todo (el procesamiento agrega ahí
# mismo sus tablas)
DB_PATH = os.path.join(OUTPUT_DIR, "selema.db")

# Interfaz web (servidor.py). Cada proyecto se guarda como un JSON aparte, sin
# tocar selema.db.
WEB_PUERTO = 8000
PROYECTOS_DIR = os.path.join(OUTPUT_DIR, "proyectos")

# LLM que convierte el tema escrito en la interfaz web en cadenas de búsqueda
# (generar_cadenas.py): un modelo de Gemini (Google AI Studio) llamado con
# LangChain. La key va en ../.env como LLM_API_KEY (se saca gratis en
# https://aistudio.google.com/apikey). Sin key, o si el modelo falla, la
# interfaz arma cadenas básicas con las palabras del tema.
LLM_MODELO = "gemini-3.5-flash"
LLM_API_KEY = _clave("LLM_API_KEY")
