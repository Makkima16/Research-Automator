"""
Genera cadenas de búsqueda a partir de un tema escrito en lenguaje natural
(lo usa la interfaz web, ver servidor.py). Las cadenas salen en la misma
sintaxis AND / OR / NOT de config.PAPER_QUERIES (ver fetch_papers.py).

Usa Nemotron en build.nvidia.com (NVIDIA_API_KEY en ../.env). Si no responde,
arma cadenas básicas con las palabras del tema y devuelve un aviso, para que
la interfaz siga funcionando y el usuario las edite a mano.

Términos obligatorios: el usuario puede fijar conceptos que deben estar en
TODAS las cadenas (cada uno es un grupo AND propio). El modelo los traduce y
les agrega sinónimos, pero quien garantiza que estén es el código
(asegurar_obligatorios): si una cadena llega sin el grupo, se le antepone.
"""

import json
import re
import unicodedata

import requests
from pydantic import BaseModel, Field, ValidationError

import config
import llm_nvidia

MAX_CADENAS = 12

# Por idioma: (en qué idioma van los términos, cómo armar los grupos).
# Las bases académicas indexan sobre todo en inglés: la misma cadena traducida
# al español encuentra del orden de 50 veces menos papers, y cada grupo AND de
# frases exactas la reduce más. Por eso en español se piden cadenas más amplias.
IDIOMAS = {
    "en": ("inglés",
           "Entre 2 y 3 grupos AND por cadena, con 2 a 4 alternativas por grupo."),
    "ambos": ("inglés y español: en cada grupo pon los términos en inglés y, como alternativas "
              "con OR, sus equivalentes en español (con tildes)",
              "Entre 2 y 3 grupos AND por cadena, con 2 a 3 términos en inglés por grupo más sus "
              "equivalentes en español."),
    "es": ("español (con sus tildes)",
           "Hay muy pocos papers indexados en español, así que las cadenas deben ser amplias: "
           "como máximo 2 grupos AND por cadena, y al menos un tercio de las cadenas con un solo "
           "grupo (solo alternativas unidas con OR). De 3 a 5 alternativas por grupo. Prefiere "
           "términos cortos y de uso común (1 o 2 palabras) a frases largas o muy técnicas, e "
           "incluye variantes regionales del mismo concepto. En las cadenas de un solo grupo usa "
           "solo frases propias del tema, nunca una palabra genérica suelta (como robots o "
           "leche) ni una que se escriba igual en inglés. No uses NOT."),
}

# Palabras que no sirven como término de búsqueda en las cadenas básicas
_VACIAS = set("""de del la las el los un una unos unas en con por para sobre entre y o que como
su sus al lo se es son más menos muy the of in on and or for with to from by a an at into
efecto efectos estudio estudios últimos ultimos años anos effects effect study studies""".split())


# Formato para Nemotron: el modelo solo entrega los términos de cada grupo y el código arma la
# sintaxis (comillas, OR, AND, NOT). Pedirle la cadena escrita le fallaba: devolvía palabras
# sueltas, sin operadores o con un único término por grupo.
INSTRUCCIONES_GRUPOS = """Eres un bibliotecario experto en búsquedas bibliográficas. A partir del tema del \
usuario diseña {n} estrategias de búsqueda distintas y complementarias (cada una cubre un ángulo diferente \
del tema) para bases académicas (OpenAlex, Semantic Scholar, Scopus). El tema puede venir en cualquier idioma: \
tradúcelo al idioma pedido para los términos.

Cada estrategia es una lista de GRUPOS de conceptos. El paper debe contener al menos un término de CADA grupo. \
Dentro de un grupo van las alternativas del mismo concepto: sinónimos, variantes, abreviaturas y términos relacionados.
- {estructura}
- Las alternativas de un grupo son distintas entre sí y se escriben como las usaría un autor en el título o el \
resumen, SIN comillas y SIN operadores (el sistema los agrega).
- Prefiere términos de 1 a 3 palabras. No pases de 12 alternativas en total por estrategia; las más \
importantes primero.
- Cada estrategia debe aportar algo distinto: no repitas grupos enteros de otra estrategia.
- Un dato de contexto (país, variedad, población, año) no es un grupo propio: ponlo solo en una o dos estrategias.
- Los términos en español se escriben SIEMPRE con sus tildes y la ñ (robótica, automatización, niños, \
digestión). Sin tildes la búsqueda no encuentra los papers.
- Sin filtros de fecha ni de campo: no uses años como términos.
- "excluir": null, salvo que el usuario pida excluir algo de forma explícita; entonces un único término.

Idioma de los términos: {idioma}.
{obligatorios}
Responde SOLO con un objeto JSON: {{"estrategias": [{{"grupos": [["alternativa", "alternativa", "..."], \
["..."]], "excluir": null, "intencion": "qué busca esta estrategia", "alcance": "enfoque de esta estrategia"}}], \
"intencion_consolidada": "resumen de 2 a 4 frases de la intención de búsqueda (el tema original más el \
contexto o las respuestas añadidas)", "obligatorios": [{{"termino": "...", "alternativas": ["...", "..."]}}]}}."""

