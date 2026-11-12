"""Pruebas de estrictez (punto 2 de PENDIENTES.md): hasta dónde puede apretar una
cadena sin perder un paper que se sabe que existe. Sirve para decidir cuántos
grupos AND y cuántas alternativas OR conviene pedirle al modelo.

Metodología (skill research-automator-cadenas):
1. Papers objetivo conocidos: los que ya están guardados en los proyectos de la
   interfaz, guardados en PostgreSQL (tablas proyectos/papers_proyectos/papers, SOLO
   LECTURA), con título y abstract.
2. Por paper se construye una escala de cadenas con los términos del propio paper
   (título y palabras frecuentes del abstract), de la más flexible a la más estricta:
   - L1 flexible:    un grupo con OR (términos del título).
   - L2 dos_grupos:  2 grupos AND con alternativas OR (título + abstract).
   - L3 dos_sueltos: 2 grupos AND de un único término cada uno.
   - L4 tres_sueltos: 3 grupos AND de un único término.
   - L5 frase:       una frase exacta del título AND un término del abstract.
   - L6 estricta:    frase exacta AND término AND NOT review (3 cláusulas + exclusión).
3. Por nivel se registra: si el paper aparece entre los primeros 300 resultados,
   en qué posición y el total de resultados de la cadena.
4. Motor: OpenAlex (el principal; con OPENALEX_API_KEY en .env no da 429). Scopus y
   Semantic Scholar quedan como extensión: cada motor interpreta la sintaxis distinto.

Salida: resultados/estrictez_res.json y una tabla por nivel con: % de papers que
sobreviven, mediana de posición y mediana de resultados. Si en un nivel desaparecen
muchos papers, la generación no debería pedir cadenas tan estrictas.

Uso (desde esta carpeta): python estrictez.py [--papers=N] [--niveles=L1,L2,...]
"""

import argparse
import json
import os
import re
import statistics
import sys

import requests

S = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(os.path.dirname(S))
sys.path.insert(0, os.path.join(RAIZ, "busqueda"))
sys.path.insert(0, S)

import config
import database
import fetch_papers as fp

SALIDA = S + "/resultados/estrictez_res.json"
MAX_RESULTADOS_NIVEL = 300      # hasta aquí se busca al paper objetivo
VACIAS = set("""de del la las el los un una unos unas en con por para sobre entre y o que como
su sus al lo se es son más menos muy the of in on and or for with to from by a an at into
using use used effect effects study studies based approach can be been was were this these
those which their its have has are is not no than then when where other others both each
also may might could would should more most such same only some all one two three per via
after before during while under over above below without within toward towards upon about
across among out up down off again further once here there how what who why toward
through improving improved different various high low new""".split())


def papers_objetivo(cuantos):
    """Papers con título y abstract de los proyectos guardados en PostgreSQL
    (solo lectura), repartidos entre los proyectos que los tengan."""
    papers = []
    conn = database.conectar()
    try:
        proyectos = [f["archivo"] for f in conn.execute("SELECT archivo FROM proyectos ORDER BY archivo")]
        for archivo in proyectos:
            filas = conn.execute(
                "SELECT p.title, p.abstract, p.doi FROM papers p "
                "JOIN papers_proyectos pp ON pp.paper_id = p.paper_id "
                "WHERE pp.archivo = %s AND p.title IS NOT NULL AND length(p.abstract) > 200 "
                "ORDER BY p.cited_by_count DESC NULLS LAST LIMIT 2", (archivo,)).fetchall()
            for f in filas:
                papers.append({"proyecto": archivo, "title": f["title"],
                               "abstract": f["abstract"], "doi": f["doi"]})
    finally:
        conn.close()
    return papers[:cuantos]


