"""
Interfaz gráfica para explorar la base de datos (../busqueda/output/selema.db).

    streamlit run app.py

Se abre en el navegador. Lee la base en vivo: si extraes más papers, basta
con recargar la página. Está organizada por preguntas:
  1. Qué dice la ciencia     -> mapa de evidencia de los papers
  2. Comparar en el mercado  -> grupo A vs grupo B de productos del USDA
  3. Árbol de decisiones     -> reglas que resumen la evidencia
  4. Normatividad            -> límites legales y qué hallazgos/productos los cumplen
  5. Explorar datos          -> tablas completas y calidad de los datos
"""

import html
import re

import altair as alt
import pandas as pd
import streamlit as st
from scipy.stats import mannwhitneyu

import arbol_decision
import config_proc as config
import database_proc as database
import fetch_usda
import normatividad
from build_dataset import actualizar_tabla
from cruce_mercado import CARACTERISTICAS
from esquema import CAMPOS_NUMERICOS, Observacion

CUALQUIERA = "(cualquiera)"

# Efecto como escala divergente: azul = mejora, rojo = empeora, grises al centro
ORDEN_EFECTO = ["empeora", "mixto", "sin_diferencia", "mejora"]
COLOR_EFECTO = ["#e34948", "#8a8984", "#c4c2bc", "#2a78d6"]
COLOR_SERIE = "#2a78d6"
COLOR_POR_EFECTO = dict(zip(ORDEN_EFECTO, COLOR_EFECTO))
# Dos grupos del comparador: primeros dos colores de la paleta categórica
COLOR_GRUPOS = {"A": "#2a78d6", "B": "#eb6834"}

NUTRIENTES = {
    "energy_kcal": "Energía (kcal)",
    "protein_g": "Proteína (g)",
    "fat_g": "Grasa (g)",
    "sat_fat_g": "Grasa saturada (g)",
    "sugars_g": "Azúcares (g)",
    "calcium_mg": "Calcio (mg)",
    "sodium_mg": "Sodio (mg)",
    "vitamin_d_iu": "Vitamina D (UI)",
}

ETIQUETAS = {
    "matriz": "Tipo de producto",
    "tipo_beta_caseina": "Beta-caseína",
    "especie_leche": "Especie",
    "tratamiento_termico": "Tratamiento térmico",
    "raza": "Raza",
    "sistema_alimentacion": "Alimentación de la vaca",
    "lactosa_reducida": "Lactosa reducida",
}
# Nombres legibles para las demás columnas de la tabla de observaciones
ETIQUETAS_OTRAS = {
    "categoria_factor": "Tipo de factor", "factor_evaluado": "Factor evaluado",
    "variable_resultado": "Variable medida",
    "region": "Región", "tipo_estudio": "Tipo de estudio", "temperatura_c": "Temperatura (°C)",
    "tiempo_min": "Tiempo (min)", "ph": "pH", "proteina_pct": "Proteína (%)", "grasa_pct": "Grasa (%)",
    "lactosa_pct": "Lactosa (%)", "solidos_totales_pct": "Sólidos totales (%)",
    "celulas_somaticas_miles_ml": "Células somáticas", "vida_util_dias": "Vida útil (días)",
    "tamano_muestra": "Tamaño de muestra",
}
NOMBRES_OPCIONES = {"A1A2": "A1A2 (convencional)", "A1": "A1 (solo A1)"}


# ---------------------------------------------------------------- utilidades

def legible(valor):
    return NOMBRES_OPCIONES.get(valor, str(valor).replace("_", " "))


def nombre_campo(campo):
    return ETIQUETAS.get(campo, ETIQUETAS_OTRAS.get(campo, legible(campo).capitalize()))


def opciones(campo):
    if campo == "lactosa_reducida":
        return [CUALQUIERA, "si", "no"]
    return [CUALQUIERA] + [e.value for e in Observacion.model_fields[campo].annotation
                           if e.value != "no_especificado"]


def a_valor(campo, opcion):
    """Opción del selectbox -> valor en la base (None = sin filtro)."""
    if opcion in (None, CUALQUIERA):
        return None
    if campo == "lactosa_reducida":
        return 1 if opcion == "si" else 0
    return opcion


def tarjeta(efecto, encabezado, cuerpo_html):
    """Tarjeta con el borde superior del color del efecto (el mismo de los gráficos)."""
    color = COLOR_POR_EFECTO.get(efecto, "#8a8984")
    st.markdown(f"""
<div style="border:1px solid rgba(128,128,128,.35); border-top:6px solid {color};
            border-radius:8px; padding:10px 14px; margin-bottom:12px;">
  <div style="font-size:.78rem; font-weight:700; letter-spacing:.05em; text-transform:uppercase;">
    <span style="color:{color}">●</span> {html.escape(legible(efecto))}
    <span style="font-weight:400; opacity:.7; text-transform:none; letter-spacing:0">· {html.escape(encabezado)}</span>
  </div>
  {cuerpo_html}
</div>""", unsafe_allow_html=True)


def tarjeta_hallazgo(fila):
    fuente = ""
    if fila["doi"]:
        doi = html.escape(fila["doi"])
        fuente = f'<div style="margin-top:6px">Fuente: <a href="{doi}" target="_blank">{doi}</a> ({fila["year"]})</div>'
    cuerpo = f"""
  <div style="margin-top:4px">{html.escape(fila["comparacion"] or "")}</div>
  <details style="margin-top:6px">
    <summary style="cursor:pointer; font-size:.85rem; opacity:.75">Ver cita y fuente</summary>
    <blockquote style="margin:8px 0; padding-left:10px; border-left:3px solid rgba(128,128,128,.5); font-style:italic">
      {html.escape(fila["cita_textual"] or "")}</blockquote>
    {fuente}
  </details>"""
    encabezado = legible(fila["variable_resultado"])
    if fila.get("categoria_factor"):
        encabezado += f" · {legible(fila['categoria_factor'])}"
    tarjeta(fila["efecto"], encabezado, cuerpo)


