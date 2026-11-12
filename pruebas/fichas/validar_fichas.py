"""
Validación de las fichas del procesamiento contra la intención de cada proyecto.

Para cada proyecto guardado en la base (tabla `proyectos`):

1. Toma los papers seleccionados por el usuario. Si el proyecto no tiene
   selección y se pasa `--muestra N`, usa los N primeros del ranking más
   `--control K` del final del ranking (grupo de control: deberían salir
   menos relevantes).
2. Genera sus fichas con el flujo real (`extract_ficha.procesar`, con el tema
   refinado del proyecto). Las fichas que ya existen con la versión vigente
   del prompt no se regeneran.
3. Valida cada ficha:
   - Estructura: campos presentes, largos razonables, topes de las listas.
   - Cifras: todo número citado en los hallazgos debe aparecer en el texto
     que recibió el modelo (detecta datos inventados).
   - Relevancia: un juez Nemotron independiente, que solo ve el tema, el
     título y el abstract (no la ficha), asigna su propia relevancia; se mide
     el acuerdo con la de la ficha.
   - Fidelidad: el juez compara la ficha con el texto fuente y dice si sus
     afirmaciones están respaldadas y si el «aporte al tema» responde a lo que
     busca el proyecto.

Escribe `resultados/validar_<archivo>.json` e imprime un resumen con los
criterios de aprobación. Consume NVIDIA (Nemotron Parse para los PDFs nuevos
y ~2 llamadas de juez por cada 8 papers).

    cd pruebas/fichas
    ../../venv/bin/python validar_fichas.py                         # solo selecciones
    ../../venv/bin/python validar_fichas.py --muestra 10 --control 5
    ../../venv/bin/python validar_fichas.py --sin-procesar          # valida lo ya generado
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(os.path.dirname(AQUI))
sys.path.insert(0, os.path.join(RAIZ, "procesamiento"))

import config_proc  # noqa: E402,F401  (agrega ../busqueda a la ruta de importación)
import database_proc  # noqa: E402
import extract_ficha  # noqa: E402
import llm_nvidia  # noqa: E402

NIVELES = extract_ficha.NIVELES_RELEVANCIA            # alta, media, baja, nula
PUNTOS = {"alta": 3, "media": 2, "baja": 1, "nula": 0}
LOTE_JUEZ = 8
MAX_CARACTERES_FUENTE = 3000

# Criterios de aprobación (proporción mínima sobre las fichas validadas)
CRITERIOS = {
    "estructura_ok": 0.90,
    "cifras_respaldadas": 0.90,
    "acuerdo_util_vs_no_util": 0.80,
    "acuerdo_a_un_nivel": 0.85,
    "afirmaciones_respaldadas": 0.90,
    "aporte_responde_al_tema": 0.85,
}

SISTEMA_JUEZ_RELEVANCIA = """Eres un evaluador experto de revisiones de literatura. Recibirás el TEMA
de una investigación y varios papers (P1, P2...) con su título y su abstract. Para cada paper decide
qué tan útil es para ese tema:
  "alta"  = trata directamente el tema (mismo problema, población o método central);
  "media" = trata una parte importante del tema o un caso muy cercano;
  "baja"  = solo toca el tema de forma tangencial o sirve como contexto general;
  "nula"  = no tiene relación con el tema.
Responde SOLO con JSON: {"papers": [{"paper_ref": "P1", "relevancia": "...", "motivo": "una frase"}]}"""

SISTEMA_JUEZ_FIDELIDAD = """Eres un revisor que verifica fichas de lectura de papers científicos. Recibirás
el TEMA de una investigación y, para cada paper (P1, P2...), el TEXTO FUENTE que se le dio al
redactor y la FICHA que escribió. Para cada paper responde:
- respaldada: true si todas las afirmaciones de la ficha (frase, hallazgos, conclusiones) se apoyan en
  el texto fuente; false si alguna inventa o distorsiona datos.
- aporte_responde: true si el campo "aporte_al_tema" explica algo útil y concreto para el TEMA (o si
  es null porque el paper no tiene relación); false si es genérico, no tiene que ver con el tema o
  exagera la relación.