BLOQUE_OBLIGATORIOS = """
TÉRMINOS OBLIGATORIOS (los fijó el usuario; cada uno debe aparecer en TODAS las estrategias):
{lista}
- Cada estrategia incluye, para CADA término obligatorio, un grupo propio con ese concepto: el término \
traducido al idioma pedido más 2 a 4 sinónimos o variantes con que lo escribiría un autor. Si el usuario \
dio variantes separadas por coma, inclúyelas (traducidas).
- Los demás grupos de cada estrategia cubren los otros conceptos del tema, como siempre.
- Devuelve también "obligatorios": un elemento por término obligatorio, en el mismo orden, con "termino" \
tal como lo escribió el usuario y "alternativas": las que usaste en su grupo.
"""


class Estrategia(BaseModel):
    grupos: list[list[str]]
    excluir: str | None = None
    intencion: str = ""
    alcance: str = ""


class Obligatorio(BaseModel):
    termino: str
    alternativas: list[str] = Field(default_factory=list)


class Estrategias(BaseModel):
    estrategias: list[Estrategia]
    intencion_consolidada: str = ""
    obligatorios: list[Obligatorio] = Field(default_factory=list)


MAX_OBLIGATORIOS = 5
MAX_ALTERNATIVAS_OBLIGATORIO = 6


def limpiar_terminos_clave(valores):
    """Términos obligatorios tal como los escribió el usuario: sin vacíos ni
    repetidos, como mucho MAX_OBLIGATORIOS de 120 caracteres."""
    limpios, vistos = [], set()
    for valor in valores or []:
        texto = " ".join(str(valor).replace('"', "").split())[:120]
        if texto and texto.casefold() not in vistos:
            vistos.add(texto.casefold())
            limpios.append(texto)
    return limpios[:MAX_OBLIGATORIOS]


def _variantes_usuario(termino):
    """Un chip puede traer variantes separadas por coma: "mujeres, estudiantes mujeres"."""
    return [v.strip() for v in termino.split(",") if v.strip()]


def _clave_termino(texto):
    return _sin_tildes(" ".join(str(texto).replace('"', "").split()).casefold())


def conceptos_obligatorios(terminos, del_modelo=None, idioma="en"):
    """[{"termino", "alternativas"}] de cada término obligatorio. Las
    alternativas salen del modelo (traducidas y con sinónimos); las variantes
    que escribió el usuario se agregan si la búsqueda no es solo en inglés, o
    si el modelo no dio ninguna (así el término nunca queda sin grupo)."""
    por_termino = {_clave_termino(o.termino): o.alternativas for o in (del_modelo or [])}
    modelo_en_orden = [o.alternativas for o in (del_modelo or [])]
    conceptos = []
    for i, termino in enumerate(terminos):
        alternativas = por_termino.get(_clave_termino(termino))
        if alternativas is None and i < len(modelo_en_orden):
            alternativas = modelo_en_orden[i]
        alternativas = [a for a in (alternativas or []) if str(a).strip()]
        if idioma != "en" or not alternativas:
            alternativas = _variantes_usuario(termino) + alternativas
        unicas = list(dict.fromkeys(t for t in (_termino(a) for a in alternativas) if t))
        conceptos.append({"termino": termino, "alternativas": unicas[:MAX_ALTERNATIVAS_OBLIGATORIO]})
    return [c for c in conceptos if c["alternativas"]]