def grafico_efectos(df, eje, titulo_eje):
    """Barras apiladas: cuántas observaciones dicen mejora/empeora por categoría."""
    conteo = df.groupby([eje, "efecto"]).size().reset_index(name="observaciones")
    conteo["categoria"] = conteo[eje].map(legible)
    conteo["efecto_txt"] = conteo["efecto"].map(legible)
    conteo["orden"] = conteo["efecto"].map(ORDEN_EFECTO.index)
    orden_y = conteo.groupby("categoria")["observaciones"].sum().sort_values(ascending=False).index.tolist()
    return (
        alt.Chart(conteo)
        .mark_bar(size=18)
        .encode(
            y=alt.Y("categoria:N", title=titulo_eje, sort=orden_y, axis=alt.Axis(labelLimit=220)),
            x=alt.X("sum(observaciones):Q", title="Observaciones", axis=alt.Axis(tickMinStep=1)),
            color=alt.Color("efecto_txt:N", title="Efecto",
                            scale=alt.Scale(domain=[legible(e) for e in ORDEN_EFECTO], range=COLOR_EFECTO),
                            legend=alt.Legend(orient="top", columns=4, labelLimit=200)),
            order=alt.Order("orden:Q"),
            tooltip=[alt.Tooltip("categoria:N", title=titulo_eje), alt.Tooltip("efecto_txt:N", title="Efecto"),
                     alt.Tooltip("observaciones:Q", title="Observaciones")],
        )
        .properties(height=alt.Step(34))
    )


# ---------------------------------------------------- 1. qué dice la ciencia

def cargar_observaciones(conn):
    return pd.read_sql(
        f"""SELECT o.*, p.doi, p.year FROM observaciones o JOIN papers p ON p.paper_id = o.paper_id
            WHERE {database.ACEPTADA_SQL}""", conn)


def quitar_filtros():
    for campo in CARACTERISTICAS:
        st.session_state[f"ev_{campo}"] = CUALQUIERA


def filtros_evidencia(obs):
    """Filtros de la evidencia en cascada: solo se ofrecen opciones con hallazgos
    (según los demás filtros) y el ícono de ayuda de cada filtro dice cuántos
    hay. Las etiquetas de las opciones son fijas a propósito: Streamlit guarda
    la opción elegida por su texto, y si el texto cambiara entre recargas (por
    ejemplo, un conteo) la selección se perdería o quedaría desincronizada."""
    actual = {c: a_valor(c, st.session_state.get(f"ev_{c}")) for c in CARACTERISTICAS}
    columnas = st.columns(4)
    visibles = 0
    perfil = {}
    for campo in CARACTERISTICAS:
        sub = obs
        for c, v in actual.items():
            if c != campo and v is not None:
                sub = sub[sub[c] == v]
        conteos = {o: int((sub[campo] == a_valor(campo, o)).sum()) for o in opciones(campo)[1:]}
        elegido = st.session_state.get(f"ev_{campo}", CUALQUIERA)
        lista = [CUALQUIERA] + [o for o, n in conteos.items() if n or o == elegido]
        if len(lista) == 1:  # ninguna opción con datos: el filtro no aporta
            continue
        ayuda = "Hallazgos con cada opción (según los demás filtros): " + ", ".join(
            f"{legible(o)}: {conteos[o]}" for o in lista[1:])
        with columnas[visibles % 4]:
            valor = st.selectbox(nombre_campo(campo), lista, key=f"ev_{campo}", help=ayuda,
                                 format_func=lambda o: o if o == CUALQUIERA else legible(o))
        perfil[campo] = a_valor(campo, valor)
        visibles += 1

    # Se filtra solo con lo que muestran los selectores visibles
    filtrado = obs
    for campo, v in perfil.items():
        if v is not None:
            filtrado = filtrado[filtrado[campo] == v]
    activos = sum(v is not None for v in perfil.values())
    c1, c2 = st.columns([4, 1])
    c1.caption(f"Con {activos} filtro(s) activo(s) quedan **{len(filtrado)}** de {len(obs)} hallazgos.")
    c2.button("Quitar filtros", on_click=quitar_filtros, disabled=not activos, width="stretch")
    return filtrado


def mapa_evidencia(obs):
    """Mapa de calor tipo de factor × variable medida. Color = balance de la
    evidencia ((mejora - empeora) / hallazgos); número = cantidad de hallazgos."""
    celdas = (obs.groupby(["categoria_factor", "variable_resultado", "efecto"]).size()
                 .unstack(fill_value=0).reindex(columns=ORDEN_EFECTO, fill_value=0).reset_index())
    celdas["n"] = celdas[ORDEN_EFECTO].sum(axis=1)
    celdas["balance"] = (celdas["mejora"] - celdas["empeora"]) / celdas["n"]
    celdas["factor"] = celdas["categoria_factor"].map(legible)
    celdas["variable"] = celdas["variable_resultado"].map(legible)
    orden_filas = celdas.groupby("factor")["n"].sum().sort_values(ascending=False).index.tolist()
    orden_cols = celdas.groupby("variable")["n"].sum().sort_values(ascending=False).index.tolist()

    seleccion = alt.selection_point(name="celda", fields=["categoria_factor", "variable_resultado"], empty=False)
    base = alt.Chart(celdas).encode(
        x=alt.X("variable:N", title="Variable medida", sort=orden_cols,
                axis=alt.Axis(labelAngle=-35, labelLimit=160, orient="top")),
        y=alt.Y("factor:N", title="Tipo de factor evaluado", sort=orden_filas, axis=alt.Axis(labelLimit=200)),
    )
    rect = base.mark_rect(cornerRadius=4).encode(
        color=alt.Color("balance:Q", title="Balance de la evidencia",
                        # interpolación en RGB: solo tonos entre rojo, gris y azul (sin morados ni cafés)
                        scale=alt.Scale(domain=[-1, 0, 1], range=["#e34948", "#c4c2bc", "#2a78d6"],
                                        interpolate="rgb"),
                        legend=alt.Legend(orient="bottom", direction="horizontal", gradientLength=220,
                                          values=[-1, 0, 1], labelExpr=
                                          "datum.value < 0 ? 'empeora' : datum.value > 0 ? 'mejora' : 'dividido'")),
        stroke=alt.condition(seleccion, alt.value("#eda100"), alt.value("transparent")),
        strokeWidth=alt.condition(seleccion, alt.value(4), alt.value(0)),
        tooltip=[alt.Tooltip("factor:N", title="Tipo de factor"), alt.Tooltip("variable:N", title="Variable"),
                 alt.Tooltip("n:Q", title="Hallazgos"), alt.Tooltip("mejora:Q", title="Mejora"),
                 alt.Tooltip("empeora:Q", title="Empeora"), alt.Tooltip("sin_diferencia:Q", title="Sin diferencia"),
                 alt.Tooltip("mixto:Q", title="Mixto")],
    ).add_params(seleccion)
    texto = base.mark_text(fontSize=13, fontWeight="bold").encode(
        text="n:Q",
        color=alt.condition("abs(datum.balance) >= 0.5", alt.value("white"), alt.value("#0b0b0b")),
    )
    return (rect + texto).properties(height=alt.Step(40), width=alt.Step(78))


