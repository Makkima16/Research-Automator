"""
Esquema de la tabla para el árbol de decisiones.

Cada paper se convierte en una o varias OBSERVACIONES: una fila por cada
comparación + variable de resultado que el paper reporte (por ejemplo,
"leche A2 vs A1 -> síntomas gastrointestinales -> mejora").

Las columnas categóricas usan listas cerradas (Enum) para que el LLM no
invente categorías nuevas y el árbol pueda agruparlas. La columna objetivo
del árbol es `efecto`.

Si el equipo necesita otra columna, se agrega aquí: la base de datos y la
tabla final se generan a partir de este archivo.
"""

from enum import Enum

from pydantic import BaseModel, Field


class TipoEstudio(str, Enum):
    ensayo_clinico = "ensayo_clinico"
    estudio_animal = "estudio_animal"
    in_vitro = "in_vitro"
    formulacion_proceso = "formulacion_proceso"
    modelado_ml = "modelado_ml"
    revision = "revision"
    otro = "otro"


class Matriz(str, Enum):
    leche_liquida = "leche_liquida"
    yogur_fermentado = "yogur_fermentado"
    queso = "queso"
    leche_en_polvo_formula = "leche_en_polvo_formula"
    proteina_aislada = "proteina_aislada"
    otro = "otro"


class TipoBetaCaseina(str, Enum):
    A2 = "A2"
    A1 = "A1"
    A1A2 = "A1A2"
    no_especificado = "no_especificado"


class EspecieLeche(str, Enum):
    vaca = "vaca"
    cabra = "cabra"
    oveja = "oveja"
    bufala = "bufala"
    humana = "humana"
    otra = "otra"
    no_especificado = "no_especificado"


class Raza(str, Enum):
    holstein = "holstein"
    jersey = "jersey"
    guernsey = "guernsey"
    pardo_suizo = "pardo_suizo"
    normando = "normando"
    ayrshire = "ayrshire"
    cebu_gyr = "cebu_gyr"          # Bos indicus: Gyr, Brahman, Sahiwal...
    cruce = "cruce"                # ej. Girolando, Holstein x Jersey
    otra = "otra"
    no_especificado = "no_especificado"


class Region(str, Enum):
    america_latina = "america_latina"
    america_norte = "america_norte"
    europa = "europa"
    oceania = "oceania"
    asia = "asia"
    africa = "africa"
    no_especificado = "no_especificado"


class SistemaAlimentacion(str, Enum):
    pastoreo = "pastoreo"
    estabulado = "estabulado"      # confinamiento con ración / concentrado
    mixto = "mixto"
    no_especificado = "no_especificado"


class TratamientoTermico(str, Enum):
    crudo = "crudo"
    pasteurizado = "pasteurizado"
    ultrapasteurizado = "ultrapasteurizado"  # ESL
    uht = "uht"
    esterilizado = "esterilizado"
    otro = "otro"
    no_especificado = "no_especificado"


class Poblacion(str, Enum):
    adultos = "adultos"
    ninos = "ninos"
    animales = "animales"
    no_aplica = "no_aplica"


class VariableResultado(str, Enum):
    digestibilidad_proteica = "digestibilidad_proteica"
    sintomas_gastrointestinales = "sintomas_gastrointestinales"
    marcadores_inflamacion = "marcadores_inflamacion"
    textura_reologia = "textura_reologia"
    sensorial_aceptacion = "sensorial_aceptacion"
    vida_util = "vida_util"
    composicion_nutricional = "composicion_nutricional"
    calidad_microbiologica = "calidad_microbiologica"
    estabilidad_proceso = "estabilidad_proceso"    # estabilidad térmica, coagulación, rendimiento quesero
    otro = "otro"


