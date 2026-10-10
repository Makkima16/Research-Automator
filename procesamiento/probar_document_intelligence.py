"""
Prueba mínima de conexión con Azure AI Document Intelligence: solo lista los
modelos del recurso (no analiza ningún documento) para confirmar que
AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT y AZURE_DOCUMENT_INTELLIGENCE_API_KEY
(.env) son correctos.

    python probar_document_intelligence.py
"""

import os
from urllib.parse import urlsplit

import requests

import config_proc as config
from extract_llm_insights import cargar_env


def main():
    cargar_env()
    faltan = [v for v in ("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", "AZURE_DOCUMENT_INTELLIGENCE_API_KEY")
              if not os.environ.get(v)]
    if faltan:
        print(f"ERROR: falta {' y '.join(faltan)} en el archivo .env.")
        return

    partes = urlsplit(os.environ["AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT"])
    if not partes.scheme or not partes.netloc:
        print("ERROR: AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT no es una URL válida. Revisa el archivo .env.")
        return

    url = (f"{partes.scheme}://{partes.netloc}/documentintelligence/documentModels"
           f"?api-version={config.AZURE_DOCUMENT_INTELLIGENCE_API_VERSION}")
    print(f"Probando: {url}")
    cabeceras = {"Ocp-Apim-Subscription-Key": os.environ["AZURE_DOCUMENT_INTELLIGENCE_API_KEY"]}
    try:
        resp = requests.get(url, headers=cabeceras, timeout=60)
    except requests.RequestException as exc:
        print(f"ERROR de conexión: {exc}")
        return

    if resp.status_code == 200:
        modelos = resp.json().get("value", [])
        print(f"OK: el recurso respondió con {len(modelos)} modelo(s) disponible(s) "
              f"(prebuilt-layout, prebuilt-read, etc. deberían estar ahí).")
    elif resp.status_code == 404:
        print("ERROR 404: revisa AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT en .env "
              "(debe ser el del recurso de Document Intelligence, no el de Azure OpenAI).")
    elif resp.status_code in (401, 403):
        print(f"ERROR {resp.status_code}: la API key no es válida para este recurso. "
              "Revisa AZURE_DOCUMENT_INTELLIGENCE_API_KEY en .env.")
    else:
        print(f"ERROR {resp.status_code}: {resp.text[:400]}")


if __name__ == "__main__":
    main()