def pestana_ciencia(conn):
    obs = cargar_observaciones(conn)
    if obs.empty:
        st.info("Todavía no hay observaciones. Corre python extract_llm_insights.py")
        return
    st.subheader("¿Qué dice la ciencia?")
    st.caption("Cada hallazgo es una comparación reportada por un paper: un factor evaluado (ej. leche UHT) "
               "frente a una referencia (ej. leche cruda), y lo que le pasó a una variable medida.")
    with st.expander("Filtrar la evidencia", expanded=False):
        obs_f = filtros_evidencia(obs)
    if obs_f.empty:
        st.warning("Ningún hallazgo cumple esos filtros.")
        return

    con_factor = obs_f[obs_f["categoria_factor"].notna()]
    if con_factor.empty:
        st.warning("Estos hallazgos son de la extracción anterior y no tienen el tipo de factor. Corre "
                   "python extract_llm_insights.py --top 150 para ver el mapa de evidencia. Mientras tanto, "
                   "así se reparten por variable medida:")
        st.altair_chart(grafico_efectos(obs_f, "variable_resultado", "Variable medida"), width="stretch")
        return

    st.markdown(f"**Mapa de evidencia** · {len(con_factor)} hallazgos")
    st.caption("Filas: qué tipo de factor se evaluó. Columnas: qué se midió. El número es la cantidad de "
               "hallazgos; el color, hacia dónde apunta la mayoría (azul mejora, rojo empeora, gris dividido). "
               "Las celdas vacías son preguntas que la literatura recolectada no responde. "
               "**Haz clic en una celda** para ver sus hallazgos.")
    evento = st.altair_chart(mapa_evidencia(con_factor), on_select="rerun", key="mapa")
    elegidas = (evento.selection.get("celda") or []) if evento else []
    if not elegidas:
        st.info("Haz clic en una celda del mapa para ver los hallazgos y sus citas.")
    else:
        celda = elegidas[0]
        detalle = con_factor[(con_factor["categoria_factor"] == celda["categoria_factor"])
                             & (con_factor["variable_resultado"] == celda["variable_resultado"])]
        st.markdown(f"#### {legible(celda['categoria_factor']).capitalize()} → {legible(celda['variable_resultado'])}"
                    f" · {len(detalle)} hallazgos")
        factores = detalle["factor_evaluado"].dropna().str.strip().str.lower().value_counts()
        if not factores.empty:
            st.caption("Factores evaluados: " + ", ".join(f"{f} ({n})" for f, n in factores.head(8).items()))
        izquierda, derecha = st.columns(2, gap="large")
        filas = detalle.sort_values("efecto", key=lambda e: e.map(ORDEN_EFECTO.index))
        for i, (_, fila) in enumerate(filas.iterrows()):
            with (izquierda if i % 2 == 0 else derecha):
                tarjeta_hallazgo(fila)

    with st.expander("Ver la evidencia agrupada por otra característica"):
        campo = st.selectbox("Agrupar por", [c for c in ETIQUETAS if c != "lactosa_reducida"]
                             + ["tipo_estudio", "region"], format_func=nombre_campo)
        datos = obs_f[obs_f[campo].notna() & (obs_f[campo] != "no_especificado")]
        if datos.empty:
            st.warning("Ningún hallazgo especifica esta característica.")
        else:
            st.altair_chart(grafico_efectos(datos, campo, nombre_campo(campo)), width="stretch")
        st.caption(f"{len(obs_f) - len(datos)} de {len(obs_f)} hallazgos no especifican esta característica.")


# ------------------------------------------------ 2. comparar en el mercado

# Atributos del USDA que definen un grupo: (columna, etiqueta, opciones -> valor en la base)
ATRIBUTOS_GRUPO = {
    "tipo_beta_caseina": ("Beta-caseína", {"A2": "A2", "convencional (no declara A2)": "no_especificado"}),
    "especie_leche": ("Especie", None),
    "tratamiento_termico": ("Tratamiento térmico", None),
    "organico": ("Orgánica", {"sí": "si", "no": "no_especificado"}),
    "pastoreo": ("Pastoreo (grass-fed)", {"sí": "si", "no": "no_especificado"}),
    "sin_lactosa": ("Sin lactosa", {"sí": "si", "no": "no_especificado"}),
}
COMPARACIONES_RAPIDAS = {
    "A2 vs convencional": ({"tipo_beta_caseina": "A2"}, {"tipo_beta_caseina": "convencional (no declara A2)"}),
    "Orgánica vs no orgánica": ({"organico": "sí"}, {"organico": "no"}),
    "Pastoreo vs sin pastoreo declarado": ({"pastoreo": "sí"}, {"pastoreo": "no"}),
    "Sin lactosa vs con lactosa": ({"sin_lactosa": "sí"}, {"sin_lactosa": "no"}),
    "Cabra vs vaca": ({"especie_leche": "cabra"}, {"especie_leche": "vaca"}),
    "UHT vs pasteurizada": ({"tratamiento_termico": "uht"}, {"tratamiento_termico": "pasteurizado"}),
}