def _contiene(alternativa_grupo, alternativa_concepto):
    """True si la alternativa del grupo es el concepto o lo contiene como
    palabra(s) completa(s): "women in engineering" contiene "women"."""
    g, c = _clave_termino(alternativa_grupo), _clave_termino(alternativa_concepto)
    return g == c or re.search(rf"(?<!\w){re.escape(c)}(?!\w)", g) is not None


def faltantes(cadena, conceptos):
    """Términos obligatorios que no tienen grupo en la cadena."""
    grupos = [re.split(r"\s+OR\s+", g) for g in re.split(r"\s+AND\s+", cadena)
              if not re.match(r"(?i)^NOT\s", g.strip())]
    return [c["termino"] for c in conceptos
            if not any(_contiene(alt, ca) for grupo in grupos for alt in grupo for ca in c["alternativas"])]


def completar_alternativas(cadenas, conceptos, tope=12):
    """Los conceptos con todas las alternativas que quedaron en su grupo dentro
    de las cadenas. El modelo a veces declara menos alternativas de las que usa
    (en «Ambos» declaró solo «mujeres» y escribió «women OR female» en el grupo):
    el rescate y el ranking necesitan la lista completa."""
    completos = []
    for c in conceptos:
        alternativas = list(c["alternativas"])
        for cadena in cadenas:
            for grupo in re.split(r"\s+AND\s+", cadena):
                if re.match(r"(?i)^NOT\s", grupo.strip()):
                    continue
                terminos = [t.strip() for t in re.split(r"\s+OR\s+", grupo) if t.strip()]
                if any(_contiene(t, ca) for t in terminos for ca in c["alternativas"]):
                    alternativas += terminos
        claves, unicas = set(), []
        for a in alternativas:
            if _clave_termino(a) not in claves:
                claves.add(_clave_termino(a))
                unicas.append(a)
        completos.append({"termino": c["termino"], "alternativas": unicas[:tope]})
    return completos


def asegurar_obligatorios(cadena, conceptos):
    """La cadena con un grupo AND por cada término obligatorio que le falte,
    antepuesto (el recorte por límites de motor descarta grupos desde el final,
    así que los obligatorios se conservan)."""
    nuevos = [" OR ".join(c["alternativas"]) for c in conceptos if c["termino"] in faltantes(cadena, conceptos)]
    return " AND ".join(nuevos + [cadena]) if nuevos else cadena


def _termino(texto):
    """Un término listo para la cadena: entre comillas si tiene más de una palabra."""
    texto = " ".join(str(texto).replace('"', "").replace("(", "").replace(")", "").split())
    if re.fullmatch(r"\d{4}", texto):      # un año suelto no es un concepto: los filtros de fecha van aparte
        return ""
    return f'"{texto}"' if " " in texto else texto


def _armar_cadena(estrategia):
    grupos = []
    for grupo in estrategia.grupos:
        alternativas = list(dict.fromkeys(t for t in (_termino(a) for a in grupo if str(a).strip()) if t))
        if alternativas:
            grupos.append(" OR ".join(alternativas))
    if estrategia.excluir and estrategia.excluir.strip():
        grupos.append("NOT " + _termino(estrategia.excluir))
    return " AND ".join(grupos)


def _normalizar(cadena, idioma=None):
    """Deja la cadena en la sintaxis de fetch_papers.py: sin paréntesis, sin alternativas ni
    grupos repetidos y con NOT solo como último grupo y con un único término. Devuelve ''
    si no queda una cadena útil (sin grupos positivos o, fuera del español, con uno solo)."""
    cadena = " ".join(cadena.replace("(", "").replace(")", "").split())
    positivos, negativos, vistos = [], [], set()
    for grupo in re.split(r"\s+AND\s+", cadena):
        grupo = grupo.strip()
        if re.match(r"(?i)^NOT\s", grupo):
            termino = grupo[4:].strip()
            if termino and not re.search(r"\s+OR\s+", termino) and not negativos:
                negativos.append(f"NOT {termino}")
            continue
        alternativas, claves = [], set()
        for alt in re.split(r"\s+OR\s+", grupo):
            alt = alt.strip()
            if alt and alt.casefold() not in claves:
                claves.add(alt.casefold())
                alternativas.append(alt)
        clave_grupo = frozenset(claves)
        if alternativas and clave_grupo not in vistos:
            vistos.add(clave_grupo)
            positivos.append(" OR ".join(alternativas))
    if not positivos or (idioma != "es" and len(positivos) < 2):
        return ""
    return " AND ".join(positivos + negativos)


