"""Tablas de análisis de amplitud_res.json: por variante (global), por tema y por
cadena, más la simulación de cuántos papers recibiría el usuario con el tope por
cadena de la interfaz. No llama a ninguna API. Uso (desde esta carpeta):
    python analisis_amplitud.py [--tope=10]
"""

import argparse
import json
import os
import statistics

S = os.path.dirname(os.path.abspath(__file__))
SALIDA = S + "/resultados/amplitud_res.json"

ORDEN = ["base", "sin_not", "sin_comillas", "pares", "fulltext", "or"]


def cargar():
    with open(SALIDA, encoding="utf-8") as f:
        return json.load(f)


def puntos_de(tema, variante):
    return [p for cad in tema["cadenas"] for s in cad["variantes"].get(variante, []) for p in s["puntos"]]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tope", type=int, default=10)
    args = parser.parse_args()
    resultados = cargar()

    print("=== GLOBAL por variante (por búsqueda individual) ===")
    print(f"{'variante':13}{'búsquedas':>10}{'ceros':>6}{'satur':>6}{'mediana hits':>13}"
          f"{'estricta(=2)':>13}{'laxa(>=1)':>11}")
    agg = {}
    for tema in resultados:
        for cad in tema["cadenas"]:
            for nombre, subs in cad["variantes"].items():
                a = agg.setdefault(nombre, {"hits": [], "ceros": 0, "sat": 0, "pts": []})
                for s in subs:
                    if s["hits"] is None:
                        a["sat"] += 1
                        continue
                    a["hits"].append(s["hits"])
                    if s["hits"] == 0:
                        a["ceros"] += 1
                    a["pts"].extend(s["puntos"])
    for n in ORDEN:
        if n not in agg:
            continue
        a = agg[n]
        pts = a["pts"]
        print(f"{n:13}{len(a['hits']) + a['sat']:>10}{a['ceros']:>6}{a['sat']:>6}"
              f"{statistics.median(a['hits']):>13.0f}"
              f"{(sum(1 for p in pts if p == 2) / len(pts) if pts else 0):>13.2f}"
              f"{(sum(1 for p in pts if p >= 1) / len(pts) if pts else 0):>11.2f}")

    print("\n=== POR TEMA: hits totales (suma de las búsquedas que llegaron) ===")
    encabezado = f"{'tema':37}" + "".join(f"{v:>11}" for v in ORDEN if v in agg)
    print(encabezado)
    for tema in resultados:
        tot = {}
        for cad in tema["cadenas"]:
            for nombre, subs in cad["variantes"].items():
                for s in subs:
                    if s["hits"]:
                        tot[nombre] = tot.get(nombre, 0) + s["hits"]
        fila = f"{tema['tema'][:36]:37}" + "".join(f"{tot.get(v, 0):>11}" for v in ORDEN if v in agg)
        print(fila)

    print(f"\n=== POR TEMA: precisión estricta / laxa (todos los títulos juzgados) ===")
    for tema in resultados:
        partes = []
        for v in ORDEN:
            pts = puntos_de(tema, v)
            if pts:
                e = sum(1 for p in pts if p == 2) / len(pts)
                l = sum(1 for p in pts if p >= 1) / len(pts)
                partes.append(f"{v}: {e:.2f}/{l:.2f} (n={len(pts)})")
        print(f"{tema['tema'][:36]}")
        for p in partes:
            print(f"    {p}")

    print(f"\n=== Simulación: papers que llegan al usuario con tope={args.tope}/cadena (solo OpenAlex) ===")
    print(f"{'tema':37}{'hits base':>10}{'hits s/comill':>14}{'llegan base':>12}{'llegan s/comill':>16}")
    for tema in resultados:
        base_hits = sum((c["variantes"].get("base", [{}])[0].get("hits") or 0) for c in tema["cadenas"])
        sc_hits = sum((c["variantes"].get("sin_comillas", [{}])[0].get("hits") or 0)
                      for c in tema["cadenas"] if "sin_comillas" in c["variantes"])
        base_llegan = sum(min(c["variantes"].get("base", [{}])[0].get("hits") or 0, args.tope)
                          for c in tema["cadenas"])
        sc_llegan = sum(min(c["variantes"].get("sin_comillas", [{}])[0].get("hits") or 0, args.tope)
                        for c in tema["cadenas"] if "sin_comillas" in c["variantes"])
        print(f"{tema['tema'][:36]:37}{base_hits:>10}{sc_hits:>14}{base_llegan:>12}{sc_llegan:>16}")

    print("\n=== Cadenas con 0 hits en base y qué variante las rescata ===")
    for tema in resultados:
        for cad in tema["cadenas"]:
            b = cad["variantes"].get("base", [{}])[0]
            if b.get("hits") == 0:
                otros = {v: [s.get("hits") for s in cad["variantes"].get(v, [])]
                         for v in ORDEN if v != "base" and v in cad["variantes"]}
                print(f"[{tema['tema']}] {cad['cadena'][:80]}")
                print(f"    {otros}")


if __name__ == "__main__":
    main()
