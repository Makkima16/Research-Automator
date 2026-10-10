"""
Esquema de la tabla para el árbol de decisiones: familia "leche", etapa
"general" (ver procesamiento/esquemas/leche/general.yaml).

Se genera en tiempo de ejecución desde ese YAML (ver esquema_dinamico.py), que
es ahora la fuente de verdad versionada en git. Para otra familia o etapa
(ej. "biochar"), no se importa este módulo: se llama directamente a
esquema_dinamico.construir_modelo(familia, etapa).

Si el equipo necesita otra columna para lácteos, se agrega en el YAML, no acá.
"""

import esquema_dinamico as _dinamico

Observacion, _ENUMS, _DEFINICION = _dinamico.construir_modelo("leche", "general")

CAMPOS_OBSERVACION = list(Observacion.model_fields)
CAMPOS_NUMERICOS = _dinamico.campos_numericos(Observacion)
CAMPOS_BOOLEANOS = _dinamico.campos_booleanos(Observacion)
CAMPOS_CATEGORICOS = _dinamico.campos_categoricos(Observacion)
