"""Banco de pruebas de amplitud de la búsqueda (pendiente 1 de PENDIENTES.md, fase de ejecución).

Las cadenas generadas con el formato de grupos ya tienen buena estructura; acá se
prueba cómo se EJECUTAN: por qué a veces traen muy pocos papers y con qué variante
se consigue más cantidad sin desviarse del tema ni de la intención del usuario.

Por cada cadena se prueban variantes de ejecución en OpenAlex, con
from_publication_date=2015 (el mismo límite que aplica la interfaz por defecto):

- base:         la cadena tal cual (con su NOT, si lo tiene).
- sin_not:      igual, sin el grupo NOT.
- pares:        cada par de grupos AND positivos por separado (solo con 3 o más
                grupos); los resultados se unen. Hits = suma de los pares (cota
                superior, puede haber solape).
- or:           todas las alternativas de todos los grupos unidas con OR. Es el
                control de amplitud máxima: sirve para ver cuánto se desvía.
- fulltext:     búsqueda en texto completo (default.search) en vez de solo
                título y abstract.
- sin_comillas: las frases exactas se convierten en palabras sueltas.

Métricas por variante: hits (meta.count de OpenAlex) y puntos del juez sobre los
primeros títulos: 0 = desviado, 1 = toca un concepto de la cadena, 2 = trata el
tema o combina varios conceptos. El criterio 0/1/2 es nuevo (el banco.py histórico
usaba relevante/no relevante), así que los números NO son comparables con los
parciales de CONTEXTO.md; la fracción de 2 es lo más parecido al criterio viejo.

El juez es Nemotron (llm_nvidia); las corridas del 2026-10-29/30 usaron GPT-5.5
(Azure, suscripción vencida: los scripts banco.py y azure_prueba.py se borraron,
los resultados que produjeron siguen en resultados/). El acuerdo entre ambos
jueces fue 0,66 exacto: no comparar números de jueces distintos.

Uso (desde esta carpeta, con el venv activado):
    python amplitud.py                        # todos los temas
    python amplitud.py --temas=cancer,banano  # solo algunos (prefijos del nombre)

Escribe resultados/amplitud_res.json (parcial tras cada tema) y un resumen en
consola. Reusa las cadenas ya generadas de resultados/final_res.json (español y
«Ambos»); los temas en inglés se generan con el flujo real (generar_con_info),
que consume llamadas a Nemotron.
"""

import argparse
import json
import os
import re
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(RAIZ, "busqueda"))
S = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, S)

import config
import fetch_papers as fp
import generar_cadenas as g
import limites_motores as lm
import llm_nvidia
MIN_YEAR = 2015
SALIDA = S + "/resultados/amplitud_res.json"

PROMPT_JUEZ = (
    "Eres un revisor de literatura científica. Recibes el TEMA de investigación, la CADENA de búsqueda "
    "con sus conceptos y una lista de títulos de papers. Puntúa cada título: 2 si trata directamente el "
    "tema o combina varios de los conceptos de la cadena; 1 si solo toca un concepto de la cadena; "
    "0 si no se relaciona con el tema ni con los conceptos. "
    'Responde SOLO con JSON {"puntos": [0, 1 o 2 por cada título, en orden]}.'
)

# Temas en inglés: (nombre, tema, número de cadenas). Los de español y «Ambos» salen
# de final_res.json. Los temas salen de proyectos.json (prompt y tema_refinado).
TEMAS_EN = [
    ("uht", "Desarrollo y factores de la leche entera UHT", 5),
    ("ml_lineal", "Machine Learning y los algoritmos discriminantes lineales", 5),
]


def variantes_de(cadena):
    """{nombre: [subqueries]} con las variantes de ejecución de una cadena.
    Las variantes que quedan idénticas entre sí se emiten una sola vez."""
    grupos = lm.parsear(cadena)
    positivos = [terminos for negar, terminos in grupos if not negar]
    salida = {}
    base = lm.unir(grupos)
    sin_not = lm.unir([(False, t) for t in positivos])
    salida["base"] = [base]
    if sin_not != base:
        salida["sin_not"] = [sin_not]
    if len(positivos) >= 3:
        pares = []
        for i in range(len(positivos)):
            for j in range(i + 1, len(positivos)):
                pares.append(lm.unir([(False, positivos[i]), (False, positivos[j])]))
        salida["pares"] = pares
    todo_or = [t for grupo in positivos for t in grupo]
    or_total = lm.unir([(False, todo_or)])
    if or_total not in (base, sin_not):
        salida["or"] = [or_total]
    if len(positivos) > 1:
        salida["fulltext"] = [sin_not]
        salida["sin_comillas"] = [sin_not.replace('"', "")]
    return salida