def aplicar_comparacion_rapida():
    elegida = st.session_state.get("comparacion_rapida")
    if elegida not in COMPARACIONES_RAPIDAS:
        return
    for grupo, valores in zip("AB", COMPARACIONES_RAPIDAS[elegida]):
        for campo in ATRIBUTOS_GRUPO:
            st.session_state[f"grupo{grupo}_{campo}"] = valores.get(campo, CUALQUIERA)


def definir_grupo(grupo, base):
    """Selectores de un grupo. Devuelve (productos del grupo, descripción)."""
    st.markdown(f"<span style='color:{COLOR_GRUPOS[grupo]}; font-size:1.3rem'>●</span> **Grupo {grupo}**",
                unsafe_allow_html=True)
    filtrado, partes = base, []
    columnas = st.columns(2)
    for i, (campo, (etiqueta, mapa)) in enumerate(ATRIBUTOS_GRUPO.items()):
        if mapa is None:
            valores = sorted(v for v in base[campo].dropna().unique() if v != "no_especificado")
            mapa = {legible(v): v for v in valores}
        clave = f"grupo{grupo}_{campo}"
        if st.session_state.get(clave, CUALQUIERA) not in [CUALQUIERA, *mapa]:
            st.session_state[clave] = CUALQUIERA
        elegido = columnas[i % 2].selectbox(etiqueta, [CUALQUIERA, *mapa], key=clave)
        if elegido != CUALQUIERA:
            filtrado = filtrado[filtrado[campo] == mapa[elegido]]
            partes.append(f"{etiqueta.lower()}: {elegido}")
    st.caption(f"{len(filtrado)} productos")
    return filtrado, ", ".join(partes) or "sin condiciones"


def comparar_grupos(a, b):
    filas = []
    for columna, nombre in NUTRIENTES.items():
        va, vb = a[columna].dropna(), b[columna].dropna()
        if va.empty or vb.empty:
            continue
        ma, mb = va.mean(), vb.mean()
        diferencia = (ma / mb - 1) * 100 if mb else float("nan")
        p = mannwhitneyu(va, vb).pvalue if len(va) >= 3 and len(vb) >= 3 else float("nan")
        if abs(diferencia) < 5:
            lectura = "≈ igual"
        else:
            lectura = f"{'↑' if diferencia > 0 else '↓'} {abs(diferencia):.0f} % {'más' if diferencia > 0 else 'menos'}"
        if pd.isna(p):
            confianza = "pocos datos"
        elif p < 0.05:
            confianza = "consistente"
        else:
            confianza = "podría ser azar"
        filas.append({"nutriente": nombre, "A": round(ma, 2), "B": round(mb, 2), "diferencia_%": round(diferencia, 1),
                      "lectura": lectura, "confianza": confianza, "nA": len(va), "nB": len(vb)})
    return pd.DataFrame(filas)


def grafico_grupos(tabla):
    """Un renglón por nutriente, cada uno con su propia escala (distintas unidades)
    que empieza en cero, para que la distancia entre A y B sea proporcional a la
    diferencia real y no se exageren diferencias pequeñas."""
    largo = tabla.melt(id_vars=["nutriente"], value_vars=["A", "B"], var_name="grupo", value_name="valor")
    largo = largo.merge(tabla[["nutriente", "A", "B", "lectura"]], on="nutriente")
    largo["min"] = largo[["A", "B"]].min(axis=1)
    largo["max"] = largo[["A", "B"]].max(axis=1)
    orden = tabla["nutriente"].tolist()
    eje = alt.Axis(tickCount=3, grid=False)
    regla = alt.Chart().mark_rule(color="#8a8984", strokeWidth=2).encode(x=alt.X("min:Q", title=None, axis=eje), x2="max:Q")
    puntos = alt.Chart().mark_circle(size=140, opacity=1).encode(
        x=alt.X("valor:Q", title=None, scale=alt.Scale(zero=True), axis=eje),
        color=alt.Color("grupo:N", title="Grupo", scale=alt.Scale(domain=["A", "B"],
                        range=[COLOR_GRUPOS["A"], COLOR_GRUPOS["B"]]), legend=alt.Legend(orient="top")),
        tooltip=[alt.Tooltip("nutriente:N", title="Nutriente"), alt.Tooltip("grupo:N", title="Grupo"),
                 alt.Tooltip("valor:Q", title="Promedio por 100 g", format=".2f"),
                 alt.Tooltip("lectura:N", title="A frente a B")],
    )
    return (
        alt.layer(regla, puntos, data=largo)
        .properties(height=26, width=420)  # un gráfico por renglones no admite ancho "container"
        .facet(row=alt.Row("nutriente:N", sort=orden, title=None,
                           header=alt.Header(labelAngle=0, labelAlign="left", labelLimit=160)), spacing=6)
        .resolve_scale(x="independent")
    )