def _sin_tildes(palabra):
    return "".join(c for c in unicodedata.normalize("NFD", palabra) if unicodedata.category(c) != "Mn").replace("ñ", "n")


INSTRUCCIONES_TILDES = """Eres un corrector ortográfico. Recibes cadenas de búsqueda bibliográfica con términos en español \
(a veces mezclados con inglés) a las que les faltan las tildes y la ñ. Devuelve las mismas cadenas añadiendo \
SOLO las tildes y la ñ que falten en las palabras en español (robotica -> robótica, automatizacion -> \
automatización, ninos -> niños). No cambies ninguna otra letra, ni los operadores (AND, OR, NOT), ni las \
comillas, ni el orden. Las palabras en inglés no se tocan (digestion, information y similares se quedan igual \
cuando son inglés). Responde SOLO con un JSON {"cadenas": ["...", "..."]} con la misma cantidad de cadenas."""


def _restaurar_tildes(cadenas):
    """{cadena original: cadena con tildes}. Nemotron a veces escribe el español sin tildes ni ñ y
    así la búsqueda pierde papers. Una cadena solo se acepta si, quitando las tildes, queda igual
    que la original: el corrector no puede cambiar nada más. Si falla, no se toca nada."""
    try:
        texto = llm_nvidia.chat_json(INSTRUCCIONES_TILDES, json.dumps({"cadenas": cadenas}, ensure_ascii=False),
                                     timeout=90)
        nuevas = json.loads(texto)["cadenas"]
    except (ValueError, KeyError, TypeError, requests.RequestException):
        return {}
    if not isinstance(nuevas, list) or len(nuevas) != len(cadenas):
        return {}
    return {a: b for a, b in zip(cadenas, nuevas) if isinstance(b, str) and _sin_tildes(a) == _sin_tildes(b)}


def _limpiar(cadenas, n, idioma=None):
    limpias = []
    for c in cadenas:
        if not isinstance(c, str):
            continue
        c = _normalizar(c, idioma)
        if c and c not in limpias:
            limpias.append(c)
    return limpias[:n]


def _con_nvidia(tema, n, idioma, terminos=()):
    """Nemotron en build.nvidia.com (formato de grupos: ver INSTRUCCIONES_GRUPOS)."""
    en_idioma, estructura = IDIOMAS[idioma]
    bloque = BLOQUE_OBLIGATORIOS.format(lista="\n".join(f"{i}. {t}" for i, t in enumerate(terminos, 1))) \
        if terminos else ""
    contenido = llm_nvidia.chat_json(
        INSTRUCCIONES_GRUPOS.format(n=n, idioma=en_idioma, estructura=estructura, obligatorios=bloque),
        f"Tema: {tema}", timeout=120)
    try:
        res = Estrategias.model_validate_json(contenido)
    except (ValidationError, ValueError) as exc:
        raise ValueError("la respuesta de NVIDIA no tiene la forma esperada") from exc
    cadenas, detalles = [], []
    for estrategia in res.estrategias:
        cadena = _armar_cadena(estrategia)
        if cadena:
            cadenas.append(cadena)
            detalles.append({"cadena": cadena, "intencion": estrategia.intencion, "alcance": estrategia.alcance})
    return cadenas, res.intencion_consolidada or "", detalles, res.obligatorios


PROVEEDORES = {"nvidia": _con_nvidia}


def _secreto_fuera(texto):
    for secreto in (config.NVIDIA_API_KEY,):
        if secreto:
            texto = texto.replace(secreto, "<key>")
    return texto


