"""
Guarda cada proyecto de la interfaz web (servidor.py) en su propia base
SQLite: output/proyectos/<nombre_del_proyecto>.db. El archivo se llama como el
proyecto (sin tildes ni espacios) y se renombra cuando cambia el título.

Tablas de cada base:
- papers:   los resultados de la última búsqueda, con las mismas columnas que
            la tabla `papers` de selema.db (ver database.py) más
            `seleccionado` (1 si el paper está en la selección del proyecto).
- proyecto: una fila con el resto del proyecto (título, prompt, cadenas,
            parámetros de búsqueda, etapa...) en JSON.

Se puede abrir con DB Browser for SQLite, igual que selema.db.
"""

import json
import os
import re
import sqlite3
import unicodedata
from contextlib import closing

import config
import database

COLUMNAS_PAPERS = ["paper_id", "openalex_id", "doi", "title", "year", "cited_by_count",
                   "is_oa", "oa_url", "source", "abstract", "matched_query", "score",
                   "motor_busqueda", "motor_pdf", "pdf_url", "pdf_bloqueado", "seleccionado"]

# Campos del proyecto que no van al JSON de la tabla `proyecto`: los papers y
# la selección viven en la tabla `papers`; los otros solo existen en memoria
FUERA_DEL_ESTADO = ("papers", "seleccion", "archivo", "busqueda")

SCHEMA = database.SCHEMA_PAPERS + """
CREATE TABLE IF NOT EXISTS proyecto (
    clave TEXT PRIMARY KEY,
    valor TEXT
);
"""


def ruta(archivo):
    return os.path.join(config.PROYECTOS_DIR, archivo)


def _conectar(archivo):
    conn = sqlite3.connect(ruta(archivo))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    database._migrar(conn, "papers", {**database.COLUMNAS_PAPERS_NUEVAS, "seleccionado": "INTEGER"})
    return conn


def nombre_archivo(titulo, propio=None):
    """'Leche A2 y digestión' -> 'leche_a2_y_digestion.db'. Si ya existe un
    archivo con ese nombre (de otro proyecto; `propio` es el del mismo
    proyecto y no cuenta), agrega _2, _3..."""
    sin_tildes = unicodedata.normalize("NFKD", titulo).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "_", sin_tildes.lower()).strip("_")[:60].strip("_") or "proyecto"
    nombre, n = f"{base}.db", 1
    while nombre != propio and os.path.exists(ruta(nombre)):
        n += 1
        nombre = f"{base}_{n}.db"
    return nombre


def guardar(proyecto, con_papers=False):
    """Guarda el estado del proyecto y, con `con_papers`, reemplaza también su
    tabla de papers (solo hace falta cuando cambian los resultados)."""
    estado = {k: v for k, v in proyecto.items() if k not in FUERA_DEL_ESTADO}
    with closing(_conectar(proyecto["archivo"])) as conn, conn:
        conn.execute("INSERT OR REPLACE INTO proyecto (clave, valor) VALUES ('estado', ?)",
                     (json.dumps(estado, ensure_ascii=False),))
        if con_papers:
            seleccion = set(proyecto["seleccion"])
            filas = []
            for paper in proyecto["papers"]:
                fila = {**paper, "paper_id": paper["id"], "seleccionado": int(paper["id"] in seleccion)}
                filas.append([fila.get(c) for c in COLUMNAS_PAPERS])
            conn.execute("DELETE FROM papers")
            conn.executemany(
                f"INSERT INTO papers ({', '.join(COLUMNAS_PAPERS)}) "
                f"VALUES ({', '.join('?' for _ in COLUMNAS_PAPERS)})", filas)


def guardar_seleccion(proyecto):
    seleccion = [(s,) for s in proyecto["seleccion"]]
    with closing(_conectar(proyecto["archivo"])) as conn, conn:
        conn.execute("UPDATE papers SET seleccionado = 0")
        conn.executemany("UPDATE papers SET seleccionado = 1 WHERE paper_id = ?", seleccion)


def cargar(archivo):
    """Lee un proyecto completo de su base. None si el archivo no es de un
    proyecto (no tiene estado guardado)."""
    with closing(_conectar(archivo)) as conn:
        fila = conn.execute("SELECT valor FROM proyecto WHERE clave = 'estado'").fetchone()
        if fila is None:
            return None
        proyecto = json.loads(fila["valor"])
        papers = []
        # rowid conserva el orden en que se guardaron: el del ranking
        for f in conn.execute("SELECT * FROM papers ORDER BY rowid"):
            paper = dict(f)
            paper["id"] = paper.pop("paper_id")
            paper["is_oa"] = bool(paper["is_oa"])
            if paper.pop("seleccionado"):
                proyecto.setdefault("seleccion", []).append(paper["id"])
            papers.append(paper)
    proyecto.setdefault("seleccion", [])
    proyecto.update(papers=papers, archivo=archivo, busqueda=None)
    return proyecto


def renombrar(proyecto):
    """Cambia el nombre del archivo para que siga al título del proyecto."""
    nuevo = nombre_archivo(proyecto["name"], propio=proyecto["archivo"])
    if nuevo != proyecto["archivo"]:
        os.rename(ruta(proyecto["archivo"]), ruta(nuevo))
        proyecto["archivo"] = nuevo


def borrar(proyecto):
    try:
        os.remove(ruta(proyecto["archivo"]))
    except FileNotFoundError:
        pass