def pestana_comparar(conn):
    st.subheader("Comparar en el mercado")
    st.caption("Compara la composición promedio (por 100 g, según las etiquetas del USDA) de dos grupos de "
               "productos. Describe el mercado de EE. UU.; no prueba que una característica cause la diferencia.")
    u = pd.read_sql("SELECT * FROM alimentos_usda", conn)

    c1, c2, c3 = st.columns([2, 2, 3])
    tipos = sorted(u["tipo_producto"].dropna().unique())
    tipo = c1.selectbox("Tipo de producto", tipos, index=tipos.index("leche") if "leche" in tipos else 0,
                        format_func=legible)
    grasas = [g for g in ["entera", "semidescremada", "baja_grasa", "descremada"] if g in set(u["nivel_grasa"])]
    grasa = c2.selectbox("Mismo nivel de grasa en ambos grupos", [CUALQUIERA, *grasas], format_func=legible,
                         help="Comparar entera con entera evita que la diferencia se deba a mezclar leches "
                              "enteras con descremadas.")
    subtipos = c3.multiselect("Productos a incluir", fetch_usda.SUBTIPOS, default=list(database.SUBTIPOS_COMPARABLES),
                              format_func=legible,
                              help="Por defecto solo naturales: sin buttermilk, condensadas, en polvo, con "
                                   "proteína agregada ni saborizadas.")
    base = u[(u["tipo_producto"] == tipo) & u["subtipo"].isin(subtipos)]
    if grasa != CUALQUIERA:
        base = base[base["nivel_grasa"] == grasa]

    if "comparacion_rapida" not in st.session_state:  # primera carga: A2 vs convencional
        st.session_state["comparacion_rapida"] = "A2 vs convencional"
        aplicar_comparacion_rapida()
    st.selectbox("Comparación rápida", ["Personalizada", *COMPARACIONES_RAPIDAS], key="comparacion_rapida",
                 on_change=aplicar_comparacion_rapida,
                 help="Elige una comparación típica o ajusta tú mismo los grupos (queda como «Personalizada»).")
    col_a, col_b = st.columns(2, gap="large")
    with col_a:
        grupo_a, desc_a = definir_grupo("A", base)
    with col_b:
        grupo_b, desc_b = definir_grupo("B", base)

    if grupo_a.empty or grupo_b.empty:
        st.warning("Uno de los grupos no tiene productos. Cambia sus condiciones, el nivel de grasa o los "
                   "tipos de producto incluidos.")
        return
    tabla = comparar_grupos(grupo_a, grupo_b)
    if tabla.empty:
        st.warning("No hay nutrientes con datos en ambos grupos.")
        return

    st.divider()
    relevantes = tabla[(tabla["lectura"] != "≈ igual") & (tabla["confianza"] == "consistente")]
    dudosas = tabla[(tabla["lectura"] != "≈ igual") & (tabla["confianza"] != "consistente")]
    tipo_txt = legible(tipo) + ("" if grasa == CUALQUIERA else f" {legible(grasa)}")
    if relevantes.empty:
        resumen = (f"Los {len(grupo_a)} productos del grupo A ({desc_a}) **no muestran diferencias consistentes** "
                   f"con los {len(grupo_b)} del grupo B ({desc_b}).")
    else:
        cambios = ", ".join(f"**{r['lectura'][2:]} {r['nutriente'].split(' (')[0].lower()}**"
                            for _, r in relevantes.iterrows())
        resumen = (f"En {tipo_txt}, los {len(grupo_a)} productos del grupo A ({desc_a}) tienen en promedio "
                   f"{cambios} que los {len(grupo_b)} del grupo B ({desc_b}).")
    st.markdown(resumen)
    if not dudosas.empty:
        st.caption("Diferencias que podrían deberse al azar (pocos productos o mucha variación): "
                   + ", ".join(f"{r['nutriente'].split(' (')[0].lower()} ({r['lectura'][2:]})"
                               for _, r in dudosas.iterrows()) + ".")
    if min(len(grupo_a), len(grupo_b)) < 5:
        st.warning("Un grupo tiene menos de 5 productos: el promedio es poco confiable.")

    izquierda, derecha = st.columns([3, 2], gap="large")
    with izquierda:
        st.markdown("**Promedio por 100 g** (cada renglón con su propia escala, desde 0)")
        st.altair_chart(grafico_grupos(tabla))
    with derecha:
        st.markdown("**Tabla de la comparación**")
        st.dataframe(tabla[["nutriente", "A", "B", "lectura", "confianza"]], hide_index=True, width="stretch",
                     column_config={"nutriente": "Nutriente", "A": "Grupo A", "B": "Grupo B",
                                    "lectura": "A frente a B", "confianza": st.column_config.TextColumn(
                                        "Confianza", help="«consistente»: la diferencia se mantiene entre "
                                        "productos (prueba de Mann-Whitney, p < 0,05). «podría ser azar»: los "
                                        "valores de ambos grupos se solapan demasiado.")})
    columnas = ["description", "brand_owner", "protein_g", "fat_g", "sugars_g", "calcium_mg", "url_fuente"]
    config_cols = {"description": "Producto", "brand_owner": "Marca", "protein_g": "Proteína (g)",
                   "fat_g": "Grasa (g)", "sugars_g": "Azúcares (g)", "calcium_mg": "Calcio (mg)",
                   "url_fuente": st.column_config.LinkColumn("Fuente", display_text="ver en USDA")}
    for grupo, datos in (("A", grupo_a), ("B", grupo_b)):
        with st.expander(f"Ver los {len(datos)} productos del grupo {grupo}"):
            st.dataframe(datos[columnas].fillna({"brand_owner": "—"}), hide_index=True, width="stretch",
                         column_config=config_cols)


# ------------------------------------------------------ 3. árbol de decisiones

def texto_condicion(condicion):
    """'tratamiento_termico = uht' -> 'Tratamiento térmico = uht'."""
    m = re.match(r"^(\S+) (=|≠|≤|>) (.+)$", condicion)
    if not m:
        return condicion
    campo, op, valor = m.groups()
    return f"{nombre_campo(campo)} {op} {legible(valor)}"


