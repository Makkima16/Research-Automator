"""
Entrena un árbol de decisiones sobre la tabla `tabla_arbol` de la base de
datos para predecir `efecto` (mejora / sin_diferencia / empeora / mixto) y
muestra sus reglas en lenguaje claro.

    python arbol_decision.py
    python arbol_decision.py --resultado sintomas_gastrointestinales
    python arbol_decision.py --solo-primaria --profundidad 3
    python arbol_decision.py --dentro-de-norma   # sin hallazgos obtenidos fuera de la norma

Debajo de cada regla se listan los requisitos legales que activa (normas.csv)
y su veredicto normativo: permitida / requiere verificación / fuera de norma
(ver normatividad.veredicto_regla).
La interfaz gráfica (app.py, pestaña "Árbol de decisiones") usa estas mismas
funciones. Con pocas filas las reglas son orientativas, no concluyentes.
"""

import argparse

import pandas as pd
from sklearn.model_selection import cross_val_score
from sklearn.tree import DecisionTreeClassifier, export_text

import config_proc as config
import database_proc as database
import normatividad
from build_dataset import actualizar_tabla
from esquema import CAMPOS_BOOLEANOS, CAMPOS_CATEGORICOS, CAMPOS_NUMERICOS

OBJETIVO = "efecto"
MIN_FILAS = 10


def preparar(df, resultado=None, solo_primaria=False, min_completitud=0.6, dentro_de_norma=False):
    if resultado:
        df = df[df["variable_resultado"] == resultado]
    if solo_primaria:
        df = df[df["es_evidencia_primaria"].astype(bool)]
    if dentro_de_norma:
        # Un hallazgo logrado con un proceso ilegal no sirve para decidir el producto
        df = df[df["estado_normativo"] != "fuera_de_norma"]
    categoricas = [c for c in CAMPOS_CATEGORICOS if c != OBJETIVO] + CAMPOS_BOOLEANOS
    if resultado:
        categoricas.remove("variable_resultado")
    X = pd.get_dummies(df[categoricas].fillna("no_especificado"), prefix_sep="=")
    # "no especificado" no es una característica real de la leche: no se usa para decidir
    X = X.loc[:, ~X.columns.str.endswith("=no_especificado")]
    # Una columna numérica casi vacía haría que el árbol aprenda "tiene dato / no
    # tiene dato" (se ve como "<= inf") en vez del valor en sí
    numericas = [c for c in CAMPOS_NUMERICOS if df[c].notna().mean() >= min_completitud]
    X = pd.concat([X, df[numericas]], axis=1)
    # Columnas sin ninguna variación no aportan al árbol
    X = X.loc[:, X.nunique(dropna=False) > 1]
    return X, df[OBJETIVO]


def entrenar(df, resultado=None, solo_primaria=False, profundidad=4, min_hojas=3, min_completitud=0.6,
             dentro_de_norma=False):
    """Devuelve un dict con el árbol entrenado y sus métricas, o con la clave
    `error` si no hay datos suficientes."""
    X, y = preparar(df, resultado, solo_primaria, min_completitud, dentro_de_norma)
    if len(y) < MIN_FILAS or y.nunique() < 2:
        return {"error": f"Solo hay {len(y)} filas y {y.nunique()} clase(s): no alcanza para entrenar un árbol."}
    if X.shape[1] == 0:
        return {"error": "Ninguna característica tiene datos suficientes para separar los resultados."}

    # Sin pesos por clase: cada regla predice lo que dice la mayoría de sus hallazgos
    arbol = DecisionTreeClassifier(max_depth=profundidad, min_samples_leaf=min_hojas, random_state=42)
    pliegues = min(5, y.value_counts().min())
    validacion = None
    if pliegues >= 2:
        puntajes = cross_val_score(arbol, X, y, cv=pliegues, scoring="balanced_accuracy")
        validacion = {"media": puntajes.mean(), "desv": puntajes.std(), "pliegues": pliegues}
    arbol.fit(X, y)
    return {
        "arbol": arbol, "X": X, "y": y, "validacion": validacion,
        "azar": 1 / y.nunique(),  # exactitud balanceada de adivinar al azar
        "importancias": pd.Series(arbol.feature_importances_, index=X.columns)
                          .loc[lambda s: s > 0].sort_values(ascending=False),
    }


