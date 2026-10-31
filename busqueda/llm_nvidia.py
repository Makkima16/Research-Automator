"""
Llamada al LLM de NVIDIA (Nemotron en build.nvidia.com, API de chat completions
compatible con OpenAI) con respuesta en JSON, reintentos y manejo del límite de
uso. La comparten busqueda/generar_cadenas.py y procesamiento/extract_ficha.py.
"""

import json
import time

import requests

import config


class ErrorFatal(ValueError):
    """Error que no se arregla reintentando (key inválida, cuota agotada): se
    detiene la corrida completa."""


def configurado():
    return bool(config.NVIDIA_API_KEY)


def _extraer_json(texto):
    """El JSON de la respuesta, sin las cercas ``` ni texto alrededor."""
    texto = (texto or "").strip()
    if texto.startswith("```"):
        texto = texto.split("\n", 1)[-1].rsplit("```", 1)[0]
    inicio, fin = texto.find("{"), texto.rfind("}")
    if inicio == -1 or fin < inicio:
        raise ValueError("el modelo no devolvió un JSON")
    texto = texto[inicio:fin + 1]
    json.loads(texto)
    return texto


def chat_json(sistema, usuario, intentos=2, timeout=300, max_tokens=12000):
    """Devuelve el texto JSON que responde el modelo."""
    if not configurado():
        raise ErrorFatal("falta NVIDIA_API_KEY en el archivo .env.")
    cuerpo = {"model": config.NVIDIA_MODELO, "max_tokens": max_tokens, "temperature": 0.2,
              # Sin razonamiento: con él gasta todos los tokens pensando y no llega a responder
              "chat_template_kwargs": {"enable_thinking": False},
              "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}]}
    cabeceras = {"Authorization": f"Bearer {config.NVIDIA_API_KEY}"}
    esperas_por_limite, intento = 0, 0
    while intento < intentos:
        intento += 1
        try:
            resp = requests.post(config.NVIDIA_URL_CHAT, json=cuerpo, headers=cabeceras, timeout=timeout)
        except requests.RequestException:
            if intento == intentos:
                raise
            time.sleep(15)
            continue
        if resp.status_code == 429:
            espera = float(resp.headers.get("retry-after") or 30)
            if espera > 300:
                raise ErrorFatal(f"Límite de uso alcanzado; se renueva en {espera / 60:.0f} min.")
            esperas_por_limite += 1
            if esperas_por_limite > 5:
                resp.raise_for_status()
            print(f"  -> límite por minuto; esperando {espera:.0f}s")
            time.sleep(espera)
            intento -= 1
            continue
        if resp.status_code in (401, 403, 404):
            raise ErrorFatal(f"NVIDIA respondió {resp.status_code}: revisa NVIDIA_API_KEY y el modelo "
                             f"({config.NVIDIA_MODELO}).")
        if resp.status_code == 413:
            raise ValueError(f"solicitud demasiado grande (413): {resp.text[:150]}")
        if 400 <= resp.status_code < 500:
            raise ValueError(f"NVIDIA respondió {resp.status_code}: {resp.text[:300]}")
        if resp.status_code >= 500:
            if intento < intentos:
                time.sleep(15)
                continue
            resp.raise_for_status()
        try:
            return _extraer_json(resp.json()["choices"][0]["message"].get("content"))
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            if intento == intentos:
                raise ValueError(f"respuesta de NVIDIA inválida: {exc}") from exc
    raise ValueError("NVIDIA no respondió tras los reintentos")