VEREDICTO_ESTILO = {  # (símbolo, color)
    "permitida": ("✓", "#1f9d55"),
    "requiere_verificacion": ("!", "#c98a00"),
    "fuera_de_norma": ("✕", "#e34948"),
}
VEREDICTO_AYUDA = {
    "permitida": "Ningún hallazgo de respaldo fuera de norma, requisitos verificados y (si hay límites de "
                 "proceso) la mayoría del respaldo demuestra cumplirlos.",
    "requiere_verificacion": "Faltan datos de proceso en los hallazgos o hay requisitos sin verificar en normas.csv.",
    "fuera_de_norma": "La mayoría de los hallazgos que respaldan la regla se obtuvo con un proceso fuera de "
                      "la norma: no sirve para diseñar el producto.",
}


def bloque_veredicto(v):
    simbolo, color = VEREDICTO_ESTILO[v["veredicto"]]
    motivos = "".join(f"<li>{html.escape(m)}</li>" for m in v["motivos"])
    return f"""
  <div style="margin-top:8px; font-size:.85rem">
    <span style="display:inline-block; border:1px solid {color}; color:{color}; border-radius:10px;
                 padding:0 8px; font-weight:700">{simbolo} Norma: {html.escape(normatividad.VEREDICTOS[v["veredicto"]])}</span>
    <span style="opacity:.7"> · respaldo: {v["cumple"]} cumplen, {v["fuera"]} fuera, {v["sin_datos"]} sin datos</span>
    {f'<ul style="margin:4px 0; opacity:.8">{motivos}</ul>' if motivos else ''}
  </div>"""


def pestana_arbol(conn):
    tabla, _ = actualizar_tabla(conn)
    if tabla.empty:
        st.info("Todavía no hay observaciones. Corre python extract_llm_insights.py")
        return

    st.subheader("Árbol de decisiones")
    st.caption("El árbol busca qué características (tratamiento, raza, especie…) separan los hallazgos que "
               "dicen «mejora» de los que dicen «empeora». Cada tarjeta es una regla: si una leche cumple sus "
               "condiciones, eso es lo que dice la mayoría de la evidencia.")

    conteo = tabla["variable_resultado"].value_counts()
    opciones_var = ["(todas)"] + conteo.index.tolist()
    c1, c2, c3, c4, c5 = st.columns([3, 2, 2, 2, 2])
    variable = c1.selectbox("Variable medida", opciones_var, index=1,
                            format_func=lambda v: v if v == "(todas)" else legible(v),
                            help="Hallazgos por variable: " + ", ".join(f"{legible(v)}: {n}" for v, n in conteo.items()))
    solo_primaria = c2.checkbox("Solo estudios primarios", value=True,
                                help="Excluye revisiones bibliográficas y modelos, que resumen otros estudios.")
    profundidad = c3.slider("Profundidad", 2, 6, 3, help="Cuántas condiciones puede encadenar una regla.")
    min_hojas = c4.slider("Mínimo de hallazgos por regla", 2, 10, 3)
    dentro_de_norma = c5.checkbox("Solo dentro de la norma", value=False,
                                  help="Excluye hallazgos cuyo proceso (temperatura, tiempo, almacenamiento…) "
                                       "está fuera de los límites legales de normas.csv.")

    res = arbol_decision.entrenar(tabla, None if variable == "(todas)" else variable,
                                  solo_primaria, profundidad, min_hojas, dentro_de_norma=dentro_de_norma)
    if "error" in res:
        st.warning(res["error"] + " Prueba con otra variable medida o desmarca «Solo estudios primarios».")
        return

    a, b, c = st.columns(3)
    a.metric("Hallazgos usados", len(res["y"]))
    v = res["validacion"]
    if v:
        b.metric("Exactitud balanceada", f"{v['media']:.0%}", f"{v['media'] - res['azar']:+.0%} vs. azar",
                 help="Qué tan bien predice el árbol hallazgos que no vio al entrenar (validación cruzada). "
                      f"Adivinar al azar daría {res['azar']:.0%}.")
    c.metric("Características disponibles", res["X"].shape[1])
    if v and v["media"] < res["azar"] + 0.1:
        st.warning("El árbol apenas supera al azar: sus reglas son orientativas, no conclusiones. "
                   "Hacen falta más hallazgos o datos más completos (raza, pH, alimentación…).")

    normas = normatividad.leer(conn)
    lista_reglas = arbol_decision.reglas(res)
    for regla in lista_reglas:
        regla["normativo"] = normatividad.veredicto_regla(tabla.loc[regla["filas"]], regla["efecto"],
                                                          normas, regla["condiciones"])
    conteo_veredictos = pd.Series([r["normativo"]["veredicto"] for r in lista_reglas]).value_counts()
    columnas_v = st.columns(len(normatividad.VEREDICTOS))
    for col, (clave, nombre) in zip(columnas_v, normatividad.VEREDICTOS.items()):
        col.metric(f"Reglas: {nombre.lower()}", int(conteo_veredictos.get(clave, 0)),
                   help=VEREDICTO_AYUDA[clave])

    st.markdown("**Reglas** (de más a menos hallazgos)")
    izquierda, derecha = st.columns(2, gap="large")
    for i, regla in enumerate(lista_reglas):
        condiciones = "".join(f"<li>{html.escape(texto_condicion(c))}</li>" for c in regla["condiciones"])
        distribucion = " · ".join(f"{legible(k)}: {n}" for k, n in
                                  sorted(regla["distribucion"].items(), key=lambda kv: ORDEN_EFECTO.index(kv[0])))
        requisitos = normatividad.requisitos_regla(normas, regla["condiciones"])
        bloque_normas = ""
        if requisitos:
            items = "".join(f"<li>{html.escape(r)}</li>" for r in requisitos)
            bloque_normas = f"""
  <details style="margin-top:6px">
    <summary style="cursor:pointer; font-size:.85rem; opacity:.75">Requisitos legales que activa ({len(requisitos)})</summary>
    <ul style="margin:4px 0; font-size:.85rem">{items}</ul>
  </details>"""
        cuerpo = f"""
  <div style="margin-top:6px; font-size:.85rem; opacity:.75">SI</div>
  <ul style="margin:2px 0 6px 0">{condiciones}</ul>
  <div style="font-size:.85rem; opacity:.75">Hallazgos en esta regla: {html.escape(distribucion)}</div>
  {bloque_veredicto(regla["normativo"])}{bloque_normas}"""
        with (izquierda if i % 2 == 0 else derecha):
            tarjeta(regla["efecto"], f"{regla['aciertos']} de {regla['n']} hallazgos "
                                     f"({regla['aciertos'] / regla['n']:.0%})", cuerpo)

    st.markdown("**Factores que más pesan en el árbol**")
    imp = res["importancias"].rename(index=texto_condicion).mul(100).round(1).reset_index()
    imp.columns = ["factor", "importancia"]
    st.altair_chart(
        alt.Chart(imp).mark_bar(size=14, cornerRadius=4, color=COLOR_SERIE).encode(
            y=alt.Y("factor:N", title=None, sort="-x", axis=alt.Axis(labelLimit=260)),
            x=alt.X("importancia:Q", title="Importancia (%)"),
            tooltip=["factor:N", alt.Tooltip("importancia:Q", title="%")],
        ).properties(height=alt.Step(26)),
        width="stretch",
    )
    with st.expander("Ver los hallazgos usados para entrenar"):
        usados = tabla.loc[res["y"].index]
        st.dataframe(usados[["variable_resultado", "categoria_factor", "comparacion", "efecto", "matriz",
                             "tipo_beta_caseina", "especie_leche", "raza", "tratamiento_termico", "doi"]],
                     hide_index=True, width="stretch")


