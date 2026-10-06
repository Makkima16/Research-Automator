"""
Tablas del procesamiento en la base de datos SQLite del proyecto
(../busqueda/output/selema.db).

Las tablas `papers` y `alimentos_usda` las crea y las llena la búsqueda
(../busqueda/database.py). Aquí se agregan:
- textos_completos: texto completo de los papers de acceso abierto (Europe PMC
                  o PDF) y los fragmentos con condiciones de proceso que se le
                  envían al LLM (ver fetch_fulltext.py).
- extracciones:   respuesta cruda del LLM por paper (sirve de caché: no se
                  vuelve a pagar/llamar al LLM si el abstract no cambió).
- observaciones:  una fila por hallazgo extraído y validado. Es la base de
                  la tabla del árbol de decisiones.
- equiv_matriz, equiv_tratamiento: equivalencias entre el vocabulario de los
                  papers y el del USDA (ej. leche_liquida <-> leche).
- evidencia_mercado (vista): cada hallazgo de los papers junto con cuántos
                  productos del mercado (USDA) tienen esas características y
                  su composición promedio.
- normas:         límites legales por parámetro (temperatura de pasteurización,
                  grasa mínima...). Se copia de normas.csv cada vez que se abre
                  la base: para corregir una norma, edita el CSV.

Se puede abrir con DB Browser for SQLite (https://sqlitebrowser.org) para
revisar o corregir a mano. Para aprobar o descartar una fila manualmente,
pon 'aprobada' o 'rechazada' en observaciones.revision_humana.
"""

import csv
import json
import os
from datetime import datetime, timezone

import config_proc as config  # primero: agrega ../busqueda a la ruta de importación
import database as db_busqueda
import fetch_usda
from esquema import Observacion


def _tipo_sql(nombre):
    anotacion = Observacion.model_fields[nombre].annotation
    if anotacion == (int | None):
        return "INTEGER"
    if anotacion == (float | None):
        return "REAL"
    if anotacion == (bool | None):
        return "INTEGER"
    return "TEXT"


# `comparacion` no la escribe el LLM: se arma como "factor_evaluado vs referencia".
# `cita_en` dice dónde se encontró la cita: abstract | texto_completo
COLUMNAS_OBS = {**{c: _tipo_sql(c) for c in Observacion.model_fields}, "comparacion": "TEXT", "cita_en": "TEXT"}
_COLUMNAS_OBS = ",\n    ".join(f"{c} {t}" for c, t in COLUMNAS_OBS.items())

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS textos_completos (
    paper_id TEXT PRIMARY KEY REFERENCES papers(paper_id),
    estado TEXT,              -- ok | no_disponible | error
    fuente TEXT,              -- europepmc | pdf
    url TEXT,
    texto TEXT,               -- texto completo (sin referencias); sirve para verificar citas
    fragmentos TEXT,          -- frases con condiciones de proceso que se envían al LLM
    n_caracteres INTEGER,
    error TEXT,
    descargado_en TEXT
);

CREATE TABLE IF NOT EXISTS extracciones (
    paper_id TEXT PRIMARY KEY REFERENCES papers(paper_id),
    modelo TEXT,
    estado TEXT,              -- ok | error | sin_abstract | no_relevante
    texto_hash TEXT,
    respuesta_json TEXT,
    error TEXT,
    creado_en TEXT
);

CREATE TABLE IF NOT EXISTS observaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id TEXT NOT NULL REFERENCES papers(paper_id),
    {_COLUMNAS_OBS},
    cita_verificada INTEGER,
    valida INTEGER,
    problemas TEXT,
    revision_humana TEXT      -- NULL | aprobada | rechazada
);

CREATE INDEX IF NOT EXISTS idx_obs_paper ON observaciones(paper_id);

CREATE TABLE IF NOT EXISTS equiv_matriz (
    matriz TEXT,              -- vocabulario de los papers
    tipo_producto TEXT        -- vocabulario del USDA
);

