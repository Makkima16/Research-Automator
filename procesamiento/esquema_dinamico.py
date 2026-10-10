"""
Construye en tiempo de ejecución el modelo Pydantic de una "observación"
(una comparación + variable medida extraída de un paper) a partir de un
archivo YAML versionado en git: procesamiento/esquemas/<familia>/<etapa>.yaml.

Es el reemplazo genérico de lo que antes se escribía a mano en esquema.py
(una sola familia: leche). Cada archivo YAML define sus propios vocabularios
cerrados (enums) y campos; dos familias distintas (ej. "leche" y "biochar")
no comparten vocabulario, aunque usen los mismos nombres de campo.

Formato de un archivo de esquema:

    familia: biochar
    etapa: pirolisis
    version: 1
    descripcion: "..."
    enums:
      nombre_del_enum: [valor_1, valor_2, otro]
    campos:
      nombre_del_campo:
        tipo: texto | numero | entero | booleano | enum
        enum: nombre_del_enum       # solo si tipo == enum
        obligatorio: true | false   # false = puede faltar (queda en null)
        descripcion: "..."

`version` sirve para que un humano note que el esquema cambió; `esquemas.json`
no se audita automáticamente todavía (eso es de una fase posterior, cuando la
cola de revisión experta pueda promover campos nuevos).
"""

import os

import yaml
from enum import Enum
from pydantic import Field, create_model

ESQUEMAS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "esquemas")

TIPOS_PYTHON = {
    "texto": str,
    "numero": float,
    "entero": int,
    "booleano": bool,
}


def ruta_esquema(familia, etapa):
    return os.path.join(ESQUEMAS_DIR, familia, f"{etapa}.yaml")


def familias_disponibles():
    if not os.path.isdir(ESQUEMAS_DIR):
        return []
    return sorted(d for d in os.listdir(ESQUEMAS_DIR) if os.path.isdir(os.path.join(ESQUEMAS_DIR, d)))


def etapas_disponibles(familia):
    carpeta = os.path.join(ESQUEMAS_DIR, familia)
    if not os.path.isdir(carpeta):
        return []
    return sorted(f[:-5] for f in os.listdir(carpeta) if f.endswith(".yaml"))


def cargar_definicion(familia, etapa):
    ruta = ruta_esquema(familia, etapa)
    if not os.path.exists(ruta):
        raise FileNotFoundError(
            f"No existe el esquema {familia}/{etapa} ({ruta}). "
            f"Familias disponibles: {familias_disponibles()}")
    with open(ruta, encoding="utf-8") as f:
        definicion = yaml.safe_load(f)
    if definicion.get("familia") != familia or definicion.get("etapa") != etapa:
        raise ValueError(
            f"{ruta}: dice familia={definicion.get('familia')!r} etapa={definicion.get('etapa')!r}, "
            f"pero se cargó como {familia}/{etapa}. Revisa la cabecera del archivo.")
    return definicion


def _construir_enum(nombre_modelo, nombre_enum, valores):
    """Enum(str) con cada valor igual a su propio nombre, como los de esquema.py."""
    return Enum(f"{nombre_modelo}_{nombre_enum}", {v: v for v in valores}, type=str)


def construir_modelo(familia, etapa):
    """Devuelve (ModeloObservacion, {nombre_enum: ClaseEnum}, definicion_cruda)."""
    definicion = cargar_definicion(familia, etapa)
    nombre_modelo = f"Observacion_{familia}_{etapa}"

    enums = {nombre: _construir_enum(nombre_modelo, nombre, valores)
             for nombre, valores in (definicion.get("enums") or {}).items()}

    campos_pydantic = {}
    for nombre, spec in definicion["campos"].items():
        tipo = spec["tipo"]
        if tipo == "enum":
            if spec.get("enum") not in enums:
                raise ValueError(f"{familia}/{etapa}: el campo {nombre!r} usa el enum {spec.get('enum')!r}, "
                                 "que no está declarado en 'enums'.")
            anotacion = enums[spec["enum"]]
        elif tipo in TIPOS_PYTHON:
            anotacion = TIPOS_PYTHON[tipo]
        else:
            raise ValueError(f"{familia}/{etapa}: el campo {nombre!r} tiene tipo {tipo!r} desconocido "
                             f"(usa uno de {list(TIPOS_PYTHON) + ['enum']}).")
        obligatorio = bool(spec.get("obligatorio", False))
        if not obligatorio:
            anotacion = anotacion | None
        valor_por_defecto = ... if obligatorio else spec.get("default", None)
        campos_pydantic[nombre] = (anotacion, Field(valor_por_defecto, description=spec.get("descripcion")))

    modelo = create_model(nombre_modelo, **campos_pydantic)
    return modelo, enums, definicion


def campos_numericos(modelo):
    return [n for n, c in modelo.model_fields.items() if c.annotation in (float | None, int | None)]


def campos_booleanos(modelo):
    return [n for n, c in modelo.model_fields.items() if c.annotation == (bool | None)]


def campos_categoricos(modelo):
    return [n for n, c in modelo.model_fields.items()
            if isinstance(c.annotation, type) and issubclass(c.annotation, Enum)]
