"""
Pruebas de estrictez por motor (Scopus y Semantic Scholar).

Versión reducida de estrictez.py (que solo cubre OpenAlex): para cada paper objetivo
de los proyectos guardados en PostgreSQL (solo lectura) arma los 6 niveles de
restricción con sus propios términos y mide, en cada motor, si el paper aparece entre
los primeros MAX_RESULTADOS resultados y en qué posición. No distingue "enterrado" de
"perdido" (eso exigiría un filtro por DOI propio de cada motor).

Uso (desde la raíz, venv activo):  python pruebas/cadenas/estrictez_motores.py [--papers 6]
Consume cuota de Scopus y de Semantic Scholar. Resultados en
resultados/estrictez_motores_res.json.
"""

import argparse
import json
import os
import statistics
import sys

S = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(os.path.dirname(S))
sys.path.insert(0, os.path.join(RAIZ, "busqueda"))
sys.path.insert(0, S)

import config
import doi as doi_util
import estrictez
import fetch_scopus
import fetch_semantic_scholar

SALIDA = S + "/resultados/estrictez_motores_res.json"
MAX_RESULTADOS = 100


def _buscadores():
    return {
        "scopus": lambda q: fetch_scopus.buscar_scopus(q, config.SCOPUS_API_KEY, None, MAX_RESULTADOS),
        "semantic_scholar": lambda q: fetch_semantic_scholar.buscar_semantic_scholar(
            q, config.SEMANTIC_SCHOLAR_API_KEY, None, MAX_RESULTADOS),
    }


def localizar(resultados, paper):
    """Posición (1 = primero) del paper objetivo por DOI o, si no, por título; None si no está."""
    objetivo = doi_util.normalizar(paper["doi"]) if paper["doi"] else None
    titulo = (paper["title"] or "").strip().casefold()
    for i, r in enumerate(resultados, 1):
        d = doi_util.normalizar(r.get("doi")) if r.get("doi") else None
        if (objetivo and d == objetivo) or (r.get("title") or "").strip().casefold() == titulo:
            return i
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--papers", type=int, default=6)
    args = parser.parse_args()
    buscadores = _buscadores()
    resultados = []
    for paper in estrictez.papers_objetivo(args.papers):
        niveles = estrictez.niveles_de(paper)
        if not niveles:
            continue
        fila = {"title": paper["title"], "doi": paper["doi"], "motores": {}}
        for motor, buscar in buscadores.items():
            fila["motores"][motor] = {}
            for nivel, cadena in niveles.items():
                try:
                    lista = buscar(cadena) or []
                    pos, total = localizar(lista, paper), len(lista)
                except Exception as exc:
                    pos, total = None, None
                    print(f"  [aviso] {motor} {nivel}: {type(exc).__name__}", flush=True)
                fila["motores"][motor][nivel] = {"cadena": cadena, "posicion": pos, "devueltos": total}
                print(f"  {motor:17}{nivel:16} pos={str(pos):>5} devueltos={str(total):>5}  {paper['title'][:40]}",
                      flush=True)
        resultados.append(fila)
        with open(SALIDA, "w", encoding="utf-8") as f:
            json.dump(resultados, f, ensure_ascii=False, indent=1)
    resumen(resultados)


def resumen(resultados):
    print(f"\n{'motor':18}{'nivel':16}{'aparece':>8}{'sin dato':>9}{'med. pos':>9}{'med. devueltos':>15}")
    for motor in ("scopus", "semantic_scholar"):
        niveles = sorted({n for r in resultados for n in r["motores"].get(motor, {})})
        for nivel in niveles:
            filas = [r["motores"][motor][nivel] for r in resultados if nivel in r["motores"].get(motor, {})]
            validas = [f for f in filas if f["devueltos"] is not None]
            pos = [f["posicion"] for f in validas if f["posicion"]]
            dev = [f["devueltos"] for f in validas]
            print(f"{motor:18}{nivel:16}{len(pos):>5}/{len(validas):<2}{len(filas) - len(validas):>9}"
                  f"{(statistics.median(pos) if pos else 0):>9.0f}{(statistics.median(dev) if dev else 0):>15.0f}")


if __name__ == "__main__":
    main()