class CategoriaFactor(str, Enum):
    """Qué tipo de cosa es el factor evaluado; sirve para agrupar la evidencia."""
    beta_caseina = "beta_caseina"                # A2 vs A1 / convencional
    genetica_raza = "genetica_raza"              # razas, genotipos, cruces
    alimentacion = "alimentacion"                # pastoreo, dietas, suplementos
    estres_ambiental = "estres_ambiental"        # estrés térmico, clima, estación
    sanidad_animal = "sanidad_animal"            # mastitis, células somáticas
    tratamiento_termico = "tratamiento_termico"  # pasteurización, UHT, esterilización
    otro_proceso = "otro_proceso"                # homogeneización, filtración, almacenamiento
    fermentacion = "fermentacion"                # cultivos, probióticos, yogur
    especie = "especie"                          # cabra, oveja, búfala... vs vaca
    formulacion = "formulacion"                  # ingredientes, deslactosado, fortificación
    otro = "otro"


class Efecto(str, Enum):
    """Variable objetivo del árbol: qué le pasó a la variable de resultado."""
    mejora = "mejora"
    sin_diferencia = "sin_diferencia"
    empeora = "empeora"
    mixto = "mixto"


class Observacion(BaseModel):
    """Una comparación reportada por un paper. `factor_evaluado` es el grupo que
    se estudia y `referencia` el grupo control; las características (matriz,
    beta-caseína, raza, tratamiento...) describen al grupo EVALUADO, y `efecto`
    dice qué le pasó a la variable medida en el evaluado frente a la referencia."""
    categoria_factor: CategoriaFactor
    factor_evaluado: str = Field(description="Grupo o condición que se evalúa, en pocas palabras, ej. 'leche UHT', 'leche A2', 'pastoreo'")
    referencia: str = Field(description="Grupo control con el que se compara, ej. 'leche pasteurizada', 'leche A1', 'dieta estabulada'")
    tipo_estudio: TipoEstudio
    matriz: Matriz
    tipo_beta_caseina: TipoBetaCaseina
    especie_leche: EspecieLeche
    raza: Raza
    sistema_alimentacion: SistemaAlimentacion
    region: Region
    pais: str | None = Field(None, description="País de origen de la leche o donde se hizo el estudio")
    tratamiento_termico: TratamientoTermico
    homogeneizado: bool | None = None
    lactosa_reducida: bool | None = Field(None, description="True si la leche es deslactosada o con lactasa")
    temperatura_c: float | None = Field(None, description="Temperatura de proceso en °C, solo si el texto la da")
    tiempo_min: float | None = Field(None, description="Tiempo de proceso en minutos, solo si el texto lo da")
    ph: float | None = None
    usa_probioticos: bool | None = None
    cepas: str | None = Field(None, description="Cepas bacterianas separadas por ';'")
    proteina_pct: float | None = None
    grasa_pct: float | None = None
    lactosa_pct: float | None = None
    solidos_totales_pct: float | None = None
    celulas_somaticas_miles_ml: float | None = Field(None, description="Recuento de células somáticas en miles de células/mL")
    vida_util_dias: float | None = None
    poblacion: Poblacion
    tamano_muestra: int | None = Field(None, description="Número de sujetos o muestras")
    variable_resultado: VariableResultado
    efecto: Efecto = Field(description="Qué le pasó a la variable medida en el factor evaluado frente a la referencia")
    cita_textual: str = Field(description="Frase COPIADA LITERALMENTE del texto que respalda esta observación")


CAMPOS_OBSERVACION = list(Observacion.model_fields)
CAMPOS_NUMERICOS = [
    nombre for nombre, campo in Observacion.model_fields.items()
    if campo.annotation in (float | None, int | None)
]
CAMPOS_BOOLEANOS = [
    nombre for nombre, campo in Observacion.model_fields.items()
    if campo.annotation == (bool | None)
]
CAMPOS_CATEGORICOS = [
    nombre for nombre, campo in Observacion.model_fields.items()
    if isinstance(campo.annotation, type) and issubclass(campo.annotation, Enum)
]
