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

# Archivo con las API keys del LLM y de Document Intelligence
ENV_PATH = os.path.join(RAIZ, ".env")

# Proveedor del LLM que lee los abstracts:
#   "azure"  -> deployment de GPT-5.5 en Azure AI Foundry; el endpoint y la key
#               van en .env como AZURE_OPENAI_ENDPOINT=... y AZURE_OPENAI_API_KEY=...
#   "ollama" -> modelo local en tu PC con Ollama (gratis, sin cuotas, más lento)
LLM_PROVEEDOR = "azure"

# Ollama: instala desde https://ollama.com y descarga el modelo con
# "ollama pull qwen2.5:7b". Un modelo de 7-8B necesita ~6 GB de RAM.
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODELO = "qwen2.5:7b"
OLLAMA_CONTEXTO = 8192       # tokens de contexto (prompt + respuesta)
OLLAMA_TIMEOUT_S = 1800      # en CPU una respuesta puede tardar varios minutos
PAPERS_POR_LOTE_LOCAL = 2    # los modelos pequeños rinden mejor con pocos papers a la vez

# Azure AI Foundry. El nombre del deployment y el api-version NO son secretos
# (a diferencia del endpoint y la key, que van en .env): ajústalos aquí según
# lo que muestre tu recurso en Foundry -> Deployments -> "View code".
AZURE_OPENAI_DEPLOYMENT = "gpt-5.5"
AZURE_OPENAI_API_VERSION = "2024-10-21"
# Plan pagado: lotes más grandes y menos pausa que con Groq gratis; ajusta
# según el límite de tokens/minuto (TPM) que te muestre tu cuota de Azure.
PAPERS_POR_LOTE_AZURE = 15
PAUSA_AZURE_S = 2
# Tokens de entrada máximos por solicitud: los lotes se arman sumando papers
# hasta este presupuesto (súbelo si tu cuota de Azure lo permite)
MAX_TOKENS_ENTRADA_AZURE = 20000

# Algunos "abstracts" de OpenAlex traen el texto completo del paper (miles de
# palabras). Se recortan a este largo para el LLM; la verificación de citas
# sigue usando el texto completo.
MAX_CARACTERES_ABSTRACT = 6000

# Cuántos papers del ranking se envían al LLM por defecto
MAX_PAPERS_TO_EXTRACT = 50

# Tope de papers por corrida de "Procesar PDFs" desde la interfaz web del
# Buscador (busqueda/servidor.py), para controlar el costo de Azure
MAX_PAPERS_PROCESAR_WEB = 60

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

# Azure AI Document Intelligence (endpoint y key en .env: AZURE_DOCUMENT_INTELLIGENCE_*)
AZURE_DOCUMENT_INTELLIGENCE_API_VERSION = "2024-11-30"