def buscar_openalex(query, campo="title_and_abstract.search", per_page=10):
    """(hits, primeros títulos) de una query en OpenAlex, o (None, []) si falla
    o viene saturada (429 con espera larga)."""
    filtro = fp.construir_filtro(query)
    if campo != "title_and_abstract.search":
        filtro = filtro.replace("title_and_abstract.search:", campo + ":")
    filtro += f",from_publication_date:{MIN_YEAR}-01-01"
    params = {"filter": filtro, "per-page": per_page, "select": "title",
              "mailto": config.CONTACT_EMAIL}
    for intento in range(3):
        config.esperar_turno()
        try:
            r = requests.get(fp.OPENALEX_URL, params=params, timeout=40)
        except requests.RequestException:
            return None, []
        if r.status_code == 429:
            espera = int(r.headers.get("Retry-After", 5 * (intento + 1)))
            if espera > 30:
                return None, []
            time.sleep(espera)
            continue
        if r.status_code != 200:
            return None, []
        data = r.json()
        return data["meta"]["count"], [w.get("title") for w in data["results"] if w.get("title")]
    return None, []


def juzgar(ctx, cadena, titulos):
    """Puntos 0/1/2 del juez (Nemotron) para cada título (lista vacía si falla)."""
    if not titulos:
        return []
    lista = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(titulos))
    usuario = f"TEMA: {ctx}\n\nCADENA (conceptos): {cadena}\n\nTÍTULOS:\n{lista}"
    for _ in range(3):
        try:
            texto = llm_nvidia.chat_json(PROMPT_JUEZ, usuario, timeout=120)
            puntos = json.loads(texto)["puntos"]
            return [int(x) for x in puntos][: len(titulos)]
        except Exception:
            time.sleep(3)
    return []


def evaluar_cadena(ctx, cadena):
    """Evalúa todas las variantes de una cadena. Devuelve
    {"variantes": {nombre: [sub]}, "juez": "nvidia"}."""
    variantes = {}
    for nombre, subqueries in variantes_de(cadena).items():
        subs = []
        for query in subqueries:
            campo = "default.search" if nombre == "fulltext" else "title_and_abstract.search"
            hits, titulos = buscar_openalex(query, campo=campo)
            puntos = juzgar(ctx, cadena, titulos) if hits else []
            subs.append({"query": query, "hits": hits, "titulos": titulos, "puntos": puntos})
        variantes[nombre] = subs
    return {"cadena": cadena, "variantes": variantes, "juez": "nvidia"}


def resumen_variantes(resultado):
    """{variante: {hits, ceros, saturadas, estricta, laxa}} para un tema."""
    filas = {}
    for cadena in resultado["cadenas"]:
        for nombre, subs in cadena["variantes"].items():
            fila = filas.setdefault(nombre, {"hits": [], "ceros": 0, "saturadas": 0,
                                             "puntos": [], "titulos": 0})
            for sub in subs:
                if sub["hits"] is None:
                    fila["saturadas"] += 1
                    continue
                fila["hits"].append(sub["hits"])
                if sub["hits"] == 0:
                    fila["ceros"] += 1
                fila["puntos"].extend(sub["puntos"])
                fila["titulos"] += len(sub["titulos"])
    salida = {}
    for nombre, fila in filas.items():
        puntos = fila["puntos"]
        salida[nombre] = {
            "n_busquedas": len(fila["hits"]) + fila["saturadas"],
            "hits_mediana": statistics.median(fila["hits"]) if fila["hits"] else None,
            "hits_max": max(fila["hits"]) if fila["hits"] else None,
            "ceros": fila["ceros"],
            "saturadas": fila["saturadas"],
            "estricta": (sum(1 for p in puntos if p == 2) / len(puntos)) if puntos else None,
            "laxa": (sum(1 for p in puntos if p >= 1) / len(puntos)) if puntos else None,
        }
    return salida