# -------------------------------------------------------------- 4. normatividad

def pestana_normatividad(conn):
    todas = normatividad.leer(conn, todas=True)
    if todas.empty:
        st.info(f"No hay normas cargadas: revisa {config.NORMAS_CSV}.")
        return

    st.subheader("Límites legales para el producto")
    st.caption(f"Vienen de {config.NORMAS_CSV} (edítalo en Excel y recarga la página). Delimitan el espacio de "
               "decisión: un proceso o una composición fuera de estos rangos no se puede vender con esa denominación.")
    jurisdicciones = st.multiselect("Jurisdicciones", sorted(todas["jurisdiccion"].unique()),
                                    default=[j for j in config.JURISDICCIONES_NORMAS if j in set(todas["jurisdiccion"])],
                                    format_func=legible)
    normas = todas[todas["jurisdiccion"].isin(jurisdicciones)]
    pendientes = normas.loc[normas["verificado"] != "si", "norma_id"].nunique()
    if pendientes:
        st.warning(f"{pendientes} de {normas['norma_id'].nunique()} requisitos están sin verificar contra el texto "
                   "oficial. Confírmalos y pon verificado = si en el CSV antes de usarlos para decidir.")

    c1, c2, c3, c4 = st.columns(4)
    perfil = {
        "matriz": a_valor("matriz", c1.selectbox("Tipo de producto", opciones("matriz"), format_func=legible)),
        "tratamiento_termico": a_valor("tratamiento_termico", c2.selectbox(
            "Tratamiento térmico", opciones("tratamiento_termico"), format_func=legible)),
        "especie_leche": a_valor("especie_leche", c3.selectbox(
            "Especie", opciones("especie_leche"), format_func=legible)),
        "nivel_grasa": a_valor("nivel_grasa", c4.selectbox(
            "Nivel de grasa", [CUALQUIERA, "entera", "semidescremada", "descremada"], format_func=legible)),
    }
    req = normatividad.requisitos(normas, perfil)
    st.caption(f"{req['norma_id'].nunique()} requisitos podrían aplicar a este perfil "
               "(los que no dependen de un filtro que dejaste en «cualquiera» también se muestran).")
    st.dataframe(
        req[["tipo", "norma_id", "norma", "articulo", "alternativa", "parametro", "rango", "descripcion",
             "verificado", "url"]].fillna(""),
        column_config={"tipo": "Tipo", "norma_id": "Requisito", "norma": "Norma", "articulo": "Artículo",
                       "alternativa": "Alternativa", "parametro": "Parámetro", "rango": "Límite",
                       "descripcion": "Descripción", "verificado": "Verificado",
                       "url": st.column_config.LinkColumn("Fuente", display_text="ver")},
        hide_index=True, width="stretch",
    )

    st.subheader("Hallazgos de los papers frente a la norma")
    st.caption("Se evalúan con los datos que trae cada hallazgo (temperatura, tiempo, composición…). "
               "«Sin datos» es lo más común: los abstracts rara vez dan las condiciones exactas del proceso.")
    tabla, _ = actualizar_tabla(conn)
    evaluada = normatividad.evaluar_hallazgos(tabla, normas)
    conteo = evaluada["estado_normativo"].value_counts()
    a, b, c = st.columns(3)
    a.metric("Dentro de la norma", int(conteo.get("cumple", 0)))
    b.metric("Fuera de la norma", int(conteo.get("fuera_de_norma", 0)))
    c.metric("Sin datos para evaluar", int(conteo.get("sin_datos", 0)))
    fuera = evaluada[evaluada["estado_normativo"] == "fuera_de_norma"]
    if not fuera.empty:
        st.dataframe(fuera[["comparacion", "variable_resultado", "efecto", "detalle_normativo", "doi"]],
                     column_config={"comparacion": "Comparación", "variable_resultado": "Variable medida",
                                    "efecto": "Efecto", "detalle_normativo": "Qué incumple",
                                    "doi": st.column_config.LinkColumn("Fuente", display_text="DOI")},
                     hide_index=True, width="stretch")

    st.subheader("Productos del mercado (USDA) frente a la norma")
    st.caption("Composición declarada frente a los límites de su denominación (ej. grasa mínima de leche entera). "
               "El USDA reporta g/100 g y algunas normas % m/v: la diferencia en leche es de ~3 %.")
    prod = normatividad.evaluar_productos(conn, normas)
    if prod.empty:
        st.info("Ningún producto tiene datos que permitan evaluar un requisito de estas jurisdicciones.")
        return
    st.dataframe(prod.groupby(["norma_id", "estado"]).size().unstack(fill_value=0), width="stretch")
    malos = prod[prod["estado"] == "no_cumple"]
    if not malos.empty:
        st.dataframe(malos[["description", "brand_owner", "norma_id", "detalle", "url_fuente"]].fillna("—"),
                     column_config={"description": "Producto", "brand_owner": "Marca", "norma_id": "Requisito",
                                    "detalle": "Qué incumple",
                                    "url_fuente": st.column_config.LinkColumn("Fuente", display_text="ver en USDA")},
                     hide_index=True, width="stretch")


