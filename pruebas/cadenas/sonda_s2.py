"""Sonda de Semantic Scholar: qué trae el sistema hoy (búsqueda bulk ordenada por
citas, tope de 10 resultados por cadena) para cadenas ya evaluadas en OpenAlex, y
qué tan relacionados están esos títulos según el juez. Compara el desvío del
motor contra el de OpenAlex para las mismas cadenas. Escribe
resultados/sonda_s2_res.json. Uso (desde esta carpeta): python sonda_s2.py
"""

import json
import os
import sys

S = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(os.path.dirname(S))
sys.path.insert(0, os.path.join(RAIZ, "busqueda"))
sys.path.insert(0, S)

import amplitud as a
import config
import fetch_semantic_scholar as s2

SALIDA = S + "/resultados/sonda_s2_res.json"

# (tema, contexto del juez, cadena): una cadena restrictiva y una amplia por tema
CADENAS = [
    ("extra_leche_es", "Efecto de la pasteurización UHT en la leche entera y su vida útil",
     '"pasteurización UHT" OR "ultra alta temperatura" OR "tratamiento térmico" OR "procesamiento térmico" OR "esterilización UHT" AND "leche entera" OR "leche fluida" OR "leche cruda"'),
    ("extra_cancer_es", "Tratamientos de cáncer de mama con inmunoterapia",
     '"cáncer de mama" OR "carcinoma mamario" OR "tumor de mama" OR "cáncer de pecho" OR mama AND inmunoterapia OR "inmunoterapia del cáncer" OR "inmunoterapia oncológica"'),
    ("extra_cobots_ambos", "Robots colaborativos en logística y almacenes",
     '"human robot collaboration" OR "colaboración humano robot" OR "colaboración humano-robot" AND "warehouse automation" OR "automatización de almacenes" OR "automatización logística"'),
]


def main():
    resultados = []
    for tema, ctx, cadena in CADENAS:
        filas = s2.buscar_semantic_scholar(cadena, config.SEMANTIC_SCHOLAR_API_KEY, 2015, 10)
        con_doi = [f for f in filas if f["doi"]]
        titulos = [f["title"] for f in con_doi if f["title"]]
        puntos = a.juzgar(ctx, cadena, titulos, "gpt") if titulos else []
        resultados.append({
            "tema": tema, "cadena": cadena, "total": len(filas), "con_doi": len(con_doi),
            "titulos": titulos, "puntos": puntos,
            "citas": [f["cited_by_count"] for f in con_doi],
        })
        e = sum(1 for p in puntos if p == 2)
        l = sum(1 for p in puntos if p >= 1)
        print(f"[{tema}] {len(filas)} resultados ({len(con_doi)} con DOI); "
              f"estricta {e}/{len(puntos)}, laxa {l}/{len(puntos)}", flush=True)
    with open(SALIDA, "w", encoding="utf-8") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=1)
    print("Resultados en", SALIDA, flush=True)


if __name__ == "__main__":
    main()