def _palabras(texto, n, fuera=()):
    """Las n palabras con contenido más frecuentes del texto, en orden de aparición,
    sin repeticiones y excluyendo `fuera`."""
    conteo, orden = {}, []
    for p in re.findall(r"[^\W\d_]{4,}", (texto or "").lower()):
        if p in VACIAS or p in fuera:
            continue
        if p not in conteo:
            orden.append(p)
        conteo[p] = conteo.get(p, 0) + 1
    ranked = sorted(orden, key=lambda p: (-conteo[p], orden.index(p)))
    return ranked[:n]


def _frase_real(titulo):
    """Primer par de palabras ADYACENTES del título original (frase que de verdad
    aparece en él), con contenido ambas; None si no hay ninguna."""
    brutas = re.findall(r"[^\W\d_]+", titulo or "")
    for a, b in zip(brutas, brutas[1:]):
        if len(a) >= 4 and len(b) >= 4 and a.lower() not in VACIAS and b.lower() not in VACIAS:
            return f"{a.lower()} {b.lower()}"
    return None


def niveles_de(paper):
    """{nivel: cadena} con los términos del propio paper (título y abstract), sin
    repetir un término en la misma cadena."""
    titulo = paper["title"]
    t = _palabras(titulo, 4)                      # términos del título
    a = _palabras(paper["abstract"], 4, fuera=set(t))   # del abstract, sin repetir los del título
    frase = _frase_real(titulo)
    if len(t) < 3 or len(a) < 2 or not frase:
        return {}
    return {
        "L1_flexible": f"{t[0]} OR {t[1]} OR {t[2]}",
        "L2_dos_grupos": f"{t[0]} OR {t[1]} AND {a[0]} OR {a[1]}",
        "L3_dos_sueltos": f"{t[0]} AND {a[0]}",
        "L4_tres_sueltos": f"{t[0]} AND {t[1]} AND {a[0]}",
        "L5_frase": f'"{frase}" AND {a[0]}',
        "L6_estricta": f'"{frase}" AND {a[0]} AND NOT review',
    }


def buscar_y_localizar(cadena, paper):
    """(aparece, posicion, total) del paper objetivo entre los primeros
    MAX_RESULTADOS_NIVEL resultados de la cadena."""
    params = {"filter": fp.construir_filtro(cadena), "per-page": 200,
              "select": "title,doi", "mailto": config.CONTACT_EMAIL}
    if config.OPENALEX_API_KEY:
        params["api_key"] = config.OPENALEX_API_KEY
    doi_pelado = re.sub(r"^https?://(dx\.)?doi\.org/", "", paper["doi"] or "", flags=re.I)
    total, vistos, pagina = 0, 0, 1
    while pagina <= 2:                 # 2 páginas de 200 = hasta 300 resultados
        params["page"] = pagina
        config.esperar_turno()
        try:
            r = requests.get(fp.OPENALEX_URL, params=params, timeout=40)
            if r.status_code != 200:
                return None, None, None
            data = r.json()
        except Exception:
            return None, None, None
        total = data["meta"]["count"]
        works = data.get("results", [])
        if not works:
            break
        for i, w in enumerate(works):
            w_doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", w.get("doi") or "", flags=re.I)
            if (doi_pelado and w_doi == doi_pelado) or \
                    (w.get("title") or "").strip().casefold() == (paper["title"] or "").strip().casefold():
                return True, vistos + i + 1, total
        vistos += len(works)
        if vistos >= min(total, MAX_RESULTADOS_NIVEL) or vistos >= 400:
            break
        pagina += 1
    return False, None, total