CREATE TABLE IF NOT EXISTS equiv_tratamiento (
    tratamiento TEXT,
    tratamiento_usda TEXT
);
"""


# Papers -> USDA. Lo que no aparece aquí (ej. matriz "otro", tratamiento
# "esterilizado") no tiene equivalente en el mercado y no cruza con productos.
EQUIV_MATRIZ = {
    "leche_liquida": ["leche"],
    "yogur_fermentado": ["yogur", "kefir"],
    "queso": ["queso"],
    "leche_en_polvo_formula": ["leche_en_polvo"],
}
EQUIV_TRATAMIENTO = {
    "crudo": ["crudo"],
    "pasteurizado": ["pasteurizado", "pasteurizado_lento"],
    "ultrapasteurizado": ["ultrapasteurizado"],
    "uht": ["uht"],
}

# Observaciones que entran a la tabla del árbol (mismo criterio que build_dataset.py)
ACEPTADA_SQL = ("((o.valida = 1 AND COALESCE(o.revision_humana, '') != 'rechazada') "
                "OR o.revision_humana = 'aprobada')")

NUTRIENTES_CRUCE = ["energy_kcal", "protein_g", "fat_g", "sat_fat_g", "sugars_g",
                    "calcium_mg", "sodium_mg", "vitamin_d_iu"]


# Valores que el USDA no registra en sus etiquetas: el filtro no se puede
# aplicar a los productos (se ignora en el cruce y la interfaz lo avisa)
NO_APLICA_MERCADO = {
    "especie_leche": {"otra"},
    "tratamiento_termico": {"otro"},
    "raza": {"otra", "cruce"},
    "sistema_alimentacion": {"estabulado", "mixto"},
}

# Por defecto solo se comparan productos naturales (sin buttermilk, condensadas,
# en polvo, modificadas ni saborizadas)
SUBTIPOS_COMPARABLES = ("natural",)


def aplica_en_mercado(campo, valor):
    return valor is None or valor not in NO_APLICA_MERCADO.get(campo, set())


def condicion_mercado(v, subtipos=SUBTIPOS_COMPARABLES):
    """Condición SQL que decide si un producto `u` del USDA es compatible con
    un perfil de características de los papers. `v(columna)` devuelve la
    expresión SQL de cada característica (una columna de `o` o un parámetro).

    Una característica vacía o "no_especificado" no restringe. A1A2 equivale a
    los productos que no se venden como A2 (la leche convencional mezcla ambas);
    A1 no cruza con nada, porque en el mercado no se vende leche solo A1.
    Solo entran los productos de los `subtipos` indicados (por defecto los
    naturales), para no comparar leche con buttermilk o leche condensada.
    """
    return f"""
    ({v('matriz')} IS NULL OR u.tipo_producto IN
        (SELECT tipo_producto FROM equiv_matriz WHERE matriz = {v('matriz')}))
    AND ({v('especie_leche')} IS NULL OR {v('especie_leche')} IN ('no_especificado', 'otra')
         OR u.especie_leche = {v('especie_leche')})
    AND ({v('tipo_beta_caseina')} IS NULL OR {v('tipo_beta_caseina')} = 'no_especificado'
         OR u.tipo_beta_caseina = CASE {v('tipo_beta_caseina')} WHEN 'A2' THEN 'A2'
                                   WHEN 'A1A2' THEN 'no_especificado' END)
    AND ({v('tratamiento_termico')} IS NULL OR {v('tratamiento_termico')} IN ('no_especificado', 'otro')
         OR u.tratamiento_termico IN
            (SELECT tratamiento_usda FROM equiv_tratamiento WHERE tratamiento = {v('tratamiento_termico')}))
    AND ({v('raza')} IS NULL OR {v('raza')} IN ('no_especificado', 'otra', 'cruce') OR u.raza = {v('raza')})
    AND ({v('sistema_alimentacion')} IS NULL OR {v('sistema_alimentacion')} != 'pastoreo' OR u.pastoreo = 'si')
    AND ({v('lactosa_reducida')} IS NULL OR ({v('lactosa_reducida')} = 1) = (u.sin_lactosa = 'si'))
    AND u.subtipo IN ({", ".join(repr(s) for s in subtipos if s in fetch_usda.SUBTIPOS) or "''"})
    """


def _crear_cruce(conn):
    promedios = ",\n    ".join(f"ROUND(AVG(u.{n}), 2) AS {n}_prom" for n in NUTRIENTES_CRUCE)
    with conn:
        conn.execute("DELETE FROM equiv_matriz")
        conn.executemany("INSERT INTO equiv_matriz VALUES (?, ?)",
                         [(m, t) for m, ts in EQUIV_MATRIZ.items() for t in ts])
        conn.execute("DELETE FROM equiv_tratamiento")
        conn.executemany("INSERT INTO equiv_tratamiento VALUES (?, ?)",
                         [(p, u) for p, us in EQUIV_TRATAMIENTO.items() for u in us])
        conn.execute("DROP VIEW IF EXISTS evidencia_mercado")
        conn.execute(f"""
CREATE VIEW evidencia_mercado AS
SELECT o.id AS observacion_id, o.paper_id, o.categoria_factor, o.factor_evaluado, o.referencia,
    o.variable_resultado, o.efecto, o.comparacion,
    o.matriz, o.tipo_beta_caseina, o.especie_leche, o.tratamiento_termico, o.raza,
    o.sistema_alimentacion, o.lactosa_reducida,
    COUNT(u.fdc_id) AS n_productos_mercado,
    {promedios},
    SUBSTR(GROUP_CONCAT(DISTINCT u.description), 1, 300) AS ejemplos_productos