def _llamar_llm(tema, n, idioma, terminos=()):
    """Prueba los proveedores de PROVEEDORES en orden. Si todos fallan,
    lanza ValueError con el motivo de cada uno."""
    motivos = []
    for proveedor in PROVEEDORES:
        try:
            res = PROVEEDORES[proveedor](tema, n, idioma, terminos)
            originales = res[0] if isinstance(res, tuple) else res
            if idioma in ("es", "ambos") and proveedor == "nvidia":
                con_tilde = _restaurar_tildes([c for c in originales if isinstance(c, str)])
                originales = [con_tilde.get(c, c) if isinstance(c, str) else c for c in originales]
                if isinstance(res, tuple) and len(res) >= 3:
                    res = (res[0], res[1], [{**d, "cadena": con_tilde.get(d["cadena"], d["cadena"])}
                                            if isinstance(d.get("cadena"), str) else d for d in (res[2] or [])])
            conceptos = conceptos_obligatorios(terminos, res[3] if isinstance(res, tuple) and len(res) >= 4 else None,
                                               idioma)
            # La garantía va antes de normalizar: así el detalle de cada cadena queda emparejado
            reforzadas = {c: asegurar_obligatorios(c, conceptos) for c in originales if isinstance(c, str)}
            originales = [reforzadas.get(c, c) if isinstance(c, str) else c for c in originales]
            if isinstance(res, tuple) and len(res) >= 3:
                res = (res[0], res[1], [{**d, "cadena": reforzadas.get(d["cadena"], d["cadena"])}
                                        if isinstance(d.get("cadena"), str) else d for d in (res[2] or [])])
            cadenas = _limpiar(originales, n, idioma)
            if not cadenas:
                motivos.append(f"{proveedor}: no devolvió ninguna cadena")
                continue
            info = {}
            if isinstance(res, tuple) and len(res) >= 3:
                # Los detalles se alinean con las cadenas ya normalizadas (la interfaz las empareja por texto)
                por_cadena = {_normalizar(d.get("cadena", ""), idioma): d for d in (res[2] or [])
                              if isinstance(d.get("cadena"), str)}
                info = {"intencion_consolidada": res[1] or "",
                        "detalles": [{**(por_cadena.get(c) or {"intencion": "", "alcance": ""}), "cadena": c}
                                     for c in cadenas]}
            info["obligatorios"] = completar_alternativas(cadenas, conceptos)
            return cadenas, info
        except Exception as exc:  # red, JSON malformado, cuota: de muchos tipos
            texto = _secreto_fuera(str(exc)).splitlines()[0][:160] if str(exc) else type(exc).__name__
            motivos.append(f"{proveedor}: {texto}")
            print(f"  [aviso] {proveedor} no generó las cadenas: {type(exc).__name__}: {texto}")
    raise ValueError("; ".join(motivos))


# ---------------------------------------------------------------- aclaración

MAX_RONDAS_ACLARACION = 2
MAX_PREGUNTAS = 4

INSTRUCCIONES_ACLARAR = """Eres un bibliotecario experto en búsquedas bibliográficas. El usuario describe \
lo que quiere investigar, pero a menudo es muy general y no sabe bien qué busca. Antes de generar \
cadenas de búsqueda, decide si el tema tiene suficiente detalle. Un tema es suficiente si deja claro:
1. El objeto de estudio concreto (producto, material, población, tecnología...).
2. Qué se quiere saber de él (propiedades, efectos, variables, comparaciones, métodos...).
3. El contexto que acota la búsqueda (proceso, condiciones, aplicación, tipo de estudio...).
No exijas lo que el usuario ya contestó. Si falta algo importante, haz entre 1 y {max_preguntas} preguntas \
cortas y concretas, cada una con 2 a 4 ejemplos de respuesta posible (el usuario puede ignorarlos). \
No preguntes por idioma, año ni número de cadenas: eso ya se configura aparte. \
Si el tema ya es suficiente, o ya hubo {max_rondas} rondas de preguntas, marca suficiente=true.
Siempre devuelve `tema_refinado`: el tema reescrito en un párrafo, integrando las respuestas del usuario \
(si no hubo respuestas, el tema original sin cambios).

Responde SOLO con un objeto JSON de la forma:
{{"suficiente": true|false, "preguntas": [{{"pregunta": "...", "ejemplos": ["...", "..."]}}], "tema_refinado": "..."}}"""


class PreguntaAclaracion(BaseModel):
    pregunta: str
    ejemplos: list[str] = Field(default_factory=list)


class Aclaracion(BaseModel):
    suficiente: bool
    preguntas: list[PreguntaAclaracion] = Field(default_factory=list)
    tema_refinado: str = ""


