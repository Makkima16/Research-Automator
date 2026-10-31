"""Sonda 2 de Semantic Scholar: ¿el desvío del orden por citas se arregla re-rankeando
localmente? Compara, para las mismas cadenas de sonda_s2.py más tres de los temas del
banco de amplitud, dos formas de elegir los 10 papers que el sistema entregaría:

- citas:  los 10 primeros de la búsqueda bulk (sort=citationCount:desc), exactamente
          como hace hoy buscar_semantic_scholar.
- local:  se traen 100 (misma cantidad de solicitudes: la bulk devuelve de a 100) y se
          re-rankean con rank_and_filter.score_paper usando las keywords de la propia
          cadena; los 10 mejores son los que se entregarían.

El juez (Nemotron, 0/1/2) puntúa ambos tops a ciegas (no sabe de qué condición viene
cada lista). Escribe resultados/sonda_s2_v2_res.json y imprime el resumen.
Uso (desde esta carpeta): python sonda_s2_v2.py
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
import rank_and_filter as rf

SALIDA = S + "/resultados/sonda_s2_v2_res.json"
POOL = 100
TOP = 10

CADENAS = [
    ("extra_leche_es", "Efecto de la pasteurización UHT en la leche entera y su vida útil",
     '"pasteurización UHT" OR "ultra alta temperatura" OR "tratamiento térmico" OR "procesamiento térmico" OR "esterilización UHT" AND "leche entera" OR "leche fluida" OR "leche cruda"'),
    ("extra_cancer_es", "Tratamientos de cáncer de mama con inmunoterapia",
     '"cáncer de mama" OR "carcinoma mamario" OR "tumor de mama" OR "cáncer de pecho" OR mama AND inmunoterapia OR "inmunoterapia del cáncer" OR "inmunoterapia oncológica"'),
    ("extra_cobots_ambos", "Robots colaborativos en logística y almacenes",
     '"human robot collaboration" OR "colaboración humano robot" OR "colaboración humano-robot" AND "warehouse automation" OR "automatización de almacenes" OR "automatización logística"'),
    ("extra_banano_es", "Harina de banano verde en panificación sin gluten",
     '"harina de banano verde" OR "harina de plátano verde" AND "panificación sin gluten" OR "pan sin gluten" OR panificación'),
    ("extra_infogest_ambos", "Digestibilidad de proteínas de la leche con el modelo INFOGEST",
     'digestibility OR digestibilidad AND "milk protein" OR "proteína de la leche" AND INFOGEST OR "modelo INFOGEST"'),
    ("uht", "Desarrollo y factores de la leche entera UHT",
     '"whole milk" OR milk AND UHT OR "ultra high temperature" AND quality OR "shelf life"'),
    ("uht_2", "Desarrollo y factores de la leche entera UHT",
     '"ultra high temperature" OR "UHT treatment" OR "UHT processing" AND "whole milk" OR "liquid milk"'),
    ("ml_lineal", "Machine Learning y los algoritmos discriminantes lineales",
     '"machine learning" OR "deep learning" OR "artificial intelligence" AND "linear discriminant analysis" OR "discriminant analysis"'),
    ("ml_lineal_2", "Machine Learning y los algoritmos discriminantes lineales",
     '"supervised learning" OR classification OR "pattern recognition" AND "linear classifier" OR "discriminant function"'),
]


def main():
    resultados = []
    for tema, ctx, cadena in CADENAS:
        filas = s2.buscar_semantic_scholar(cadena, config.SEMANTIC_SCHOLAR_API_KEY, 2015, POOL)
        con_doi = [f for f in filas if f["doi"] and f["title"]]
        if not con_doi:
            print(f"[{tema}] 0 resultados (¿429 de Semantic Scholar?)", flush=True)
            resultados.append({"tema": tema, "total": len(filas), "error": "sin resultados"})
            continue
        top_citas = con_doi[:TOP]
        keywords = rf.palabras_clave([cadena])
        reordenado = sorted(con_doi, key=lambda f: rf.score_paper(f, keywords), reverse=True)
        top_local = reordenado[:TOP]
        # el juez puntúa las dos listas por separado (sin saber la condición)
        pts_citas = a.juzgar(ctx, cadena, [f["title"] for f in top_citas])
        pts_local = a.juzgar(ctx, cadena, [f["title"] for f in top_local])
        resultados.append({
            "tema": tema, "total": len(filas), "con_doi": len(con_doi),
            "top_citas": [{"t": f["title"], "c": f["cited_by_count"], "p": p} for f, p in zip(top_citas, pts_citas)],
            "top_local": [{"t": f["title"], "c": f["cited_by_count"], "p": p} for f, p in zip(top_local, pts_local)],
        })
        e_c = sum(1 for p in pts_citas if p == 2); l_c = sum(1 for p in pts_citas if p >= 1)
        e_l = sum(1 for p in pts_local if p == 2); l_l = sum(1 for p in pts_local if p >= 1)
        print(f"[{tema}] pool={len(con_doi):>3}  citas: {e_c}/{len(pts_citas)} estr, {l_c} laxa   "
              f"local: {e_l}/{len(pts_local)} estr, {l_l} laxa", flush=True)
        with open(SALIDA, "w", encoding="utf-8") as f:
            json.dump(resultados, f, ensure_ascii=False, indent=1)

    con_datos = [r for r in resultados if "top_citas" in r]
    if con_datos:
        def suma(cond, minimo):
            return sum(1 for r in con_datos for x in r[cond] if x["p"] >= minimo)
        n_c = sum(len(r["top_citas"]) for r in con_datos)
        n_l = sum(len(r["top_local"]) for r in con_datos)
        print(f"\nGLOBAL  citas: estricta {suma('top_citas', 2)}/{n_c}, laxa {suma('top_citas', 1)}/{n_c}")
        print(f"GLOBAL  local: estricta {suma('top_local', 2)}/{n_l}, laxa {suma('top_local', 1)}/{n_l}")
        # solo cadenas cuyo pool supera el top entregado: ahí el re-rank tiene algo que reordenar
        con_pool = [r for r in con_datos if r["con_doi"] > TOP]
        if con_pool:
            def suma_pool(cond, minimo):
                return sum(1 for r in con_pool for x in r[cond] if x["p"] >= minimo)
            print(f"SOLO POOL>{TOP} ({len(con_pool)} cadenas)  citas: estricta {suma_pool('top_citas', 2)}, "
                  f"laxa {suma_pool('top_citas', 1)}   local: estricta {suma_pool('top_local', 2)}, "
                  f"laxa {suma_pool('top_local', 1)}")
    print("Resultados en", SALIDA, flush=True)


if __name__ == "__main__":
    main()
