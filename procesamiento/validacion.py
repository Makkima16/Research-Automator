"""
Control de calidad de cada observación extraída por el LLM.

Una observación es VÁLIDA (entra a la tabla del árbol) solo si:
1. Su `cita_textual` existe de verdad en el abstract o en el texto completo
   del paper (evita datos inventados).
2. Tiene la variable de resultado y el efecto, que son el objetivo del árbol.

Los valores numéricos fuera de rango físico no invalidan la fila: se borran
(quedan como vacíos) y se anota el problema en la columna `problemas`.
"""

import re
import unicodedata

# Fracción mínima de palabras de la cita que deben aparecer, en orden, en el texto
UMBRAL_COBERTURA_CITA = 0.85
MIN_PALABRAS_CITA = 5

RANGOS_VALIDOS = {
    "temperatura_c": (-40, 200),
    "tiempo_min": (0, 60 * 24 * 60),  # hasta 60 días
    "ph": (0, 14),
    "proteina_pct": (0, 100),
    "grasa_pct": (0, 100),
    "lactosa_pct": (0, 100),
    "solidos_totales_pct": (0, 100),
    "celulas_somaticas_miles_ml": (0, 10_000),
    "vida_util_dias": (0, 3650),
    "tamano_muestra": (1, 10_000_000),
}


def normalizar(texto):
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c)).lower()
    return re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", texto)


def cobertura_cita(cita, texto):
    """Fracción de palabras de la cita que aparecen en el texto en el mismo
    orden. Tolera pequeñas diferencias (puntuación, una palabra cambiada)
    pero no citas parafraseadas o inventadas."""
    palabras_cita = normalizar(cita)
    palabras_texto = normalizar(texto)
    if not palabras_cita:
        return 0.0
    i = 0
    encontradas = 0
    for palabra in palabras_cita:
        try:
            i = palabras_texto.index(palabra, i) + 1
            encontradas += 1
        except ValueError:
            continue
    return encontradas / len(palabras_cita)


def cita_en_texto(cita, texto):
    """¿La cita está en este texto? (mismo criterio que la verificación)."""
    return len(normalizar(cita)) >= MIN_PALABRAS_CITA and cobertura_cita(cita, texto) >= UMBRAL_COBERTURA_CITA


def validar_observacion(obs, texto_fuente):
    """Recibe la observación como dict y devuelve (obs_limpia, valida, problemas)."""
    obs = dict(obs)
    problemas = []

    # La comparación siempre se escribe igual: "evaluado vs referencia"
    factor = (obs.get("factor_evaluado") or "").strip()
    referencia = (obs.get("referencia") or "").strip()
    obs["comparacion"] = f"{factor} vs {referencia}" if referencia else factor
    if not factor:
        problemas.append("falta factor_evaluado")

    for campo, (minimo, maximo) in RANGOS_VALIDOS.items():
        valor = obs.get(campo)
        if valor is not None and not (minimo <= valor <= maximo):
            problemas.append(f"{campo}={valor} fuera de rango [{minimo}, {maximo}]")
            obs[campo] = None

    cita = obs.get("cita_textual") or ""
    cobertura = cobertura_cita(cita, texto_fuente)
    cita_verificada = cita_en_texto(cita, texto_fuente)
    if not cita_verificada:
        problemas.append(f"cita no encontrada en el texto (cobertura {cobertura:.0%})")

    if not obs.get("variable_resultado") or not obs.get("efecto"):
        problemas.append("falta variable_resultado o efecto")

    obs["cita_verificada"] = cita_verificada
    valida = cita_verificada and not any(p.startswith("falta") for p in problemas)
    return obs, valida, problemas
