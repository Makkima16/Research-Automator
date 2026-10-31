"""
Configuración del procesamiento de los papers: lectura de su estructura
(Nemotron Parse / Europe PMC) y fichas con Nemotron.

La búsqueda vive en ../busqueda y no depende de esta carpeta. El
procesamiento sí usa la búsqueda: lee su base de datos y reutiliza sus
módulos `config` y `database`. Por eso este archivo agrega
../busqueda a la ruta de importación; los demás scripts lo importan
primero (`import config_proc as config`).
"""

import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.append(os.path.join(RAIZ, "busqueda"))

import config as _config_busqueda  # noqa: E402  (busqueda/config.py)

CONTACT_EMAIL = _config_busqueda.CONTACT_EMAIL

# La base es la misma de la búsqueda: aquí se le agregan las tablas del
# procesamiento (estructuras, fichas)
DB_PATH = _config_busqueda.DB_PATH

# NVIDIA: modelo, URL y keys se definen una sola vez en ../busqueda/config.py
# (también los usa generar_cadenas.py)
NVIDIA_MODELO = _config_busqueda.NVIDIA_MODELO
NVIDIA_URL_PARSE = _config_busqueda.NVIDIA_URL_PARSE
NVIDIA_PARSE_API_KEY = _config_busqueda.NVIDIA_PARSE_API_KEY
# Pausa entre grupos de solicitudes seguidas al LLM (el plan gratis de NVIDIA limita
# los pedidos por minuto)
PAUSA_LLM_S = 2
# Lotes de fichas que se envían al LLM al mismo tiempo
HILOS_LOTES_FICHA = 2

# Algunos "abstracts" de OpenAlex traen el texto completo del paper (miles de
# palabras). Se recortan a este largo para el LLM.
MAX_CARACTERES_ABSTRACT = 6000

# Cuántos papers del ranking se procesan por defecto desde la línea de comandos
MAX_PAPERS_TO_EXTRACT = 100

# Tope de papers por corrida de "Procesar PDFs" desde la interfaz web
# (frontend/servidor.py). Solo frena una corrida lanzada por error
MAX_PAPERS_PROCESAR_WEB = 100

# Nemotron Parse lee cada página como imagen y tarda decenas de segundos por página.
# Las páginas se leen en paralelo con este número de hilos.
HILOS_PARSE = 4
# PDF que el lector local no entendió: a Nemotron Parse van las PAGINAS_INICIALES_PARSE
# primeras (abstract e introducción) más las páginas que pymupdf ubicó con las
# conclusiones y los títulos de tabla. Un PDF sin texto (escaneado) no se puede ubicar:
# ahí se leen las primeras y las últimas, hasta MAX_PAGINAS_PARSE en total.
MAX_PAGINAS_PARSE = 10
PAGINAS_INICIALES_PARSE = 4
# Con el modo híbrido el PDF se lee primero en local y gratis (pymupdf, solo en
# memoria): Nemotron Parse recibe únicamente las páginas con tablas, hasta este máximo.
MAX_PAGINAS_TABLAS_PARSE = 8

# Fichas por paper (extract_ficha.py): papers por solicitud al LLM y
# presupuesto de tokens de entrada por solicitud. Cada paper aporta ~1-2 mil tokens.
PAPERS_POR_LOTE_FICHA = 8
MAX_TOKENS_ENTRADA_FICHA = 16000
