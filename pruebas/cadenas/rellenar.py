"""Rellena las búsquedas que quedaron con hits=None en amplitud_res.json (OpenAlex
devolvió 429 durante la corrida original). Espera a que el presupuesto diario se
renueve, repite solo las búsquedas faltantes y sus juicios (Nemotron), recalcula
los resúmenes y guarda. Uso (desde esta carpeta):
    python rellenar.py
"""

import json
import os
import sys
import time

S = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(os.path.dirname(S))
sys.path.insert(0, os.path.join(RAIZ, "busqueda"))
sys.path.insert(0, S)

import requests

import amplitud as a
import config
import fetch_papers as fp

SALIDA = S + "/resultados/amplitud_res.json"


def esperar_openalex(max_min=180):
    """Espera hasta que OpenAlex responda 200 (presupuesto renovado)."""
    inicio = time.time()
    sonda = {"filter": "title_and_abstract.search:milk", "per-page": 1,
             "select": "title", "mailto": config.CONTACT_EMAIL}
    while time.time() - inicio < max_min * 60:
        config.esperar_turno()
        try:
            r = requests.get(fp.OPENALEX_URL, params=sonda, timeout=30)
            if r.status_code == 200:
                print("OpenAlex responde; se inicia el relleno", flush=True)
                return True
            print(f"  [aviso] OpenAlex {r.status_code}; reintento en 60s", flush=True)
        except requests.RequestException:
            print("  [aviso] fallo de red; reintento en 60s", flush=True)
        time.sleep(60)
    return False


def main():
    with open(SALIDA, encoding="utf-8") as f:
        resultados = json.load(f)

    pendientes = []
    for tema in resultados:
        for cad in tema["cadenas"]:
            for nombre, subs in cad["variantes"].items():
                for sub in subs:
                    if sub["hits"] is None or (sub["hits"] and not sub["puntos"]):
                        pendientes.append((tema, cad, nombre, sub))
    print(f"{len(pendientes)} búsquedas pendientes", flush=True)
    if not pendientes:
        return
    if not esperar_openalex():
        print("OpenAlex no respondió en el plazo; no se rellenó nada", flush=True)
        return

    temas_pendientes = {id(t) for t, *_ in pendientes}
    for tema in resultados:
        if id(tema) not in temas_pendientes:
            continue
        faltan = [(cad, nombre, sub) for t, cad, nombre, sub in pendientes if t is tema]
        print(f"== {tema['tema']}: {len(faltan)} búsquedas", flush=True)
        for cad, nombre, sub in faltan:
            campo = "default.search" if nombre == "fulltext" else "title_and_abstract.search"
            hits, titulos = a.buscar_openalex(sub["query"], campo=campo)
            sub["hits"], sub["titulos"] = hits, titulos
            if hits:
                sub["puntos"] = a.juzgar(tema["ctx"], cad["cadena"], titulos)
                if cad.get("juez") != "nvidia":
                    cad["juez"] = "nvidia"
            print(f"   [{nombre}] hits={hits}", flush=True)
        tema["resumen"] = a.resumen_variantes(tema)
        with open(SALIDA, "w", encoding="utf-8") as f:
            json.dump(resultados, f, ensure_ascii=False, indent=1)
    print("Relleno completo:", SALIDA, flush=True)


if __name__ == "__main__":
    main()
