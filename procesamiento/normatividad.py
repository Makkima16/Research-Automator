"""
Normatividad: delimita las decisiones de diseño y proceso con los límites
legales de normas.csv (tabla `normas` de selema.db).

    python normatividad.py                                    # cumplimiento de hallazgos y productos
    python normatividad.py --matriz leche_liquida --tratamiento_termico uht
    python normatividad.py --matriz leche_liquida --nivel_grasa entera --todas

Cada requisito (`norma_id`) agrupa una o varias filas del CSV. Dentro de una
misma `alternativa` se deben cumplir todos los parámetros; entre alternativas
basta una (ej. pasteurización lenta 63 °C/30 min O rápida 72 °C/15 s).

Un requisito se evalúa contra un hallazgo o un producto solo si sus filtros
(matriz, tratamiento térmico, nivel de grasa, especie) coinciden y hay al menos un dato:
- cumple:     alguna alternativa tiene todos sus datos dentro del rango.
- no_cumple:  todas las alternativas tienen algún dato fuera de rango.
- sin_dato:   ningún dato fuera de rango, pero faltan datos para confirmarlo.

Solo se evalúan las jurisdicciones de config.JURISDICCIONES_NORMAS (--todas
muestra también las de referencia). Las filas con verificado = no se
transcribieron sin confirmar contra el texto oficial: revísalas antes de
usarlas para decidir.
"""

import argparse
import os

import pandas as pd

import config_proc as config
import database_proc as database
from esquema import Observacion

FILTROS = ["matriz", "tratamiento_termico", "nivel_grasa", "especie_leche"]
SIN_VALOR = (None, "", "no_especificado")

# Margen relativo al comparar con un límite: los tiempos del CSV están
# redondeados (2 s = 0.0333 min) y los del LLM también (0.033)
TOLERANCIA = 0.02

# Ningún tratamiento térmico ocurre por debajo de esta temperatura: si un
# hallazgo trae temperatura_c menor, es de almacenamiento, no de proceso
MAX_TEMPERATURA_ALMACENAMIENTO_C = 50

# Columnas del USDA (por 100 g) -> parámetro de la norma. Ojo: la norma suele
# expresar la grasa en % m/v y el USDA en g/100 g (m/m); en leche la diferencia
# es ~3 % del valor (densidad ~1.03), menor que el margen de la mayoría de límites.
PARAMETROS_USDA = {"fat_g": "grasa_pct", "protein_g": "proteina_pct"}


def _vacio(valor):
    return valor is None or valor != valor or valor == ""  # None, NaN o texto vacío


def leer(conn, todas=False):
    normas = pd.read_sql("SELECT * FROM normas", conn)
    if not todas:
        normas = normas[normas["jurisdiccion"].isin(config.JURISDICCIONES_NORMAS)]
    return normas


def rango(fila):
    """'72–76 °C', '≥ 3 % m/v', '≤ 6 °C' o '' si no tiene límite numérico."""
    unidad = f" {fila['unidad']}" if not _vacio(fila["unidad"]) else ""
    minimo, maximo = fila["minimo"], fila["maximo"]
    if not _vacio(minimo) and not _vacio(maximo):
        return f"{minimo:g}{unidad}" if minimo == maximo else f"{minimo:g}–{maximo:g}{unidad}"
    if not _vacio(minimo):
        return f"≥ {minimo:g}{unidad}"
    if not _vacio(maximo):
        return f"≤ {maximo:g}{unidad}"
    return ""


def aplica(fila, perfil, excluidos=None, modo="estricto"):
    """¿Aplica esta fila de la norma a un perfil {campo: valor}?

    - estricto:  cada filtro de la norma coincide con el perfil (para evaluar
                 datos: si el hallazgo no dice su tratamiento, no se evalúa).
    - relevante: ningún filtro contradice al perfil y al menos uno coincide,
                 sin contar la especie (requisitos que una regla del árbol
                 activa explícitamente).
    - posible:   ningún filtro contradice al perfil (todo lo que podría aplicar,
                 incluidas las normas generales como BPM o rotulado).
    `excluidos` = {campo: {valores}} para condiciones "≠" de las reglas.
    """
    excluidos = excluidos or {}
    coincide = False
    for campo in FILTROS:
        filtro = fila[campo]
        if _vacio(filtro):
            continue
        if filtro in excluidos.get(campo, ()):
            return False
        valor = perfil.get(campo)
        if valor in SIN_VALOR:
            if modo == "estricto":
                return False
        elif valor != filtro:
            return False
        elif campo != "especie_leche":  # la especie sola no activa un requisito (casi todo es de vaca)
            coincide = True
    return coincide if modo == "relevante" else True


