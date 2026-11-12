"""
Prueba mínima de la base PostgreSQL (variables NEON_* en .env): conecta, asegura
el esquema, escribe un paper de prueba con su estructura y su ficha (JSONB),
las consulta con operadores de documento (->>, @>) y lo borra todo. No consume
presupuesto de ninguna API de papers ni de NVIDIA.

    python probar_postgres.py            # desde la raíz del proyecto
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "busqueda"))

import database  # noqa: E402  (busqueda/database.py)
from psycopg.types.json import Jsonb  # noqa: E402

PAPER = "prueba-conexion-000"


def main():
    conn = database.conectar()
    print("Conexión y esquema: OK")
    try:
        with conn.transaction():
            conn.execute(
                "INSERT INTO papers (paper_id, title, year, doi, is_oa, score) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (paper_id) DO UPDATE SET title = excluded.title",
                (PAPER, "Paper de prueba", 2026, "10.0000/prueba", 1, 1.5))
            conn.execute(
                "INSERT INTO estructuras (paper_id, estado, fuente, estructura_json, creado_en) "
                "VALUES (%s, 'ok', 'local', %s, 'ahora') "
                "ON CONFLICT (paper_id) DO UPDATE SET estructura_json = excluded.estructura_json",
                (PAPER, Jsonb({"abstract": "Texto de prueba del abstract.",
                               "conclusion": "Conclusión de prueba.",
                               "tablas": [{"nombre": "Tabla 1", "atributos": ["tratamiento", "rendimiento"]}]})))
            conn.execute(
                "INSERT INTO fichas (paper_id, estado, cobertura, modelo, texto_hash, ficha_json, creado_en) "
                "VALUES (%s, 'ok', 'completa', 'prueba', 'x', %s, 'ahora') "
                "ON CONFLICT (paper_id) DO UPDATE SET ficha_json = excluded.ficha_json",
                (PAPER, Jsonb({"resumen": "Resumen de prueba.",
                               "hallazgos_clave": ["hallazgo 1", "hallazgo 2"]})))
        print("Escritura de papers + estructuras + fichas (JSONB): OK")

        titulo = conn.execute("SELECT title FROM papers WHERE paper_id = %s", (PAPER,)).fetchone()["title"]
        dentro = conn.execute(
            "SELECT estructura_json ->> 'conclusion' AS conclusion "
            "FROM estructuras WHERE paper_id = %s", (PAPER,)).fetchone()["conclusion"]
        por_contenido = conn.execute(
            "SELECT COUNT(*) AS n FROM fichas WHERE ficha_json @> %s",
            (Jsonb({"resumen": "Resumen de prueba."}),)).fetchone()["n"]
        print(f"Lectura relacional (title): {titulo!r}")
        print(f"Consulta dentro del JSONB (->> conclusion): {dentro!r}")
        print(f"Consulta por contenido del JSONB (@> resumen): {por_contenido} ficha(s)")
        if not (titulo and dentro and por_contenido):
            print("ERROR: alguna consulta devolvió un valor inesperado.")
            return 1

        conn.commit()  # cierra la transacción implícita abierta por las lecturas
        with conn.transaction():
            conn.execute("DELETE FROM papers WHERE paper_id = %s", (PAPER,))
        conn.commit()
        quedan = conn.execute(
            "SELECT COUNT(*) AS n FROM estructuras WHERE paper_id = %s", (PAPER,)).fetchone()["n"]
        print(f"Borrado en cascada (estructura del paper de prueba restante): {quedan}")
        if quedan:
            print("ERROR: el borrado en cascada no limpió las tablas.")
            return 1
        print("Prueba completa: OK. La base está lista para usar el proyecto.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
