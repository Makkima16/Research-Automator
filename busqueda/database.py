"""
Capa de datos en PostgreSQL (busqueda/config.py arma la conexión con las variables NEON_* del .env).

Modelo:
- papers:           metadatos y abstract de cada paper, una sola fila por
                    paper aunque varios proyectos lo compartan.
- proyectos:        un proyecto web por fila; su estado completo (tema,
                    cadenas, parámetros, avance...) vive en estado JSONB.
- papers_proyectos: relación N:M entre proyectos y papers, con el orden del
                    ranking, el score en ese proyecto y si quedó seleccionado.
- estructuras:      piezas de cada paper leídas con Nemotron Parse o Europe PMC
                    (agregadas por ../procesamiento): el payload va en JSONB.
- fichas:           resumen que Nemotron arma con esas piezas, en JSONB.

Los índices GIN sobre las columnas JSONB permiten consultar dentro del
documento (operadores ->>, @>, ?), que es el papel "no relacional" del
motor. Las escrituras usan conn.transaction() (anidable: varios helpers
pueden participar de la misma transacción).

Para explorar la base a mano sirve cualquier cliente de Postgres, p. ej.
    psql "<DATABASE_URL>"
"""

import psycopg
from psycopg.rows import dict_row

import config

# Columnas de `papers` en orden: también las usan las consultas del
# procesamiento y del frontend
COLUMNAS_PAPERS = ["paper_id", "openalex_id", "doi", "title", "year", "cited_by_count",
                   "is_oa", "oa_url", "source", "abstract", "matched_query", "score",
                   "motor_busqueda", "motor_pdf", "pdf_url", "pdf_bloqueado"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS proyectos (
    archivo TEXT PRIMARY KEY,          -- slug del título; lo usa el frontend como clave
    nombre TEXT NOT NULL,
    estado JSONB,                      -- el resto del proyecto, tal como lo maneja la interfaz
    actualizado_en TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS papers (
    paper_id TEXT PRIMARY KEY,         -- DOI o openalex_id (el que exista)
    openalex_id TEXT,
    doi TEXT,
    title TEXT,
    year INTEGER,
    cited_by_count INTEGER,
    is_oa INTEGER,                     -- 0 | 1 (así lo entregan las APIs)
    oa_url TEXT,
    source TEXT,
    abstract TEXT,
    matched_query TEXT,
    score REAL,
    motor_busqueda TEXT,               -- openalex | semantic_scholar | scopus | scihub (varios separados por "; ")
    motor_pdf TEXT,                    -- qué plataforma dio el PDF que se terminó usando | ninguno
    pdf_url TEXT,
    pdf_bloqueado TEXT                 -- si | no | NULL (no se revisó o no hay PDF)
);
CREATE INDEX IF NOT EXISTS idx_papers_doi ON papers (doi);

CREATE TABLE IF NOT EXISTS papers_proyectos (
    archivo TEXT NOT NULL REFERENCES proyectos(archivo) ON DELETE CASCADE ON UPDATE CASCADE,
    paper_id TEXT NOT NULL REFERENCES papers(paper_id) ON DELETE CASCADE,
    orden INTEGER NOT NULL,            -- posición en el ranking del proyecto
    score REAL,
    seleccionado INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (archivo, paper_id)
);
CREATE INDEX IF NOT EXISTS idx_papers_proyectos_archivo ON papers_proyectos (archivo);

CREATE TABLE IF NOT EXISTS estructuras (
    paper_id TEXT PRIMARY KEY REFERENCES papers(paper_id) ON DELETE CASCADE,
    estado TEXT,                       -- ok | no_disponible | error
    fuente TEXT,                       -- europepmc | local | local+nemotron_parse | nemotron_parse
    url TEXT,
    estructura_json JSONB,             -- abstract, últimos párrafos de la intro, conclusión, tablas (nombre + atributos)
    error TEXT,
    creado_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_estructuras_json ON estructuras USING GIN (estructura_json);

CREATE TABLE IF NOT EXISTS fichas (
    paper_id TEXT PRIMARY KEY REFERENCES papers(paper_id) ON DELETE CASCADE,
    estado TEXT,                       -- ok | no_relevante | sin_abstract | error
    cobertura TEXT,                    -- completa (con conclusiones/tablas del paper) | parcial (solo el abstract)
    modelo TEXT,
    texto_hash TEXT,                   -- si piezas y prompt no cambiaron, no se vuelve a llamar al modelo
    ficha_json JSONB,                  -- resumen, objetivo, conclusiones, hallazgos_clave, tablas
    error TEXT,
    creado_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_fichas_json ON fichas USING GIN (ficha_json);
"""


def conectar():
    """Abre la conexión a PostgreSQL (variables NEON_* en .env) y asegura el
    esquema completo: búsqueda, proyectos web y procesamiento comparten esta
    misma base y estas mismas tablas."""
    if not config.DATABASE_URL:
        raise RuntimeError(
            "Faltan datos de conexión: completa NEON_HOST, NEON_DATABASE, "
            "NEON_USER y NEON_PASSWORD (y NEON_SSL_MODE) en el archivo .env "
            "de la raíz, con el formato de .env.example.")
    conn = psycopg.connect(config.DATABASE_URL, row_factory=dict_row)
    conn.execute(SCHEMA)  # sin parámetros: se permiten varias sentencias juntas
    conn.commit()
    # Autocommit: las lecturas no dejan abierta una transacción implícita, así
    # que cada `with conn.transaction()` es una transacción real que se
    # confirma al salir. Sin esto, escribir después de leer en la misma
    # conexión dejaba la escritura como savepoint y se perdía al cerrar.
    conn.autocommit = True
    return conn


def id_paper(row):
    return row.get("doi") or row.get("openalex_id")


def dois_existentes(conn):
    """DOI de los papers que ya están guardados, para no volver a contarlos
    como "nuevos" en la próxima búsqueda (ver main.py)."""
    filas = conn.execute("SELECT doi FROM papers WHERE doi IS NOT NULL").fetchall()
    return {f["doi"] for f in filas}


def _limpiar(valor):
    """NaN se evalúa distinto que sí mismo: algunas APIs lo devuelven para
    vacíos y la base necesita None."""
    if valor != valor:  # NaN
        return None
    return valor


def guardar_papers(conn, rows, proyecto=None, seleccionados=None):
    """Guarda (o actualiza) papers en la tabla `papers`. Con `proyecto`
    (slug de un proyecto web), repuebla además la relación `papers_proyectos`
    con el orden de `rows` (el del ranking), el score de cada paper y si está
    en `seleccionados`. El llamador define la transacción: los helper usan
    conn.transaction(), que se puede anidar."""
    datos = []
    for row in rows:
        row = {k: _limpiar(v) for k, v in row.items()}
        row["paper_id"] = id_paper(row)
        if row.get("is_oa") is not None:
            row["is_oa"] = int(bool(row["is_oa"]))
        datos.append([row.get(c) for c in COLUMNAS_PAPERS])
    columnas = COLUMNAS_PAPERS
    marcadores = ", ".join("%s" for _ in columnas)
    actualizar = ", ".join(f"{c}=excluded.{c}" for c in columnas[1:])
    with conn.transaction():
        cur = conn.cursor()
        if proyecto is not None:
            # También con rows vacío: "reiniciar" deja al proyecto sin papers
            cur.execute("DELETE FROM papers_proyectos WHERE archivo = %s", (proyecto,))
        if datos:
            cur.executemany(
                f"INSERT INTO papers ({', '.join(columnas)}) VALUES ({marcadores}) "
                f"ON CONFLICT (paper_id) DO UPDATE SET {actualizar}",
                datos,
            )
        if proyecto is not None and datos:
            marcados = set(seleccionados or ())
            cur.executemany(
                "INSERT INTO papers_proyectos (archivo, paper_id, orden, score, seleccionado) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (archivo, paper_id) DO UPDATE SET "
                "orden=excluded.orden, score=excluded.score, seleccionado=excluded.seleccionado",
                [(proyecto, d[0], n, d[columnas.index("score")],
                  int(d[0] in marcados)) for n, d in enumerate(datos, start=1)],
            )