def filtrar(normas, perfil, excluidos=None, modo="estricto"):
    """Filas de `normas` que aplican al perfil (ver `aplica`)."""
    mascara = [aplica(f, perfil, excluidos, modo) for _, f in normas.iterrows()]
    return normas.loc[pd.Series(mascara, index=normas.index, dtype=bool)]


def evaluar(normas, perfil, valores):
    """Evalúa los requisitos numéricos que aplican al perfil con los `valores`
    {parametro: número}. Devuelve una lista de dicts, uno por requisito con
    al menos un dato."""
    numericas = normas[(normas["parametro"] != "requisito")
                       & (normas["minimo"].notna() | normas["maximo"].notna())]
    numericas = filtrar(numericas, perfil)
    resultados = []
    for norma_id, grupo in numericas.groupby("norma_id", sort=False):
        if all(_vacio(valores.get(p)) for p in grupo["parametro"]):
            continue
        estados, detalles = [], []
        for alternativa, filas in grupo.groupby(grupo["alternativa"].fillna(""), sort=False):
            fuera, falta = [], False
            for _, f in filas.iterrows():
                v = valores.get(f["parametro"])
                if _vacio(v):
                    falta = True
                elif ((not _vacio(f["minimo"]) and v < f["minimo"] - abs(f["minimo"]) * TOLERANCIA)
                      or (not _vacio(f["maximo"]) and v > f["maximo"] + abs(f["maximo"]) * TOLERANCIA)):
                    fuera.append(f"{f['parametro']}={v:g} fuera de {rango(f)}")
            prefijo = f"{alternativa}: " if alternativa else ""
            if fuera:
                estados.append("no_cumple")
                detalles.append(prefijo + ", ".join(fuera))
            elif falta:
                estados.append("sin_dato")
            else:
                estados.append("cumple")
                detalles.append(prefijo + "dentro del rango")
        estado = ("cumple" if "cumple" in estados else
                  "no_cumple" if all(e == "no_cumple" for e in estados) else "sin_dato")
        primera = grupo.iloc[0]
        resultados.append({
            "norma_id": norma_id, "jurisdiccion": primera["jurisdiccion"], "norma": primera["norma"],
            "estado": estado, "detalle": " | ".join(detalles),
            "verificado": primera["verificado"] == "si",
        })
    return resultados


def estado_general(resultados):
    estados = {r["estado"] for r in resultados}
    if "no_cumple" in estados:
        return "fuera_de_norma"
    if "cumple" in estados:
        return "cumple"
    return "sin_datos"


PARAMETROS_OBS = [c for c in Observacion.model_fields
                  if Observacion.model_fields[c].annotation in (float | None, int | None)]


def valores_hallazgo(fila):
    valores = {p: fila[p] for p in PARAMETROS_OBS}
    if fila.get("categoria_factor") == "estres_ambiental":
        valores["temperatura_c"] = None  # es la temperatura del ambiente de las vacas, no de la leche
    t = valores["temperatura_c"]
    if not _vacio(t) and t < MAX_TEMPERATURA_ALMACENAMIENTO_C:
        valores["temperatura_almacenamiento_c"], valores["temperatura_c"] = t, None
    return valores


def evaluar_hallazgos(tabla, normas):
    """Agrega a la tabla del árbol `estado_normativo` (cumple / fuera_de_norma /
    sin_datos) y `detalle_normativo` (qué requisito y qué valor falla)."""
    estados, detalles = [], []
    for _, fila in tabla.iterrows():
        resultados = evaluar(normas, fila.to_dict(), valores_hallazgo(fila))
        estados.append(estado_general(resultados))
        detalles.append("; ".join(f"{r['norma_id']} {r['estado']}"
                                  + (f" ({r['detalle']})" if r["estado"] == "no_cumple" else "")
                                  for r in resultados) or None)
    return tabla.assign(estado_normativo=estados, detalle_normativo=detalles)


def perfil_usda(producto):
    """Traduce un producto del USDA al vocabulario de las normas (el de los papers)."""
    matriz = next((m for m, tipos in database.EQUIV_MATRIZ.items() if producto["tipo_producto"] in tipos), None)
    tratamiento = next((t for t, us in database.EQUIV_TRATAMIENTO.items()
                        if producto["tratamiento_termico"] in us), None)
    return {"matriz": matriz, "tratamiento_termico": tratamiento, "nivel_grasa": producto["nivel_grasa"],
            "especie_leche": producto["especie_leche"]}


