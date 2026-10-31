"""
Tablas del procesamiento en la base de datos SQLite del proyecto
(../busqueda/output/proyectos/<nombre>.db, o selema.db en la línea de comandos).

La tabla `papers` la crea y la llena la búsqueda
(../busqueda/database.py). Aquí se agregan:
- estructuras: piezas de cada paper leídas con Nemotron Parse (o
               Europe PMC): abstract, últimos párrafos de la introducción,
               conclusión y tablas (ver lectura_pdf.py).
- fichas:      resumen que Nemotron arma con esas piezas (extract_ficha.py).

Se puede abrir con DB Browser for SQLite (https://sqlitebrowser.org) para
revisar a mano.
"""

import config_proc  # noqa: F401  (primero: agrega ../busqueda a la ruta de importación)
import database as db_busqueda

SCHEMA = """
CREATE TABLE IF NOT EXISTS estructuras (
    paper_id TEXT PRIMARY KEY REFERENCES papers(paper_id),
    estado TEXT,              -- ok | no_disponible | error
    fuente TEXT,              -- europepmc | local | local+nemotron_parse | nemotron_parse
    url TEXT,
    estructura_json TEXT,     -- abstract, últimos párrafos de la intro, conclusión, tablas (nombre + atributos)
    error TEXT,
    creado_en TEXT
);

CREATE TABLE IF NOT EXISTS fichas (
    paper_id TEXT PRIMARY KEY REFERENCES papers(paper_id),
    estado TEXT,              -- ok | no_relevante | sin_abstract | error
    cobertura TEXT,           -- completa (con conclusiones/tablas del paper) | parcial (solo el abstract)
    modelo TEXT,
    texto_hash TEXT,
    ficha_json TEXT,          -- resumen, objetivo, conclusiones, hallazgos_clave, tablas
    error TEXT,
    creado_en TEXT
);
"""


def conectar(ruta):
    """Abre la base de la búsqueda (tabla papers) y le agrega las tablas del
    procesamiento."""
    conn = db_busqueda.conectar(ruta)
    conn.executescript(SCHEMA)
    return conn
