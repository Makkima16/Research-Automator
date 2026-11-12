"""
Acceso a las tablas del procesamiento (estructuras, fichas) en la base
PostgreSQL del proyecto (DATABASE_URL en ../.env).

Las tablas las crea busqueda/database.py, que es la capa de datos compartida
por la búsqueda, el frontend y este módulo. Aquí solo se expone conectar()
para que los scripts del procesamiento (extract_ficha.py) y el frontend
(servidor.py) abran la misma base con el import que ya usaban.
"""

import config_proc  # noqa: F401  (primero: agrega ../busqueda a la ruta de importación)
import database as db_busqueda


def conectar():
    """Abre la base compartida (papel de cada tabla en db_busqueda)."""
    return db_busqueda.conectar()