def evaluar_productos(conn, normas, subtipos=database.SUBTIPOS_COMPARABLES):
    """Composición de los productos del mercado frente a los límites legales
    (por ejemplo, si una leche 'whole' alcanza la grasa mínima de leche entera)."""
    productos = pd.read_sql(
        f"SELECT fdc_id, description, brand_owner, tipo_producto, subtipo, tratamiento_termico, nivel_grasa, especie_leche, "
        f"{', '.join(PARAMETROS_USDA)}, url_fuente FROM alimentos_usda "
        f"WHERE subtipo IN ({', '.join('?' for _ in subtipos)})", conn, params=list(subtipos))
    filas = []
    for _, p in productos.iterrows():
        resultados = evaluar(normas, perfil_usda(p), {par: p[col] for col, par in PARAMETROS_USDA.items()})
        for r in resultados:
            filas.append({**p.to_dict(), **r})
    return pd.DataFrame(filas)


def requisitos(normas, perfil, excluidos=None, modo="posible"):
    """Filas de la norma que aplican a un perfil (numéricas y cualitativas)."""
    req = filtrar(normas, perfil, excluidos, modo).copy()
    req["rango"] = [rango(f) for _, f in req.iterrows()]
    return req


def resumir(req):
    """Una línea por requisito: 'CO-616-PAST (Decreto 616 de 2006): temperatura_c
    72–76 °C y tiempo_min 0.25–0.3333 min, o bien ...'."""
    lineas = []
    for norma_id, grupo in req.groupby("norma_id", sort=False):
        primera = grupo.iloc[0]
        if (grupo["parametro"] == "requisito").all():
            texto = primera["descripcion"]
        else:
            alternativas = [
                (f"{alt}: " if alt else "") + " y ".join(f"{f['parametro']} {f['rango']}" for _, f in filas.iterrows())
                for alt, filas in grupo.groupby(grupo["alternativa"].fillna(""), sort=False)
            ]
            texto = " o bien ".join(alternativas)
        marca = "" if primera["verificado"] == "si" else " [sin verificar]"
        lineas.append(f"{norma_id} ({primera['norma']}): {texto}{marca}")
    return lineas


def perfil_de_condiciones(condiciones):
    """Condiciones de una regla del árbol ('matriz = leche_liquida',
    'tratamiento_termico ≠ uht') -> (perfil, excluidos)."""
    perfil, excluidos = {}, {}
    for c in condiciones:
        partes = c.split(" ", 2)
        if len(partes) != 3 or partes[0] not in FILTROS:
            continue
        campo, op, valor = partes
        if op == "=":
            perfil[campo] = valor
        elif op == "≠":
            excluidos.setdefault(campo, set()).add(valor)
    return perfil, excluidos


def requisitos_regla(normas, condiciones):
    """Requisitos legales que activa explícitamente una regla del árbol."""
    perfil, excluidos = perfil_de_condiciones(condiciones)
    if not perfil:
        return []
    return resumir(requisitos(normas, perfil, excluidos, modo="relevante"))


VEREDICTOS = {
    "permitida": "Permitida",
    "requiere_verificacion": "Requiere verificación",
    "fuera_de_norma": "Fuera de norma",
}