FROM observaciones o
LEFT JOIN alimentos_usda u ON {condicion_mercado(lambda c: 'o.' + c)}
WHERE {ACEPTADA_SQL}
GROUP BY o.id
""")


def conectar(ruta):
    """Abre la base de la búsqueda (tablas papers y alimentos_usda) y le agrega
    las tablas del procesamiento."""
    conn = db_busqueda.conectar(ruta)
    conn.executescript(SCHEMA)
    db_busqueda._migrar(conn, "observaciones", COLUMNAS_OBS)
    _crear_cruce(conn)
    cargar_normas(conn)
    return conn


# Se recrea en cada carga (es una copia de normas.csv), así un cambio de
# columnas en el CSV no exige migrar la base
SCHEMA_NORMAS = """
DROP TABLE IF EXISTS normas;
CREATE TABLE normas (
    norma_id TEXT,            -- filas con el mismo id forman un requisito
    jurisdiccion TEXT,        -- colombia | codex | ee_uu | union_europea
    norma TEXT,
    articulo TEXT,
    tipo TEXT,                -- proceso | composicion | microbiologico | almacenamiento | etiquetado | requisito...
    matriz TEXT,              -- vacío = aplica a cualquier matriz
    tratamiento_termico TEXT, -- vacío = cualquier tratamiento
    nivel_grasa TEXT,         -- vacío = cualquier nivel de grasa
    especie_leche TEXT,       -- vacío = cualquier especie (los límites de composición suelen ser de leche de vaca)
    parametro TEXT,           -- columna de observaciones (temperatura_c...) u otro; 'requisito' = sin límite numérico
    alternativa TEXT,         -- alternativas del mismo requisito (ej. pasteurización lenta o rápida): basta cumplir una
    minimo REAL,
    maximo REAL,
    unidad TEXT,
    descripcion TEXT,
    verificado TEXT,          -- si = confirmado contra el texto oficial
    url TEXT
);
"""

COLUMNAS_NORMAS = ["norma_id", "jurisdiccion", "norma", "articulo", "tipo", "matriz", "tratamiento_termico",
                   "nivel_grasa", "especie_leche", "parametro", "alternativa", "minimo", "maximo", "unidad", "descripcion",
                   "verificado", "url"]


def cargar_normas(conn, ruta=config.NORMAS_CSV):
    """Reemplaza la tabla `normas` con el contenido del CSV (vacíos -> NULL)."""
    if not os.path.exists(ruta):
        return
    with open(ruta, encoding="utf-8", newline="") as f:
        filas = list(csv.DictReader(f))
    faltan = set(COLUMNAS_NORMAS) - set(filas[0] if filas else COLUMNAS_NORMAS)
    if faltan:
        raise ValueError(f"{ruta} no tiene las columnas: {', '.join(sorted(faltan))}")
    datos = []
    for n, fila in enumerate(filas, start=2):
        valores = {c: (fila[c].strip() or None) if fila[c] is not None else None for c in COLUMNAS_NORMAS}
        for c in ("minimo", "maximo"):
            if valores[c] is not None:
                try:
                    valores[c] = float(valores[c])
                except ValueError:
                    raise ValueError(f"{ruta}, línea {n}: '{valores[c]}' no es un número en la columna {c}")
        datos.append([valores[c] for c in COLUMNAS_NORMAS])
    conn.executescript(SCHEMA_NORMAS)
    with conn:
        conn.executemany(f"INSERT INTO normas VALUES ({', '.join('?' for _ in COLUMNAS_NORMAS)})", datos)


def extraccion_existente(conn, paper_id):
    return conn.execute(
        "SELECT * FROM extracciones WHERE paper_id = ?", (paper_id,)
    ).fetchone()


def guardar_extraccion(conn, paper_id, modelo, estado, texto_hash,
                       respuesta=None, error=None, observaciones=()):
    """Guarda la respuesta del LLM y reemplaza las observaciones del paper.
    `observaciones` es una lista de (obs_dict, valida, problemas)."""
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    columnas = list(Observacion.model_fields) + ["comparacion", "cita_en", "cita_verificada", "valida", "problemas"]
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO extracciones VALUES (?, ?, ?, ?, ?, ?, ?)",
            (paper_id, modelo, estado, texto_hash,
             json.dumps(respuesta, ensure_ascii=False) if respuesta is not None else None,
             error, ahora),
        )
        conn.execute("DELETE FROM observaciones WHERE paper_id = ?", (paper_id,))
        for obs, valida, problemas in observaciones:
            valores = [obs.get(c) for c in columnas[:-2]] + [int(valida), "; ".join(problemas) or None]
            conn.execute(
                f"INSERT INTO observaciones (paper_id, {', '.join(columnas)}) "
                f"VALUES (?, {', '.join('?' for _ in columnas)})",
                [paper_id] + valores,
            )

