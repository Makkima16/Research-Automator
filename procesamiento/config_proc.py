"""
Configuración del procesamiento de los papers: texto completo, extracción con
el LLM, tabla del árbol de decisiones y normatividad.

La búsqueda (OpenAlex y USDA) vive en ../busqueda y no depende de esta carpeta.
El procesamiento sí usa la búsqueda: lee su base de datos (selema.db) y
reutiliza sus módulos `config`, `database` y `fetch_usda`. Por eso este archivo
agrega ../busqueda a la ruta de importación; los demás scripts lo importan
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
# procesamiento (textos_completos, extracciones, observaciones, normas...)
DB_PATH = _config_busqueda.DB_PATH

# CSV que exporta el procesamiento (tabla_arbol.csv, evidencia_mercado.csv...)
OUTPUT_DIR = os.path.join(_AQUI, "output")

# Archivo con las API keys del LLM (GEMINI_API_KEY, LLM_API_KEY)
ENV_PATH = os.path.join(RAIZ, ".env")

# Proveedor del LLM que lee los abstracts:
#   "gemini" -> API de Google (cuota gratuita muy limitada)
#   "ollama" -> modelo local en tu PC con Ollama (gratis, sin cuotas, más lento)
#   "openai" -> cualquier API compatible con OpenAI (Groq, OpenRouter, Mistral...);
#               la key va en .env como LLM_API_KEY=...
LLM_PROVEEDOR = "openai"

# Ollama: instala desde https://ollama.com y descarga el modelo con
# "ollama pull qwen2.5:7b". Un modelo de 7-8B necesita ~6 GB de RAM.
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODELO = "qwen2.5:7b"
OLLAMA_CONTEXTO = 8192       # tokens de contexto (prompt + respuesta)
OLLAMA_TIMEOUT_S = 1800      # en CPU una respuesta puede tardar varios minutos
PAPERS_POR_LOTE_LOCAL = 2    # los modelos pequeños rinden mejor con pocos papers a la vez

# API compatible con OpenAI. Ejemplo para Groq (revisa en su consola los
# modelos disponibles y sus límites gratuitos):
OPENAI_BASE_URL = "https://api.groq.com/openai/v1"
OPENAI_MODELO = "qwen/qwen3.8-27b"
# El plan gratuito de Groq limita los tokens por minuto (~8000): lotes chicos
# y una pausa entre solicitudes para no pasarse
PAPERS_POR_LOTE_API = 3
PAUSA_API_S = 30
# Tokens de entrada máximos por solicitud (Groq gratis acepta ~7000 por minuto):
# los lotes se arman sumando papers hasta este presupuesto
MAX_TOKENS_ENTRADA_API = 5000

# Algunos "abstracts" de OpenAlex traen el texto completo del paper (miles de
# palabras). Se recortan a este largo para el LLM; la verificación de citas
# sigue usando el texto completo.
MAX_CARACTERES_ABSTRACT = 6000

# Modelo de Gemini para extraer observaciones de los abstracts.
# La API key va en el archivo .env: GEMINI_API_KEY=tu_api_key
LLM_MODEL = "gemini-3.8-flash"
# Si el modelo principal está saturado (error 503), se prueban estos en orden
# (cada modelo tiene su propia cuota diaria; los alias "-latest" comparten la
# del modelo al que apuntan, por eso no se usan aquí)
LLM_MODELOS_RESPALDO = ["gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.1-flash-lite"]

# Papers enviados en cada solicitud al LLM. El plan gratuito da ~20 solicitudes
# por día y por modelo: con 10 papers por lote alcanzan para ~200 papers diarios.
PAPERS_POR_LOTE = 10

# Si todos los modelos están saturados (error 503), espera antes del siguiente lote
ESPERA_SATURACION_S = 120

# Cuántos papers del ranking se envían al LLM por defecto
MAX_PAPERS_TO_EXTRACT = 50

# Pausa entre llamadas al LLM (el plan gratuito de Gemini limita las
# solicitudes por minuto; bájala si tienes un plan con más cuota)
PAUSA_ENTRE_LLAMADAS_S = 6

# Normatividad: tabla editable con los límites legales (una fila por parámetro).
# Es la fuente de verdad; se recarga en selema.db (tabla `normas`) cada
# vez que se abre la base. Ver normatividad.py.
NORMAS_CSV = os.path.join(_AQUI, "normas.csv")
# Jurisdicciones contra las que se evalúa el cumplimiento (las demás filas del
# CSV quedan solo como referencia): colombia, codex, ee_uu, union_europea
JURISDICCIONES_NORMAS = ["colombia", "codex"]

# Texto completo de los papers de acceso abierto (fetch_fulltext.py). El LLM
# no recibe el paper entero (no cabe en la cuota): recibe los fragmentos con
# condiciones de proceso (°C, tiempos, pH, composición), hasta este largo.
MAX_CARACTERES_TEXTO_COMPLETO = 4000
# Papers del ranking para los que se busca texto completo
MAX_PAPERS_TEXTO_COMPLETO = 200
