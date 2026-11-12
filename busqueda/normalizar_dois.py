"""
Migración única: lleva los `paper_id` y DOI guardados al formato canónico de
doi.py ("https://doi.org/" + DOI en minúsculas) y fusiona los papers que
quedaron duplicados por diferencias de mayúsculas.

Por cada paper con el formato viejo:
- Si el ID canónico no existe, el paper se copia con ese ID y sus filas de
  `papers_proyectos`, `estructuras` y `fichas` pasan a apuntar a él.
- Si ya existe (duplicado), se conserva el canónico: se completan sus campos
  vacíos con los del viejo, en cada proyecto queda el mejor puesto del
  ranking y la selección de cualquiera de los dos, y la estructura y la ficha
  del viejo solo se mueven si el canónico no tiene.
Después se borra el paper viejo. Todo va en una sola transacción.

    python normalizar_dois.py            # simula: muestra qué cambiaría
    python normalizar_dois.py --aplicar  # escribe en la base

Con la API levantada, reiniciarla después de aplicar (guarda los proyectos
en memoria).
"""

import argparse

import database
import doi as doi_util


def pendientes(conn):
    """[(id viejo, id canónico)] de los papers con DOI fuera de formato."""
    filas = conn.execute("SELECT paper_id, doi FROM papers WHERE doi IS NOT NULL ORDER BY paper_id").fetchall()
    return [(f["paper_id"], doi_util.normalizar(f["doi"])) for f in filas
            if f["paper_id"] != doi_util.normalizar(f["doi"]) or f["doi"] != doi_util.normalizar(f["doi"])]


def _existe(conn, tabla, paper_id):
    return conn.execute(f"SELECT 1 FROM {tabla} WHERE paper_id = %s", (paper_id,)).fetchone() is not None


def migrar_uno(conn, viejo, nuevo):
    columnas = [c for c in database.COLUMNAS_PAPERS if c != "paper_id"]
    if viejo == nuevo:                   # el ID ya está bien: solo falta el campo doi
        conn.execute("UPDATE papers SET doi = %s WHERE paper_id = %s", (nuevo, viejo))
        return "doi corregido"
    if not _existe(conn, "papers", nuevo):
        lista = ", ".join(columnas)
        conn.execute(f"INSERT INTO papers (paper_id, {lista}) SELECT %s, {lista} FROM papers WHERE paper_id = %s",
                     (nuevo, viejo))
        accion = "renombrado"
    else:
        # Completar los campos vacíos del canónico con los del duplicado
        relleno = ", ".join(f"{c} = COALESCE(c.{c}, v.{c})" for c in columnas)
        conn.execute(f"UPDATE papers c SET {relleno} FROM papers v WHERE c.paper_id = %s AND v.paper_id = %s",
                     (nuevo, viejo))
        accion = "fusionado"
    conn.execute("UPDATE papers SET doi = %s WHERE paper_id = %s", (nuevo, nuevo))

    # Proyectos: mejor puesto y selección de cualquiera de los dos
    conn.execute("""
        UPDATE papers_proyectos c SET orden = LEAST(c.orden, v.orden), score = GREATEST(c.score, v.score),
               seleccionado = GREATEST(c.seleccionado, v.seleccionado)
        FROM papers_proyectos v
        WHERE c.paper_id = %s AND v.paper_id = %s AND c.archivo = v.archivo""", (nuevo, viejo))
    conn.execute("""
        UPDATE papers_proyectos v SET paper_id = %s
        WHERE v.paper_id = %s AND NOT EXISTS (
            SELECT 1 FROM papers_proyectos c WHERE c.paper_id = %s AND c.archivo = v.archivo)""",
                 (nuevo, viejo, nuevo))
    for tabla in ("estructuras", "fichas"):
        if not _existe(conn, tabla, nuevo):
            conn.execute(f"UPDATE {tabla} SET paper_id = %s WHERE paper_id = %s", (nuevo, viejo))
    # Lo que quedó del viejo (filas repetidas) se va en cascada
    conn.execute("DELETE FROM papers WHERE paper_id = %s", (viejo,))
    return accion


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--aplicar", action="store_true", help="escribir en la base (sin esto, solo simula)")
    args = parser.parse_args()
    conn = database.conectar()
    try:
        lista = pendientes(conn)
        if not lista:
            print("Todos los DOI ya están en formato canónico.")
            return
        antes = conn.execute("SELECT COUNT(*) AS n FROM papers").fetchone()["n"]
        existentes = {f["paper_id"] for f in conn.execute("SELECT paper_id FROM papers").fetchall()}
        destinos = set()
        print(f"{len(lista)} papers con DOI fuera de formato:")
        for viejo, nuevo in lista:
            duplicado = (nuevo in existentes and nuevo != viejo) or nuevo in destinos
            destinos.add(nuevo)
            print(f"  {'fusiona ' if duplicado else 'renombra'} {viejo}\n           -> {nuevo}")
        if not args.aplicar:
            print("\nSimulación: no se escribió nada. Ejecutar con --aplicar para migrar.")
            return
        conteo = {}
        with conn.transaction():
            for viejo, nuevo in lista:
                accion = migrar_uno(conn, viejo, nuevo)
                conteo[accion] = conteo.get(accion, 0) + 1
        despues = conn.execute("SELECT COUNT(*) AS n FROM papers").fetchone()["n"]
        print(f"\nAplicado: {conteo}. Papers en la base: {antes} -> {despues}.")
        if pendientes(conn):
            print("AVISO: quedaron DOI fuera de formato; revisar.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