# ------------------------------------------------------------ 5. explorar datos

def pestana_explorar(conn):
    st.subheader("Productos del mercado (USDA)")
    u = pd.read_sql("SELECT * FROM alimentos_usda", conn)
    u["origen"] = u["data_type"].map(lambda t: "Marca" if t == "Branded" else "Genérico USDA")
    c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
    tipos = c1.multiselect("Tipo de producto", sorted(u["tipo_producto"].dropna().unique()), default=["leche"],
                           format_func=legible)
    subtipos = c2.multiselect("Subtipo", fetch_usda.SUBTIPOS, default=["natural"], format_func=legible)
    origenes = c3.multiselect("Origen", ["Marca", "Genérico USDA"], default=["Marca", "Genérico USDA"],
                              help="Marca: etiqueta declarada por el fabricante. Genérico USDA: promedio "
                                   "medido en laboratorio para ese tipo de alimento (sin marca).")
    solo_a2 = c4.checkbox("Solo A2")
    if tipos:
        u = u[u["tipo_producto"].isin(tipos)]
    if subtipos:
        u = u[u["subtipo"].isin(subtipos)]
    u = u[u["origen"].isin(origenes)]
    if solo_a2:
        u = u[u["tipo_beta_caseina"] == "A2"]
    st.caption(f"{len(u)} productos")
    u = u.replace("no_especificado", "—").fillna({"brand_owner": "—"})
    st.dataframe(
        u[["description", "origen", "brand_owner", "tipo_producto", "subtipo", "tipo_beta_caseina", "tratamiento_termico",
           "nivel_grasa", "sin_lactosa", "organico", "pastoreo"] + list(NUTRIENTES) + ["url_fuente"]],
        column_config={**NUTRIENTES,
                       "description": "Producto", "origen": "Origen", "brand_owner": "Marca",
                       "tipo_producto": "Tipo", "subtipo": "Subtipo",
                       "tipo_beta_caseina": "Beta-caseína", "tratamiento_termico": "Tratamiento",
                       "nivel_grasa": "Grasa", "sin_lactosa": "Sin lactosa", "organico": "Orgánico",
                       "pastoreo": "Pastoreo",
                       "url_fuente": st.column_config.LinkColumn("Fuente", display_text="ver en USDA")},
        hide_index=True, width="stretch",
    )

    st.subheader("Qué tan completos están los hallazgos")
    obs = cargar_observaciones(conn)
    if obs.empty:
        return
    categoricas = ["categoria_factor"] + [c for c in ETIQUETAS if c != "lactosa_reducida"] + ["region"]
    completitud = pd.concat([
        (obs[categoricas].notna() & (obs[categoricas] != "no_especificado")).mean(),
        obs[CAMPOS_NUMERICOS].notna().mean(),
    ]).mul(100).round(0).reset_index()
    completitud.columns = ["columna", "porcentaje"]
    completitud["columna"] = completitud["columna"].map(nombre_campo)
    st.altair_chart(
        alt.Chart(completitud).mark_bar(size=14, cornerRadius=4, color=COLOR_SERIE).encode(
            y=alt.Y("columna:N", title=None, sort="-x", axis=alt.Axis(labelLimit=220, labelOverlap=False)),
            x=alt.X("porcentaje:Q", title="% de hallazgos con el dato", scale=alt.Scale(domain=[0, 100])),
            tooltip=["columna:N", alt.Tooltip("porcentaje:Q", title="%")],
        ).properties(height=alt.Step(26)),
        width="stretch",
    )
    st.caption("Una columna casi vacía no le sirve al árbol de decisiones. Los abstracts rara vez "
               "dan pH, raza o composición: leer los PDFs completos subiría estos porcentajes.")
    tabla, _ = actualizar_tabla(conn)
    st.download_button("Descargar la tabla del árbol (CSV)", tabla.to_csv(index=False).encode("utf-8"),
                       file_name="tabla_arbol.csv", mime="text/csv")


def main():
    st.set_page_config(page_title="Selema · Evidencia y mercado", layout="wide")
    conn = database.conectar(config.DB_PATH)

    st.title("Evidencia científica y mercado lácteo")
    n_papers, n_obs, n_prod = (conn.execute(q).fetchone()[0] for q in (
        "SELECT COUNT(*) FROM extracciones WHERE estado IN ('ok', 'no_relevante')",
        f"SELECT COUNT(*) FROM observaciones o WHERE {database.ACEPTADA_SQL}",
        "SELECT COUNT(*) FROM alimentos_usda",
    ))
    a, b, c = st.columns(3)
    a.metric("Papers leídos por la IA", n_papers)
    b.metric("Hallazgos válidos", n_obs)
    c.metric("Productos del mercado (USDA)", n_prod)

    ciencia, mercado, arbol, normas, explorar = st.tabs(["Qué dice la ciencia", "Comparar en el mercado",
                                                         "Árbol de decisiones", "Normatividad", "Explorar datos"])
    with ciencia:
        pestana_ciencia(conn)
    with mercado:
        pestana_comparar(conn)
    with arbol:
        pestana_arbol(conn)
    with normas:
        pestana_normatividad(conn)
    with explorar:
        pestana_explorar(conn)


main()