- problema: una frase con el problema encontrado, o null.
Responde SOLO con JSON: {"papers": [{"paper_ref": "P1", "respaldada": true, "aporte_responde": true,
"problema": null}]}"""


# ------------------------------------------------------------------ datos

def proyectos(conn, filtro=None):
    filas = conn.execute("SELECT archivo, estado FROM proyectos ORDER BY archivo").fetchall()
    return [f for f in filas if not filtro or f["archivo"] == filtro]


def tema_de(estado):
    estado = estado or {}
    return (estado.get("tema_refinado") or estado.get("prompt") or "").strip()


def papers_a_validar(conn, archivo, muestra, control):
    """[(paper_id, grupo)]: la selección o, si no hay y se pidió, una muestra."""
    sel = conn.execute("SELECT paper_id FROM papers_proyectos WHERE archivo = %s AND seleccionado = 1 "
                       "ORDER BY orden", (archivo,)).fetchall()
    if sel:
        return [(f["paper_id"], "seleccion") for f in sel]
    if not muestra:
        return []
    todos = [f["paper_id"] for f in conn.execute(
        "SELECT paper_id FROM papers_proyectos WHERE archivo = %s ORDER BY orden", (archivo,)).fetchall()]
    top = todos[:muestra]
    fondo = [p for p in todos[-control:] if p not in top] if control else []
    return [(p, "top") for p in top] + [(p, "control") for p in fondo]


def cargar(conn, ids):
    filas = conn.execute("""
        SELECT p.paper_id, p.title, p.abstract, f.estado, f.cobertura, f.ficha_json, e.estructura_json
        FROM papers p
        LEFT JOIN fichas f ON f.paper_id = p.paper_id
        LEFT JOIN estructuras e ON e.paper_id = p.paper_id AND e.estado = 'ok'
        WHERE p.paper_id = ANY(%s)""", (ids,)).fetchall()
    return {f["paper_id"]: f for f in filas}


# ------------------------------------------------------- validación local

RE_NUMERO = re.compile(r"\d+(?:[.,]\d+)?")
RE_REF_LOTE = re.compile(r"\bP\d{1,2}\b")


def _normalizar_numeros(texto):
    # 0,85 y 0.85 cuentan igual; se quitan separadores de miles del tipo 1 200
    return re.sub(r"(?<=\d),(?=\d)", ".", texto or "")


def cifras_sin_respaldo(ficha, fuente):
    """Números de los hallazgos que no aparecen en el texto fuente. Se ignoran
    los de un solo dígito (numeraciones, "dos grupos")."""
    fuente_n = _normalizar_numeros(fuente)
    faltan = []
    for h in ficha.get("hallazgos_clave") or []:
        for num in RE_NUMERO.findall(_normalizar_numeros(h)):
            if len(num.replace(".", "")) >= 2 and num not in fuente_n:
                faltan.append(num)
    return faltan


def problemas_estructura(ficha):
    p = []
    frase = ficha.get("en_una_frase") or ""
    n = len(frase.split())
    if not frase:
        p.append("sin en_una_frase")
    elif not 8 <= n <= 45:
        p.append(f"en_una_frase de {n} palabras")
    if ficha.get("relevancia") not in NIVELES:
        p.append("relevancia fuera de la escala (ficha con esquema antiguo)")
    if not ficha.get("motivo_relevancia"):
        p.append("sin motivo_relevancia")
    if ficha.get("relevancia") != "nula" and not ficha.get("aporte_al_tema"):
        p.append("sin aporte_al_tema siendo relevante")
    for campo, tope in (("hallazgos_clave", 4), ("conclusiones", 3), ("limitaciones", 3)):
        if len(ficha.get(campo) or []) > tope:
            p.append(f"{campo} con más de {tope}")
    if not (ficha.get("metodo") or {}).get("tipo_estudio"):
        p.append("sin tipo de estudio")
    # La ficha no debe nombrar a los otros papers del lote (P1, P2...)
    textos = [ficha.get(k) or "" for k in ("en_una_frase", "motivo_relevancia", "aporte_al_tema", "objetivo")]
    textos += (ficha.get("hallazgos_clave") or []) + (ficha.get("conclusiones") or [])
    if any(RE_REF_LOTE.search(t) for t in textos):
        p.append("menciona otro paper del lote (P1, P2...)")
    return p


# ------------------------------------------------------------------ jueces

def _juez(sistema, tema, bloques):
    """Llama al juez por lotes. `bloques` = [(ref, texto)]. Devuelve {ref: dict}."""
    salida = {}
    for i in range(0, len(bloques), LOTE_JUEZ):
        lote = bloques[i:i + LOTE_JUEZ]
        mensaje = f"TEMA: {tema}\n\n" + "\n\n".join(f"=== {ref} ===\n{texto}" for ref, texto in lote)
        try:
            datos = json.loads(llm_nvidia.chat_json(sistema, mensaje, max_tokens=4000))
        except Exception as exc:          # un lote fallido no tumba la validación
            print(f"  [juez] lote fallido: {str(exc)[:120]}")
            continue
        for p in datos.get("papers", []):
            salida[str(p.get("paper_ref", "")).strip()] = p
    return salida


def _nivel(valor):
    texto = str(valor or "").strip().lower().translate(str.maketrans("áéíóú", "aeiou")).strip(".")
    return texto if texto in NIVELES else None


# --------------------------------------------------------------- principal

def validar_proyecto(conn, proyecto, args):
    archivo, tema = proyecto["archivo"], tema_de(proyecto["estado"])
    print(f"\n=== Proyecto {archivo}\nTema: {tema}")
    objetivo = papers_a_validar(conn, archivo, args.muestra, args.control)
    if not objetivo:
        print("  Sin papers seleccionados: se omite (marca papers en la interfaz o usa --muestra N).")
        return None
    grupos = dict(objetivo)
    ids = [p for p, _ in objetivo]
    origen = "selección del usuario" if objetivo[0][1] == "seleccion" else \
        f"muestra: {sum(g == 'top' for g in grupos.values())} del tope + {sum(g == 'control' for g in grupos.values())} de control"
    print(f"  {len(ids)} papers ({origen})")

    if not args.sin_procesar:
        conteo = extract_ficha.procesar(conn, paper_ids=ids, tema=tema, forzar=args.forzar)
        print(f"  Procesamiento: {conteo}")

    datos = cargar(conn, ids)
    fichas, sin_ficha = {}, []
    for pid in ids:
        fila = datos.get(pid)
        if fila and fila["estado"] in ("ok", "no_relevante") and fila["ficha_json"]:
            fichas[pid] = fila
        else:
            sin_ficha.append({"paper_id": pid, "estado": (fila or {}).get("estado") or "pendiente"})
    if not fichas:
        print("  No hay fichas para validar.")
        return {"archivo": archivo, "tema": tema, "sin_ficha": sin_ficha}

    refs = {f"P{i}": pid for i, pid in enumerate(fichas, 1)}
    fuentes = {pid: extract_ficha.texto_paper(f, f["estructura_json"]) for pid, f in fichas.items()}

    print("  Juez de relevancia (ciego a la ficha)…")
    rel_juez = _juez(SISTEMA_JUEZ_RELEVANCIA, tema, [
        (ref, f"Título: {fichas[pid]['title']}\nAbstract: {(fichas[pid]['abstract'] or '')[:MAX_CARACTERES_FUENTE]}")
        for ref, pid in refs.items()])
    print("  Juez de fidelidad…")
    campos_ficha = ("en_una_frase", "relevancia", "motivo_relevancia", "aporte_al_tema", "hallazgos_clave",
                    "conclusiones")
    fid_juez = _juez(SISTEMA_JUEZ_FIDELIDAD, tema, [
        (ref, f"TEXTO FUENTE:\n{fuentes[pid][:MAX_CARACTERES_FUENTE * 2]}\n\nFICHA:\n"
              + json.dumps({k: fichas[pid]["ficha_json"].get(k) for k in campos_ficha}, ensure_ascii=False))
        for ref, pid in refs.items()])

    detalle = []
    for ref, pid in refs.items():
        ficha = fichas[pid]["ficha_json"]
        juez_r, juez_f = rel_juez.get(ref) or {}, fid_juez.get(ref) or {}
        nivel_f, nivel_j = _nivel(ficha.get("relevancia")), _nivel(juez_r.get("relevancia"))
        detalle.append({
            "paper_id": pid, "grupo": grupos[pid], "titulo": fichas[pid]["title"],
            "cobertura": fichas[pid]["cobertura"],
            "relevancia_ficha": nivel_f, "motivo_ficha": ficha.get("motivo_relevancia"),
            "relevancia_juez": nivel_j, "motivo_juez": juez_r.get("motivo"),
            "en_una_frase": ficha.get("en_una_frase"), "aporte_al_tema": ficha.get("aporte_al_tema"),
            "problemas_estructura": problemas_estructura(ficha),
            "cifras_sin_respaldo": cifras_sin_respaldo(ficha, fuentes[pid]),
            "respaldada": juez_f.get("respaldada"), "aporte_responde": juez_f.get("aporte_responde"),
            "problema_fidelidad": juez_f.get("problema"),
        })

    def proporcion(valores):
        valores = [v for v in valores if v is not None]
        return round(sum(valores) / len(valores), 3) if valores else None

    pares = [(d["relevancia_ficha"], d["relevancia_juez"]) for d in detalle
             if d["relevancia_ficha"] and d["relevancia_juez"]]
    util = {"alta", "media"}
    metricas = {
        "fichas_validadas": len(detalle),
        "estructura_ok": proporcion([not d["problemas_estructura"] for d in detalle]),
        "cifras_respaldadas": proporcion([not d["cifras_sin_respaldo"] for d in detalle]),
        "acuerdo_exacto": proporcion([a == b for a, b in pares]),
        "acuerdo_a_un_nivel": proporcion([abs(PUNTOS[a] - PUNTOS[b]) <= 1 for a, b in pares]),
        "acuerdo_util_vs_no_util": proporcion([(a in util) == (b in util) for a, b in pares]),
        "afirmaciones_respaldadas": proporcion([d["respaldada"] for d in detalle]),
        "aporte_responde_al_tema": proporcion([d["aporte_responde"] for d in detalle]),
        "utiles_segun_ficha": proporcion([d["relevancia_ficha"] in util for d in detalle]),
        "utiles_segun_juez": proporcion([d["relevancia_juez"] in util for d in detalle if d["relevancia_juez"]]),
        "matriz_ficha_vs_juez": {a: {b: sum(1 for x, y in pares if x == a and y == b) for b in NIVELES}
                                 for a in NIVELES},
    }
    for grupo in ("seleccion", "top", "control"):
        puntos = [PUNTOS[d["relevancia_ficha"]] for d in detalle if d["grupo"] == grupo and d["relevancia_ficha"]]
        if puntos:
            metricas[f"relevancia_media_{grupo}"] = round(sum(puntos) / len(puntos), 2)
    veredicto = {c: (metricas.get(c) is not None and metricas[c] >= minimo) for c, minimo in CRITERIOS.items()}

    resultado = {"archivo": archivo, "tema": tema, "fecha": datetime.now().isoformat(timespec="seconds"),
                 "version_ficha": extract_ficha.VERSION_FICHA, "origen_papers": origen, "criterios": CRITERIOS,
                 "metricas": metricas, "veredicto": veredicto, "detalle": detalle, "sin_ficha": sin_ficha}
    imprimir(resultado)
    return resultado


def imprimir(r):
    m = r["metricas"]
    print(f"\n  Fichas validadas: {m['fichas_validadas']}  (sin ficha: {len(r['sin_ficha'])})")
    for criterio, minimo in r["criterios"].items():
        valor = m.get(criterio)
        marca = "PASA " if r["veredicto"][criterio] else "FALLA"
        print(f"  {marca} {criterio:<26} {valor if valor is not None else '-':>6}  (mínimo {minimo})")
    print(f"  Acuerdo exacto de nivel: {m['acuerdo_exacto']}  ·  útiles según ficha {m['utiles_segun_ficha']}"
          f" / según juez {m['utiles_segun_juez']}")
    for grupo in ("seleccion", "top", "control"):
        if f"relevancia_media_{grupo}" in m:
            print(f"  Relevancia media del grupo {grupo}: {m[f'relevancia_media_{grupo}']} (0 = nula, 3 = alta)")
    print("\n  Ficha vs juez por paper:")
    for d in r["detalle"]:
        alerta = []
        if d["relevancia_ficha"] != d["relevancia_juez"]:
            alerta.append("≠juez")
        if d["problemas_estructura"]:
            alerta.append("estructura")
        if d["cifras_sin_respaldo"]:
            alerta.append(f"cifras {d['cifras_sin_respaldo']}")
        if d["respaldada"] is False or d["aporte_responde"] is False:
            alerta.append("fidelidad")
        print(f"   [{d['grupo'][:3]}] {str(d['relevancia_ficha']):<5} / {str(d['relevancia_juez']):<5} "
              f"{(d['titulo'] or '')[:62]:<62} {' '.join(alerta)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--proyecto", help="archivo del proyecto (por defecto, todos)")
    parser.add_argument("--muestra", type=int, default=0,
                        help="si un proyecto no tiene selección, validar los N primeros del ranking")
    parser.add_argument("--control", type=int, default=5, help="papers del final del ranking como control (con --muestra)")
    parser.add_argument("--sin-procesar", action="store_true", help="no generar fichas: validar las existentes")
    parser.add_argument("--forzar", action="store_true", help="regenerar las fichas aunque existan")
    args = parser.parse_args()
    if not args.sin_procesar and not extract_ficha.verificar_configuracion():
        return
    os.makedirs(os.path.join(AQUI, "resultados"), exist_ok=True)
    conn = database_proc.conectar()
    try:
        lista = proyectos(conn, args.proyecto)
        if not lista:
            print("No hay proyectos en la base.")
        for proyecto in lista:
            resultado = validar_proyecto(conn, proyecto, args)
            if resultado:
                ruta = os.path.join(AQUI, "resultados", f"validar_{proyecto['archivo']}.json")
                with open(ruta, "w", encoding="utf-8") as fh:
                    json.dump(resultado, fh, ensure_ascii=False, indent=2)
                print(f"\n  Resultado guardado en {os.path.relpath(ruta, RAIZ)}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