def verificar_match(cadena, paper):
    """True/False según si el paper matchea la cadena en OpenAlex, sin límite de
    posición: se pide el filtro de la cadena AND el DOI del paper (si no tiene
    DOI, None). Distingue "no está en el top-300" de "la cadena no lo encuentra"."""
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", paper["doi"] or "", flags=re.I)
    if not doi:
        return None
    params = {"filter": fp.construir_filtro(cadena) + f",doi:{doi}", "per-page": 1,
              "select": "title", "mailto": config.CONTACT_EMAIL}
    if config.OPENALEX_API_KEY:
        params["api_key"] = config.OPENALEX_API_KEY
    config.esperar_turno()
    try:
        r = requests.get(fp.OPENALEX_URL, params=params, timeout=40)
        if r.status_code != 200:
            return None
        return r.json()["meta"]["count"] > 0
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--papers", type=int, default=12)
    parser.add_argument("--niveles", default="", help="subconjunto de niveles separados por coma")
    parser.add_argument("--verificar", action="store_true",
                        help="solo re-verifica los niveles con aparece=False del res guardado: "
                             "¿el paper matchea la cadena (enterrado) o la cadena no lo encuentra?")
    args = parser.parse_args()

    if args.verificar:
        with open(SALIDA, encoding="utf-8") as f:
            resultados = json.load(f)
        for fila in resultados:
            paper = {"title": fila["title"], "doi": fila["doi"]}
            for nivel, info in fila["niveles"].items():
                if info["aparece"] is False and "matchea" not in info:
                    info["matchea"] = verificar_match(info["cadena"], paper)
                    print(f"  [{str(info['matchea']):>5}] matchea sin límite de posición: "
                          f"{nivel:13} {paper['title'][:45]}", flush=True)
        with open(SALIDA, "w", encoding="utf-8") as f:
            json.dump(resultados, f, ensure_ascii=False, indent=1)
        tabla(resultados)
        return

    objetivos = papers_objetivo(args.papers)
    print(f"{len(objetivos)} papers objetivo de {len({p['proyecto'] for p in objetivos})} proyectos", flush=True)
    resultados = []
    for paper in objetivos:
        niveles = niveles_de(paper)
        if args.niveles:
            pedidos = {k: v for k, v in niveles.items() if k in args.niveles.split(",")}
        else:
            pedidos = niveles
        if not pedidos:
            print(f"  [aviso] sin términos suficientes: {paper['title'][:60]}", flush=True)
            continue
        fila = {"proyecto": paper["proyecto"], "title": paper["title"], "doi": paper["doi"],
                "niveles": {}}
        for nivel, cadena in pedidos.items():
            aparece, posicion, total = buscar_y_localizar(cadena, paper)
            fila["niveles"][nivel] = {"cadena": cadena, "aparece": aparece,
                                      "posicion": posicion, "total": total}
            print(f"  [{'ok' if aparece else 'NO' if aparece is False else '??'}] {nivel:13}"
                  f" pos={str(posicion):>5} total={str(total):>6}  {paper['title'][:45]}", flush=True)
        resultados.append(fila)
        with open(SALIDA, "w", encoding="utf-8") as f:
            json.dump(resultados, f, ensure_ascii=False, indent=1)

    tabla(resultados)
    print("Resultados en", SALIDA, flush=True)


def tabla(resultados):
    """Resumen por nivel: top-300, enterrados (matchean pero no en el top-300),
    perdidos (la cadena no los encuentra), posición y total."""
    print(f"\n{'nivel':15}{'top300':>8}{'enterra':>9}{'perdido':>9}{'sin dato':>9}"
          f"{'med. pos':>9}{'med. total':>12}")
    for nivel in sorted({n for r in resultados for n in r["niveles"]}):
        filas = [r["niveles"][nivel] for r in resultados if nivel in r["niveles"]]
        top300 = sum(1 for f in filas if f["aparece"])
        enterrados = sum(1 for f in filas if f["aparece"] is False and f.get("matchea") is True)
        perdidos = sum(1 for f in filas if f["aparece"] is False and f.get("matchea") is False)
        sin_dato = sum(1 for f in filas if f["aparece"] is False and f.get("matchea") is None)
        posiciones = [f["posicion"] for f in filas if f["aparece"]]
        totales = [f["total"] for f in filas if f["total"] is not None]
        print(f"{nivel:15}{top300:>8}{enterrados:>9}{perdidos:>9}{sin_dato:>9}"
              f"{(statistics.median(posiciones) if posiciones else 0):>9.0f}"
              f"{(statistics.median(totales) if totales else 0):>12.0f}")


if __name__ == "__main__":
    main()
