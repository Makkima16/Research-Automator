"""
Prueba mínima de conexión con el deployment de GPT-5.5 en Azure AI Foundry:
una sola llamada de chat completions para confirmar que AZURE_OPENAI_ENDPOINT
y AZURE_OPENAI_API_KEY (.env) y AZURE_OPENAI_DEPLOYMENT (config_proc.py) son
correctos, antes de correr extract_llm_insights.py con papers reales.

    python probar_azure_openai.py
"""

import os

import requests

import config_proc as config
from extract_llm_insights import ErrorFatal, _azure_url, cargar_env


def main():
    cargar_env()
    faltan = [v for v in ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY") if not os.environ.get(v)]
    if faltan:
        print(f"ERROR: falta {' y '.join(faltan)} en el archivo .env.")
        return

    try:
        url = _azure_url()
    except ErrorFatal as exc:
        print(f"ERROR: {exc}")
        return
    print(f"Probando: {url}")
    print(f"Deployment configurado: {config.AZURE_OPENAI_DEPLOYMENT} "
          f"(cámbialo en config_proc.py si no es el nombre real)")

    cuerpo = {
        "messages": [{"role": "user", "content": "Responde solo con la palabra: ok"}],
    }
    cabeceras = {"api-key": os.environ["AZURE_OPENAI_API_KEY"]}
    try:
        resp = requests.post(url, json=cuerpo, headers=cabeceras, timeout=60)
    except requests.RequestException as exc:
        print(f"ERROR de conexión: {exc}")
        return

    if resp.status_code == 200:
        texto = resp.json()["choices"][0]["message"]["content"]
        print(f"OK: el modelo respondió -> {texto!r}")
    elif resp.status_code == 404:
        print("ERROR 404: la URL no existe para este recurso.")
        print("Revisa en Foundry -> Deployments -> tu deployment -> 'View code' el nombre exacto "
              "del deployment (AZURE_OPENAI_DEPLOYMENT) y el api-version (AZURE_OPENAI_API_VERSION) "
              "en config_proc.py.")
    elif resp.status_code in (401, 403):
        print(f"ERROR {resp.status_code}: la API key no es válida para este recurso. Revisa AZURE_OPENAI_API_KEY en .env.")
    else:
        print(f"ERROR {resp.status_code}: {resp.text[:400]}")


if __name__ == "__main__":
    main()
