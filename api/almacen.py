"""
Guarda cada proyecto de la interfaz web (servidor.py) como filas de la base
PostgreSQL compartida (DATABASE_URL en ../.env; esquema en
busqueda/database.py):

- proyectos:        una fila por proyecto; `archivo` es su slug (se deriva del
                    título y cambia al renombrarlo) y `estado` lleva el resto
                    del proyecto (título, prompt, cadenas, parámetros,
                    etapa...) en JSONB.
- papers_proyectos: los papers de cada proyecto, con el orden del ranking, su
                    score y si quedó seleccionado. La tabla `papers` es
                    compartida: un mismo paper es una sola fila aunque varios
                    proyectos lo incluyan.

Para revisar la base a mano sirve cualquier cliente de Postgres (psql, DBeaver...).
"""

import re
import unicodedata
from contextlib import closing

from psycopg.types.json import Jsonb

import database

# Campos del proyecto que no van al JSONB de `proyectos`: los papers y la
# selección viven en papers_proyectos; los otros solo existen en memoria
FUERA_DEL_ESTADO = ("papers", "seleccion", "archivo", "busqueda")


def listar():
    """Slugs de todos los proyectos guardados (el más reciente primero)."""
    with closing(database.conectar()) as conn:
        return [f["archivo"] for f in
                conn.execute("SELECT archivo FROM proyectos ORDER BY actualizado_en DESC")]


def nombre_archivo(titulo, propio=None):
    """'Microbioma y autismo' -> 'microbioma_y_autismo'. Si ya existe un
    proyecto con ese slug (`propio` es el del mismo proyecto y no cuenta),
    agrega _2, _3..."""
    sin_tildes = unicodedata.normalize("NFKD", titulo).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "_", sin_tildes.lower()).strip("_")[:60].strip("_") or "proyecto"
    with closing(database.conectar()) as conn:
        existentes = {f["archivo"] for f in conn.execute("SELECT archivo FROM proyectos")}
    nombre, n = base, 1
    while nombre != propio and nombre in existentes:
        n += 1
        nombre = f"{base}_{n}"
    return nombre


def guardar(proyecto, con_papers=False):
    """Guarda el estado del proyecto y, con `con_papers`, reemplaza también
    sus papers (solo hace falta cuando cambian los resultados)."""
    estado = {k: v for k, v in proyecto.items() if k not in FUERA_DEL_ESTADO}
    with closing(database.conectar()) as conn:
        with conn.transaction():
            conn.execute(
                "INSERT INTO proyectos (archivo, nombre, estado) VALUES (%s, %s, %s) "
                "ON CONFLICT (archivo) DO UPDATE SET "
                "nombre = excluded.nombre, estado = excluded.estado, actualizado_en = now()",
                (proyecto["archivo"], proyecto["name"], Jsonb(estado)))
            if con_papers:
                database.guardar_papers(conn, proyecto["papers"], proyecto=proyecto["archivo"],
                                        seleccionados=proyecto.get("seleccion") or [])


def guardar_seleccion(proyecto):
    seleccion = [(proyecto["archivo"], s) for s in proyecto["seleccion"]]
    with closing(database.conectar()) as conn:
        with conn.transaction():
            conn.execute("UPDATE papers_proyectos SET seleccionado = 0 WHERE archivo = %s",
                         (proyecto["archivo"],))
            conn.executemany(
                "UPDATE papers_proyectos SET seleccionado = 1 "
                "WHERE archivo = %s AND paper_id = %s", seleccion)


def cargar(archivo):
    """Lee un proyecto completo de la base: su estado y sus papers en orden
    de ranking. None si no hay un proyecto con ese slug."""
    with closing(database.conectar()) as conn:
        fila = conn.execute("SELECT estado FROM proyectos WHERE archivo = %s", (archivo,)).fetchone()
        if fila is None or fila["estado"] is None:
            return None
        proyecto = fila["estado"]  # JSONB: llega ya como diccionario
        papers = []
        filas = conn.execute(
            "SELECT p.*, pp.seleccionado "
            "FROM papers p JOIN papers_proyectos pp ON pp.paper_id = p.paper_id "
            "WHERE pp.archivo = %s ORDER BY pp.orden", (archivo,))
        for f in filas:
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
    """Cambia el slug para que siga al título del proyecto (la relación con
    sus papers lo acompaña: ON UPDATE CASCADE)."""
    nuevo = nombre_archivo(proyecto["name"], propio=proyecto["archivo"])
    if nuevo != proyecto["archivo"]:
        with closing(database.conectar()) as conn:
            with conn.transaction():
                conn.execute("UPDATE proyectos SET archivo = %s WHERE archivo = %s",
                             (nuevo, proyecto["archivo"]))
        proyecto["archivo"] = nuevo


def borrar(proyecto):
    """Borra el proyecto y su relación con los papers (estos últimos quedan:
    la tabla `papers` es un pool compartido entre proyectos)."""
    with closing(database.conectar()) as conn:
        with conn.transaction():
            conn.execute("DELETE FROM proyectos WHERE archivo = %s", (proyecto["archivo"],))
