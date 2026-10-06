"""
Construye la tabla final para el árbol de decisiones a partir de la base.

    python build_dataset.py

Guarda la tabla en la base de datos (tabla `tabla_arbol` de selema.db), que es
de donde la leen la interfaz y arbol_decision.py, y además exporta en output/:
- tabla_arbol.csv:           una fila por observación válida. Columnas de entrada
                             (matriz, tipo de beta-caseína, proceso, etc.) + la
                             columna objetivo `efecto`. Incluye doi y cita_textual
                             para poder rastrear cada fila hasta su fuente, y
                             estado_normativo (cumple / fuera_de_norma / sin_datos)
                             según normas.csv (ver normatividad.py).
- evidencia_mercado.csv:     cada hallazgo con los productos del USDA que tienen
                             esas características y su composición promedio.
- observaciones_revisar.csv: filas descartadas por el control de calidad, con el
                             motivo. Si una está bien, apruébala en la base
                             (revision_humana = 'aprobada') y vuelve a correr esto.
"""

import os

import pandas as pd

import config_proc as config
import database_proc as database
import normatividad
from esquema import CAMPOS_BOOLEANOS, CAMPOS_CATEGORICOS, CAMPOS_NUMERICOS, CAMPOS_OBSERVACION

TIPOS_NO_PRIMARIOS = ("revision", "modelado_ml")

CONSULTA = f"""
SELECT o.id AS observacion_id, o.paper_id, p.doi, p.title, p.year,
       {', '.join('o.' + c for c in CAMPOS_OBSERVACION)}, o.comparacion,
       o.cita_verificada, o.valida, o.problemas, o.revision_humana
FROM observaciones o
JOIN papers p ON p.paper_id = o.paper_id
"""


def construir(conn):
    df = pd.read_sql_query(CONSULTA, conn)
    aceptada = (
        ((df["valida"] == 1) & (df["revision_humana"].fillna("") != "rechazada"))
        | (df["revision_humana"] == "aprobada")
    )
    tabla = df[aceptada].copy()
    revisar = df[~aceptada].copy()

    # Una misma observación repetida dentro de un paper pesaría doble en el árbol
    # (se ignoran los textos libres, que pueden variar aunque el hallazgo sea el mismo)
    claves = ["paper_id"] + [c for c in CAMPOS_OBSERVACION
                             if c not in ("cita_textual", "factor_evaluado", "referencia", "pais", "cepas")]
    antes = len(tabla)
    tabla = tabla.drop_duplicates(subset=claves)
    tabla.attrs["duplicadas"] = antes - len(tabla)

    tabla["es_evidencia_primaria"] = ~tabla["tipo_estudio"].isin(TIPOS_NO_PRIMARIOS)
    for c in CAMPOS_BOOLEANOS:
        tabla[c] = tabla[c].map({1: "si", 0: "no"}).fillna("no_especificado")
    tabla = normatividad.evaluar_hallazgos(tabla, normatividad.leer(conn))

    columnas = (["observacion_id", "paper_id", "doi", "year"]
                + [c for c in CAMPOS_OBSERVACION if c not in ("efecto", "cita_textual")] + ["comparacion"]
                + ["es_evidencia_primaria", "estado_normativo", "detalle_normativo", "efecto", "cita_textual"])
    return tabla[columnas], revisar


def actualizar_tabla(conn):
    """Reconstruye la tabla del árbol desde las observaciones y la guarda en
    la base (tabla `tabla_arbol`). Devuelve (tabla, revisar)."""
    tabla, revisar = construir(conn)
    tabla.to_sql("tabla_arbol", conn, if_exists="replace", index=False)
    return tabla, revisar


def reporte(tabla, revisar):
    duplicadas = tabla.attrs.get("duplicadas", 0)
    total = len(tabla) + len(revisar) + duplicadas
    print(f"Observaciones totales: {total} | aceptadas: {len(tabla)} | "
          f"duplicadas eliminadas: {duplicadas} | a revisar: {len(revisar)}")
    if tabla.empty:
        return
    print(f"Papers que aportan filas: {tabla['paper_id'].nunique()}")
    print("\nDistribución de la variable objetivo (efecto):")
    print(tabla["efecto"].value_counts().to_string())
    print("\nFilas por variable de resultado:")
    print(tabla["variable_resultado"].value_counts().to_string())
    print("\nCumplimiento de la norma (ver python normatividad.py):")
    print(tabla["estado_normativo"].value_counts().to_string())
    print("\nCompletitud de columnas numéricas (% con dato):")
    print((tabla[CAMPOS_NUMERICOS].notna().mean() * 100).round(1).to_string())
    print("\nCategorías 'no_especificado' (% de filas):")
    for c in CAMPOS_CATEGORICOS:
        pct = (tabla[c] == "no_especificado").mean() * 100
        if pct:
            print(f"  {c}: {pct:.1f}%")
    if len(tabla) < 50:
        print("\n[aviso] Menos de 50 filas: el árbol será poco confiable. "
              "Extrae más papers (python extract_llm_insights.py --top 100).")


def main():
    conn = database.conectar(config.DB_PATH)
    tabla, revisar = actualizar_tabla(conn)

    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    ruta_tabla = os.path.join(config.OUTPUT_DIR, "tabla_arbol.csv")
    ruta_revisar = os.path.join(config.OUTPUT_DIR, "observaciones_revisar.csv")
    tabla.to_csv(ruta_tabla, index=False)
    revisar.to_csv(ruta_revisar, index=False)

    ruta_mercado = os.path.join(config.OUTPUT_DIR, "evidencia_mercado.csv")
    pd.read_sql_query("SELECT * FROM evidencia_mercado", conn).to_csv(ruta_mercado, index=False)

    reporte(tabla, revisar)
    print(f"\nTabla guardada en la base ({config.DB_PATH}, tabla tabla_arbol) y en {ruta_tabla}")
    print(f"Cruce hallazgos <-> productos del mercado en {ruta_mercado}")
    print(f"Filas descartadas (para revisión humana) en {ruta_revisar}")
    print("Siguiente paso: python arbol_decision.py")


if __name__ == "__main__":
    main()
