"""
Del árbol al mercado: toma las condiciones de una rama del árbol de
decisiones y muestra (1) qué dice la evidencia de los papers sobre ese perfil
y (2) qué productos del mercado (USDA) lo cumplen y cómo es su composición
comparada con el resto de productos del mismo tipo.

    python cruce_mercado.py --matriz leche_liquida --tipo_beta_caseina A2
    python cruce_mercado.py --matriz leche_liquida --tratamiento_termico uht
    python cruce_mercado.py --matriz leche_liquida --sistema_alimentacion pastoreo --lactosa_reducida si

Los valores son los mismos que aparecen en las reglas del árbol y en
tabla_arbol.csv (ej. "tipo_beta_caseina=A2" -> --tipo_beta_caseina A2).

Al final (3) lista los requisitos legales que aplicarían a ese perfil
(normas.csv, ver normatividad.py).
"""

import argparse

import pandas as pd

import config_proc as config
import database_proc as database
import normatividad
from esquema import Observacion

CARACTERISTICAS = ["matriz", "tipo_beta_caseina", "especie_leche", "tratamiento_termico",
                   "raza", "sistema_alimentacion", "lactosa_reducida"]


def leer_perfil():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for c in CARACTERISTICAS:
        anotacion = Observacion.model_fields[c].annotation
        if c == "lactosa_reducida":
            parser.add_argument(f"--{c}", choices=["si", "no"])
        else:
            parser.add_argument(f"--{c}", choices=[e.value for e in anotacion])
    parser.add_argument("--max-productos", type=int, default=15)
    args = parser.parse_args()
    perfil = {c: getattr(args, c) for c in CARACTERISTICAS}
    if perfil["lactosa_reducida"] is not None:
        perfil["lactosa_reducida"] = 1 if perfil["lactosa_reducida"] == "si" else 0
    return perfil, args.max_productos


def evidencia(conn, perfil):
    """Observaciones aceptadas cuyo valor coincide exactamente con cada
    característica pedida (las que dicen no_especificado no cuentan)."""
    filtros = [f"o.{c} = :{c}" for c, v in perfil.items() if v is not None]
    return pd.read_sql(
        f"""SELECT o.categoria_factor, o.variable_resultado, o.efecto, o.comparacion, o.cita_textual, p.doi, p.year
            FROM observaciones o JOIN papers p ON p.paper_id = o.paper_id
            WHERE {database.ACEPTADA_SQL} {''.join(' AND ' + f for f in filtros)}""",
        conn, params=perfil,
    )


def productos(conn, perfil, subtipos=database.SUBTIPOS_COMPARABLES):
    columnas = ", ".join(f"u.{n}" for n in database.NUTRIENTES_CRUCE)
    return pd.read_sql(
        f"""SELECT u.fdc_id, u.description, u.brand_owner, u.data_type, u.tipo_producto, u.subtipo, {columnas}, u.url_fuente
            FROM alimentos_usda u
            WHERE {database.condicion_mercado(lambda c: ':' + c, subtipos)}""",
        conn, params=perfil,
    )


def main():
    perfil, max_productos = leer_perfil()
    pedido = {c: v for c, v in perfil.items() if v is not None}
    if not pedido:
        print("Indica al menos una característica, ej. --matriz leche_liquida --tipo_beta_caseina A2")
        return

    conn = database.conectar(config.DB_PATH)
    pd.set_option("display.width", 200)
    pd.set_option("display.max_colwidth", 70)
    print("Perfil:", ", ".join(f"{c}={v}" for c, v in pedido.items()))

    print("\n== 1. Evidencia de los papers ==")
    ev = evidencia(conn, perfil)
    if ev.empty:
        print("No hay observaciones con exactamente esas características.")
    else:
        print(f"{len(ev)} observaciones:\n")
        print(pd.crosstab(ev["variable_resultado"], ev["efecto"]).to_string())
        print()
        for _, fila in ev.iterrows():
            print(f"- [{fila['variable_resultado']} -> {fila['efecto']}] {fila['comparacion']}")
            print(f"    \"{fila['cita_textual'][:160]}\"  {fila['doi'] or ''}")

    print("\n== 2. Productos del mercado (USDA, sin saborizados) ==")
    prod = productos(conn, perfil)
    # Referencia: todos los productos del mismo tipo, sin las demás condiciones
    referencia = productos(conn, {c: (perfil["matriz"] if c == "matriz" else None) for c in CARACTERISTICAS})
    if prod.empty:
        print("Ningún producto del USDA declara esas características en su descripción o ingredientes.")
    else:
        mostrar_productos(prod, referencia, max_productos)

    print("\n== 3. Requisitos legales que aplicarían (normas.csv) ==")
    for linea in normatividad.resumir(normatividad.requisitos(normatividad.leer(conn), perfil)):
        print(f"- {linea}")


def mostrar_productos(prod, referencia, max_productos):
    nutrientes = database.NUTRIENTES_CRUCE
    comparacion = pd.DataFrame({
        f"perfil ({len(prod)} productos)": prod[nutrientes].mean(),
        f"referencia ({len(referencia)} productos)": referencia[nutrientes].mean(),
    }).round(2)
    comparacion["diferencia_%"] = (
        (comparacion.iloc[:, 0] / comparacion.iloc[:, 1] - 1) * 100
    ).round(1)
    print("Composición promedio por 100 g (referencia = mismo tipo de producto sin las demás condiciones):\n")
    print(comparacion.to_string())

    print(f"\nProductos (hasta {max_productos}):")
    print(prod[["description", "brand_owner", "protein_g", "fat_g", "sugars_g", "url_fuente"]]
          .head(max_productos).to_string(index=False))


if __name__ == "__main__":
    main()
