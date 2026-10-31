"""Relevo post-cambio: corre las mismas 37 cadenas de amplitud_res.json por el
código NUEVO de fetch_papers.py (sin comillas + rescate en texto completo, tope
25 por cadena) y compara cuántos papers entrega contra lo que entregaba el
sistema anterior (tope 10 sobre la búsqueda con frases exactas). Los títulos
nuevos los puntúa el juez (0/1/2, mismo criterio que amplitud.py) para
verificar que siguen relacionados con el tema. Escribe resultados/relevo_res.json.
Uso (desde esta carpeta): python relevo.py
"""

import argparse
import json
import os
import sys
import time

S = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(os.path.dirname(S))
sys.path.insert(0, os.path.join(RAIZ, "busqueda"))
sys.path.insert(0, S)

import amplitud as a
import config
import fetch_papers as fp

SALIDA = S + "/resultados/relevo_res.json"
TOPE_NUEVO = 25
TOPE_VIEJO = 10


def main():
    parser = argparse.ArgumentParser()
    args = parser.parse_args()

    with open(S + "/resultados/amplitud_res.json", encoding="utf-8") as f:
        temas = json.load(f)

    proveedor = "nvidia"
    salida = []
    print(f"{len(temas)} temas; tope nuevo: {TOPE_NUEVO}", flush=True)
    for tema in temas:
        filas = []
        for cad in tema["cadenas"]:
            base_vieja = cad["variantes"].get("base", [{}])[0]
            antes = min(base_vieja.get("hits") or 0, TOPE_VIEJO)
            try:
                rows = fp.fetch_openalex(cad["cadena"], config.CONTACT_EMAIL, 2015, max_results=TOPE_NUEVO)
            except Exception as exc:
                filas.append({"cadena": cad["cadena"], "antes": antes, "ahora": None,
                              "titulos": [], "puntos": [], "error": str(exc)[:150]})
                continue
            titulos = [r["title"] for r in rows[:10] if r["title"]]
            puntos = a.juzgar(tema["ctx"], cad["cadena"], titulos) if titulos else []
            filas.append({"cadena": cad["cadena"], "antes": antes, "ahora": len(rows),
                          "titulos": titulos, "puntos": puntos})
            print(f"   antes={antes:>3}  ahora={len(rows):>3}  {cad['cadena'][:70]}", flush=True)
        salida.append({"tema": tema["tema"], "juez": proveedor, "filas": filas})
        with open(SALIDA, "w", encoding="utf-8") as f:
            json.dump(salida, f, ensure_ascii=False, indent=1)

    total_antes = sum(f["antes"] for t in salida for f in t["filas"])
    total_ahora = sum(f["ahora"] or 0 for t in salida for f in t["filas"])
    puntos = [p for t in salida for f in t["filas"] for p in f["puntos"]]
    estricta = sum(1 for p in puntos if p == 2) / len(puntos) if puntos else None
    laxa = sum(1 for p in puntos if p >= 1) / len(puntos) if puntos else None
    print(f"\nPapers entregados: {total_antes} (antes, tope 10) -> {total_ahora} (ahora, tope 25)")
    print(f"Calidad del top-10 nuevo (juez {proveedor}): estricta={estricta:.2f} laxa={laxa:.2f} (n={len(puntos)})")
    print("Resultados en", SALIDA, flush=True)


if __name__ == "__main__":
    main()