def aclarar(tema, historial=None):
    """Evalúa si el tema es lo bastante concreto para buscar. `historial` es la
    lista de rondas anteriores: [{"pregunta": ..., "respuesta": ...}, ...].
    Devuelve {"suficiente", "preguntas", "tema_refinado", "aviso"}. Si el LLM
    no responde, devuelve suficiente=True con un aviso: la búsqueda no debe
    quedar bloqueada por esto."""
    historial = [h for h in (historial or []) if str(h.get("respuesta", "")).strip()]
    rondas = len({h.get("ronda", 1) for h in historial})
    if rondas >= MAX_RONDAS_ACLARACION:
        return {"suficiente": True, "preguntas": [], "tema_refinado": _tema_con_respuestas(tema, historial),
                "aviso": None}
    usuario = f"Tema del usuario: {tema}"
    if historial:
        usuario += "\n\nPreguntas ya hechas y respuestas:\n" + "\n".join(
            f"- {h['pregunta']} -> {h['respuesta']}" for h in historial)
    try:
        resultado = Aclaracion.model_validate_json(llm_nvidia.chat_json(
            INSTRUCCIONES_ACLARAR.format(max_preguntas=MAX_PREGUNTAS, max_rondas=MAX_RONDAS_ACLARACION), usuario, timeout=120))
    except (ValueError, ValidationError, requests.RequestException) as exc:
        return {"suficiente": True, "preguntas": [], "tema_refinado": _tema_con_respuestas(tema, historial),
                "aviso": f"No se pudo pedir aclaraciones al LLM ({_secreto_fuera(str(exc)).splitlines()[0][:120]}); "
                         "se usará el tema tal como está."}
    preguntas = [p.model_dump() for p in resultado.preguntas[:MAX_PREGUNTAS]]
    suficiente = resultado.suficiente or not preguntas
    return {"suficiente": suficiente, "preguntas": [] if suficiente else preguntas,
            "tema_refinado": resultado.tema_refinado.strip() or _tema_con_respuestas(tema, historial),
            "aviso": None}


def _tema_con_respuestas(tema, historial):
    if not historial:
        return tema
    return tema + ". " + " ".join(f"{h['pregunta']} {h['respuesta']}." for h in historial)


def cadenas_basicas(tema, n, terminos=()):
    """Respaldo sin LLM: combina las palabras con contenido del tema (y
    antepone los términos obligatorios, tal como los escribió el usuario)."""
    palabras = []
    for p in re.findall(r"[^\W\d_]{3,}", tema.lower()):
        if p not in _VACIAS and p not in palabras:
            palabras.append(p)
    palabras = palabras[:6] or ["tema"]
    nucleo = " AND ".join(palabras[:3])
    candidatas = [
        nucleo,
        f'{nucleo} AND review OR "systematic review" OR meta-analysis',
        " AND ".join(palabras[:2]),
        " AND ".join(palabras[:4]),
        " OR ".join(palabras[:2]) + (" AND " + " OR ".join(palabras[2:4]) if len(palabras) > 2 else ""),
        " AND ".join(palabras[1:4]),
        f'{" AND ".join(palabras[:2])} AND "clinical trial" OR "randomized"',
        " AND ".join(palabras[2:5]),
    ]
    conceptos = conceptos_obligatorios(terminos)
    return _limpiar([asegurar_obligatorios(c, conceptos) for c in candidatas], n)


def generar(tema, n, idioma="es", terminos_clave=None):
    """Devuelve (cadenas, aviso, info). `aviso` es None si las generó el LLM.
    `info["obligatorios"]` trae cada término obligatorio con sus alternativas."""
    n = max(1, min(int(n), MAX_CADENAS))
    if idioma not in IDIOMAS:
        idioma = "en"
    terminos = limpiar_terminos_clave(terminos_clave)
    try:
        cadenas, info = _llamar_llm(tema, n, idioma, terminos)
        return cadenas, None, info
    except ValueError as exc:
        return cadenas_basicas(tema, n, terminos), (
            f"No se pudo usar el LLM ({exc}). Estas son cadenas básicas armadas con las "
            "palabras del prompt: revísalas y edítalas antes de buscar."
        ), {"obligatorios": conceptos_obligatorios(terminos)}


# Mantener compatibilidad hacia atrás
def generar_legacy(tema, n, idioma="es"):
    cadenas, aviso, _ = generar(tema, n, idioma)
    return cadenas, aviso


generar_con_info = generar