def veredicto_regla(hallazgos, efecto, normas, condiciones):
    """Veredicto normativo de una regla del árbol a partir de los hallazgos que
    respaldan su efecto (`hallazgos`: filas de la tabla del árbol en la hoja):

    - fuera_de_norma: la mayoría de los hallazgos de respaldo se obtuvo con un
      proceso fuera de la norma; la regla no sirve para diseñar el producto.
    - permitida: ningún hallazgo de respaldo está fuera de norma, los requisitos
      que activa la regla están verificados y, si alguno es de proceso con
      límites numéricos, la mayoría del respaldo demuestra cumplirlo.
    - requiere_verificacion: todo lo demás (faltan datos o normas sin verificar).

    Devuelve {"veredicto", "motivos", "respaldo", "fuera", "cumple", "sin_datos"}.
    """
    respaldo = hallazgos[hallazgos["efecto"] == efecto]
    conteo = respaldo["estado_normativo"].value_counts()
    fuera, cumple = int(conteo.get("fuera_de_norma", 0)), int(conteo.get("cumple", 0))
    sin_datos = len(respaldo) - fuera - cumple
    resultado = {"respaldo": len(respaldo), "fuera": fuera, "cumple": cumple, "sin_datos": sin_datos}

    perfil, excluidos = perfil_de_condiciones(condiciones)
    req = requisitos(normas, perfil, excluidos, modo="relevante") if perfil else normas.iloc[0:0]
    sin_verificar = req.loc[req["verificado"] != "si", "norma_id"].unique()
    numericos = req[(req["parametro"] != "requisito") & (req["minimo"].notna() | req["maximo"].notna())]

    motivos = []
    if fuera:
        motivos.append(f"{fuera} de {len(respaldo)} hallazgos de respaldo con proceso fuera de norma")
    if len(respaldo) and fuera > len(respaldo) / 2:
        return {**resultado, "veredicto": "fuera_de_norma", "motivos": motivos}

    if len(sin_verificar):
        motivos.append(f"{len(sin_verificar)} requisito(s) sin verificar: {', '.join(sin_verificar)}")
    if not numericos.empty and cumple <= len(respaldo) / 2:
        motivos.append(f"solo {cumple} de {len(respaldo)} hallazgos demuestran cumplir los límites de proceso "
                       f"({sin_datos} sin datos)")
    if req.empty:
        motivos.append("la regla no activa requisitos específicos; aplican solo los generales (BPM, rotulado)")
    veredicto = "permitida" if not fuera and not len(sin_verificar) and (
        numericos.empty or cumple > len(respaldo) / 2) else "requiere_verificacion"
    return {**resultado, "veredicto": veredicto, "motivos": motivos}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--matriz", choices=[e.value for e in Observacion.model_fields["matriz"].annotation])
    parser.add_argument("--tratamiento_termico",
                        choices=[e.value for e in Observacion.model_fields["tratamiento_termico"].annotation])
    parser.add_argument("--nivel_grasa", choices=["entera", "semidescremada", "baja_grasa", "descremada"])
    parser.add_argument("--especie_leche",
                        choices=[e.value for e in Observacion.model_fields["especie_leche"].annotation])
    parser.add_argument("--todas", action="store_true", help="incluir jurisdicciones de referencia")
    args = parser.parse_args()

    conn = database.conectar(config.DB_PATH)
    normas = leer(conn, args.todas)
    if normas.empty:
        print(f"No hay normas cargadas: revisa {config.NORMAS_CSV} y config.JURISDICCIONES_NORMAS.")
        return
    pd.set_option("display.width", 200)
    pd.set_option("display.max_colwidth", 90)

    perfil = {c: getattr(args, c) for c in FILTROS if getattr(args, c)}
    if perfil:
        print("Perfil:", ", ".join(f"{c}={v}" for c, v in perfil.items()))
        req = requisitos(normas, perfil)
        for tipo, grupo in req.groupby("tipo"):
            print(f"\n== {tipo} ==")
            for linea in resumir(grupo):
                print(f"- {linea}")
        return

    from build_dataset import actualizar_tabla  # build_dataset importa este módulo
    pendientes = (normas["verificado"] != "si").sum()
    print(f"Normas cargadas ({', '.join(sorted(normas['jurisdiccion'].unique()))}): "
          f"{normas['norma_id'].nunique()} requisitos, {len(normas)} filas, {pendientes} sin verificar.")
    if pendientes:
        print(f"[aviso] Confirma las filas con verificado = no contra el texto oficial ({config.NORMAS_CSV}).")

    tabla, _ = actualizar_tabla(conn)
    print("\n== Hallazgos de los papers frente a la norma ==")
    print(tabla["estado_normativo"].value_counts().to_string())
    fuera = tabla[tabla["estado_normativo"] == "fuera_de_norma"]
    for _, f in fuera.iterrows():
        print(f"- [{f['variable_resultado']} -> {f['efecto']}] {f['comparacion']}  {f['doi'] or ''}")
        print(f"    {f['detalle_normativo']}")

    print("\n== Productos del mercado (USDA) frente a la norma ==")
    prod = evaluar_productos(conn, normas)
    if prod.empty:
        print("Ningún producto tiene datos que permitan evaluar un requisito.")
    else:
        print(prod.groupby(["norma_id", "estado"]).size().unstack(fill_value=0).to_string())
        malos = prod[prod["estado"] == "no_cumple"]
        if not malos.empty:
            print("\nProductos fuera de norma (si se vendieran con esa denominación):")
            print(malos[["description", "brand_owner", "norma_id", "detalle"]].to_string(index=False))

    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    ruta = os.path.join(config.OUTPUT_DIR, "normas_productos.csv")
    prod.to_csv(ruta, index=False)
    print(f"\nEvaluación de productos en {ruta}; la de los hallazgos está en tabla_arbol "
          "(columnas estado_normativo y detalle_normativo).")


if __name__ == "__main__":
    main()
