"""
Base de datos SQLite de la búsqueda (output/selema.db).

Tablas:
- papers:         metadatos y abstract de cada paper (desde OpenAlex y
                  Semantic Scholar). Incluye motor_busqueda (qué plataforma
                  lo encontró), motor_pdf (qué plataforma dio el PDF que se
                  terminó usando), pdf_url y pdf_bloqueado (ver
                  fetch_semantic_scholar.revisar_acceso_pdf).

El procesamiento de los papers (../procesamiento/database_proc.py) agrega sus
propias tablas a esta misma base.

Se puede abrir con DB Browser for SQLite (https://sqlitebrowser.org) para
revisar o corregir a mano.
"""

import sqlite3


# Columnas nuevas de `papers` (Semantic Scholar): se agregan con ALTER TABLE
# a una base ya existente, porque CREATE TABLE IF NOT EXISTS no las crearía.
COLUMNAS_PAPERS_NUEVAS = {
    "motor_busqueda": "TEXT",
    "motor_pdf": "TEXT",
    "pdf_url": "TEXT",
    "pdf_bloqueado": "TEXT",
}

# Tabla de papers aparte: también la usan las bases de los proyectos de la
# interfaz web (almacen.py)
SCHEMA_PAPERS = """
CREATE TABLE IF NOT EXISTS papers (
    paper_id TEXT PRIMARY KEY,
    openalex_id TEXT,
    doi TEXT,
    title TEXT,
    year INTEGER,
    cited_by_count INTEGER,
    is_oa INTEGER,
    oa_url TEXT,
    source TEXT,
    abstract TEXT,
    matched_query TEXT,
    score REAL,
    motor_busqueda TEXT,  -- openalex | semantic_scholar | scopus | scihub (varios separados por "; ")
    motor_pdf TEXT,        -- qué plataforma dio el PDF que se terminó usando | ninguno
    pdf_url TEXT,
    pdf_bloqueado TEXT     -- si | no | NULL (no se revisó o no hay PDF)
);
"""

SCHEMA = SCHEMA_PAPERS


def conectar(ruta):
    conn = sqlite3.connect(ruta)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _migrar(conn, "papers", COLUMNAS_PAPERS_NUEVAS)
    return conn


def _migrar(conn, tabla, columnas):
    """Agrega a una base existente las columnas nuevas del esquema."""
    existentes = {r["name"] for r in conn.execute(f"PRAGMA table_info({tabla})")}
    with conn:
        for nombre, tipo in columnas.items():
            if nombre not in existentes:
                conn.execute(f"ALTER TABLE {tabla} ADD COLUMN {nombre} {tipo}")


def id_paper(row):
    return row.get("doi") or row.get("openalex_id")


def dois_existentes(conn):
    """DOI de los papers que ya están guardados, para no volver a contarlos
    como "nuevos" en la próxima búsqueda (ver main.py)."""
    filas = conn.execute("SELECT doi FROM papers WHERE doi IS NOT NULL").fetchall()
    return {f["doi"] for f in filas}


def _limpiar(valor):
    """NaN se evalúa distinto que sí mismo: algunas APIs lo devuelven para
    vacíos y SQLite necesita None."""
    if valor != valor:  # NaN
        return None
    return valor


def guardar_papers(conn, rows):
    columnas = ["paper_id", "openalex_id", "doi", "title", "year", "cited_by_count",
                "is_oa", "oa_url", "source", "abstract", "matched_query", "score",
                "motor_busqueda", "motor_pdf", "pdf_url", "pdf_bloqueado"]
    datos = []
    for row in rows:
        row = {k: _limpiar(v) for k, v in row.items()}
        row["paper_id"] = id_paper(row)
        datos.append([row.get(c) for c in columnas])
    marcadores = ", ".join("?" for _ in columnas)
    actualizar = ", ".join(f"{c}=excluded.{c}" for c in columnas[1:])
    with conn:
        conn.executemany(
            f"INSERT INTO papers ({', '.join(columnas)}) VALUES ({marcadores}) "
            f"ON CONFLICT(paper_id) DO UPDATE SET {actualizar}",
            datos,
        )