def _condicion(columna, umbral, a_la_derecha):
    """Traduce un corte del árbol a texto: 'raza = jersey', 'ph > 6.6'..."""
    if "=" in columna:  # columna binaria (dummy): <= 0.5 significa "no es"
        campo, valor = columna.split("=", 1)
        return f"{campo} {'=' if a_la_derecha else '≠'} {valor}"
    return f"{columna} {'>' if a_la_derecha else '≤'} {umbral:.2f}"


def reglas(resultado):
    """Una regla por hoja del árbol: condiciones, efecto predicho y cuántos
    hallazgos reales caen en ella (`filas`: sus índices en la tabla del árbol).
    Ordenadas de más a menos hallazgos."""
    arbol, X, y = resultado["arbol"], resultado["X"], resultado["y"]
    t = arbol.tree_
    hojas = arbol.apply(X)
    conteos = pd.crosstab(hojas, y.values)  # hallazgos reales por hoja (sin pesos)
    salida = []

    def recorrer(nodo, condiciones):
        if t.children_left[nodo] == -1:
            fila = conteos.loc[nodo]
            prediccion = arbol.classes_[t.value[nodo][0].argmax()]
            salida.append({
                "condiciones": condiciones or ["(todos los hallazgos)"],
                "efecto": prediccion,
                "n": int(fila.sum()),
                "aciertos": int(fila.get(prediccion, 0)),
                "distribucion": {k: int(v) for k, v in fila.items() if v},
                "filas": list(X.index[hojas == nodo]),
            })
            return
        columna, umbral = X.columns[t.feature[nodo]], t.threshold[nodo]
        recorrer(t.children_left[nodo], condiciones + [_condicion(columna, umbral, False)])
        recorrer(t.children_right[nodo], condiciones + [_condicion(columna, umbral, True)])

    recorrer(0, [])
    return sorted(salida, key=lambda r: -r["n"])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--resultado", help="filtrar por una variable_resultado (ej. digestibilidad_proteica)")
    parser.add_argument("--solo-primaria", action="store_true", help="excluir revisiones y modelado")
    parser.add_argument("--profundidad", type=int, default=4)
    parser.add_argument("--min-completitud", type=float, default=0.6,
                        help="fracción mínima de filas con dato para usar una columna numérica")
    parser.add_argument("--min-hojas", type=int, default=3, help="mínimo de filas por hoja")
    parser.add_argument("--dentro-de-norma", action="store_true",
                        help="excluir hallazgos cuyo proceso está fuera de la norma (normas.csv)")
    args = parser.parse_args()

    conn = database.conectar(config.DB_PATH)
    tabla, _ = actualizar_tabla(conn)
    res = entrenar(tabla, args.resultado, args.solo_primaria, args.profundidad,
                   args.min_hojas, args.min_completitud, args.dentro_de_norma)
    if "error" in res:
        print(res["error"])
        return

    v = res["validacion"]
    if v:
        print(f"Exactitud balanceada (validación cruzada {v['pliegues']} pliegues): "
              f"{v['media']:.2f} ± {v['desv']:.2f}  (azar: {res['azar']:.2f})")
    else:
        print("[aviso] Alguna clase tiene 1 sola fila: se omite la validación cruzada.")
    print(f"Entrenado con {len(res['y'])} filas y {res['X'].shape[1]} columnas.\n")

    normas = normatividad.leer(conn)
    for r in reglas(res):
        print(f"SI {' Y '.join(r['condiciones'])}")
        print(f"   ENTONCES {r['efecto']}  ({r['aciertos']} de {r['n']} hallazgos)  {r['distribucion']}")
        v = normatividad.veredicto_regla(tabla.loc[r["filas"]], r["efecto"], normas, r["condiciones"])
        print(f"   VEREDICTO NORMATIVO: {normatividad.VEREDICTOS[v['veredicto']].upper()}"
              + (f" — {'; '.join(v['motivos'])}" if v["motivos"] else ""))
        for requisito in normatividad.requisitos_regla(normas, r["condiciones"]):
            print(f"   NORMA: {requisito}")
        print()

    print("Factores más importantes:")
    print(res["importancias"].round(3).to_string())
    print("\nÁrbol completo:")
    print(export_text(res["arbol"], feature_names=list(res["X"].columns)))


if __name__ == "__main__":
    main()