def cargar_temas(solo):
    """[(nombre, idioma, ctx, cadenas)] combinando final_res.json y temas en
    inglés generados al momento."""
    temas = []
    final = json.load(open(S + "/resultados/final_res.json", encoding="utf-8"))
    ctx_por_nombre = {}
    for p in json.load(open(S + "/proyectos.json", encoding="utf-8")):
        ctx = (p.get("tema_refinado") or p.get("prompt") or "").strip()
        if p.get("prompt") and p.get("tema_refinado"):
            ctx = f'{p["prompt"].strip()} — {ctx}'
        ctx_por_nombre[p["archivo"][:-3]] = ctx
    for r in final:
        nombre = r["nombre"]
        if solo and not any(nombre.startswith(s) for s in solo):
            continue
        ctx = ctx_por_nombre.get(nombre) or {
            "extra_leche_es": "Efecto de la pasteurización UHT en la leche entera y su vida útil",
            "extra_banano_es": "Harina de banano verde en panificación sin gluten",
            "extra_cancer_es": "Tratamientos de cáncer de mama con inmunoterapia",
            "extra_cobots_ambos": "Robots colaborativos en logística y almacenes",
            "extra_infogest_ambos": "Digestibilidad de proteínas de la leche con el modelo INFOGEST",
        }.get(nombre, nombre)
        temas.append((nombre, r["idioma"], ctx, r["cadenas"]))
    for nombre, tema, n in TEMAS_EN:
        if solo and not any(nombre.startswith(s) for s in solo):
            continue
        cadenas, aviso, _ = g.generar_con_info(tema, n, "en")
        if aviso:
            print(f"  [aviso] {nombre}: {aviso}", flush=True)
        temas.append((nombre, "en", tema, cadenas))
    return temas


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--temas", default="", help="prefijos de temas separados por coma")
    parser.add_argument("--hilos", type=int, default=4)
    args = parser.parse_args()
    solo = [s.strip() for s in args.temas.split(",") if s.strip()]

    temas = cargar_temas(solo)
    print(f"{len(temas)} temas, {sum(len(t[3]) for t in temas)} cadenas; juez: nvidia", flush=True)

    resultados = []
    if os.path.exists(SALIDA):
        with open(SALIDA, encoding="utf-8") as f:
            resultados = json.load(f)
    hechos = {r["tema"] for r in resultados}

    for nombre, idioma, ctx, cadenas in temas:
        if nombre in hechos:
            continue
        print(f"\n== {nombre} ({idioma}, {len(cadenas)} cadenas)", flush=True)
        with ThreadPoolExecutor(args.hilos) as ex:
            cadenas_res = list(ex.map(lambda c: evaluar_cadena(ctx, c), cadenas))
        resultados.append({"tema": nombre, "idioma": idioma, "ctx": ctx,
                           "cadenas": cadenas_res, "resumen": resumen_variantes(
                               {"cadenas": cadenas_res})})
        with open(SALIDA, "w", encoding="utf-8") as f:
            json.dump(resultados, f, ensure_ascii=False, indent=1)

    print("\n{:14}{:>10}{:>8}{:>7}{:>9}{:>9}{:>9}{:>9}".format(
        "variante", "mediana", "max", "ceros", "satur.", "estricta", "laxa", "busq."),
          flush=True)
    por_variante = {}
    for r in resultados:
        for nombre, fila in r["resumen"].items():
            acum = por_variante.setdefault(nombre, {"hits": [], "ceros": 0, "saturadas": 0,
                                                    "puntos": [], "busq": 0})
            if fila["hits_mediana"] is not None:
                acum["hits"].append(fila["hits_mediana"])
            acum["ceros"] += fila["ceros"]
            acum["saturadas"] += fila["saturadas"]
            acum["busq"] += fila["n_busquedas"]
            n = len(r["cadenas"])
    tot_puntos = {}
    for r in resultados:
        for cadena in r["cadenas"]:
            for nombre, subs in cadena["variantes"].items():
                puntos = tot_puntos.setdefault(nombre, [])
                for sub in subs:
                    puntos.extend(sub["puntos"])
    for nombre, acum in sorted(por_variante.items()):
        puntos = tot_puntos.get(nombre, [])
        med = statistics.median(acum["hits"]) if acum["hits"] else None
        estricta = sum(1 for p in puntos if p == 2) / len(puntos) if puntos else None
        laxa = sum(1 for p in puntos if p >= 1) / len(puntos) if puntos else None
        print("{:14}{:>10}{:>8}{:>7}{:>9}{:>9.2f}{:>9.2f}{:>9}".format(
            nombre, str(med), str(max(acum["hits"]) if acum["hits"] else None),
            acum["ceros"], acum["saturadas"],
            estricta if estricta is not None else -1, laxa if laxa is not None else -1,
            acum["busq"]), flush=True)
    print(f"\nResultados en {SALIDA}", flush=True)


if __name__ == "__main__":
    main()
