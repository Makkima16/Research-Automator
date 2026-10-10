"""
Extrae observaciones estructuradas de los abstracts con un LLM y las guarda
en la base de datos (tabla `observaciones`), ya validadas.

    python extract_llm_insights.py            # procesa los top N papers del ranking
    python extract_llm_insights.py --top 100  # procesa más papers
    python extract_llm_insights.py --forzar   # vuelve a extraer aunque ya estén en caché

Envía varios papers por solicitud (config.PAPERS_POR_LOTE_AZURE) para aprovechar
mejor cada llamada a Azure AI Foundry (GPT-5.5).

Es incremental: un paper cuyo abstract no cambió no se vuelve a enviar al LLM.
"""

import argparse
import hashlib
import json
import os
import time
from urllib.parse import urlsplit

import requests

from pydantic import BaseModel, Field, ValidationError

import config_proc as config
import database_proc as database
from esquema import Observacion
from validacion import cita_en_texto, validar_observacion

SYSTEM_PROMPT = """Eres un investigador experto en ciencia de los alimentos y tecnología láctea
(leche A2, caseínas, digestibilidad, formulación de productos lácteos).

Te llegarán varios papers por solicitud, cada uno con un identificador (P1, P2...).
Para CADA paper devuelve un elemento en `papers` con su `paper_ref`, y extrae una
OBSERVACIÓN por cada comparación + variable medida que su abstract reporte.

CÓMO ARMAR CADA OBSERVACIÓN
1. Decide qué grupo es el `factor_evaluado` y cuál la `referencia` (el control).
   Usa SIEMPRE esta dirección, aunque el paper lo redacte al revés:
   - Tratamiento térmico o proceso: el más intenso es el evaluado
     (UHT vs pasteurizada, pasteurizada vs cruda, homogeneizada vs sin homogeneizar,
     almacenamiento más largo o más caliente vs más corto o más frío).
   - Beta-caseína: A2 es el evaluado; A1 o la leche convencional (A1A2) es la referencia.
   - Alimentación: pastoreo o la dieta/suplemento nuevo es el evaluado; la dieta estándar
     (estabulada, TMR, sin suplemento) es la referencia.
   - Estrés térmico, mastitis, células somáticas altas u otra condición adversa: la condición
     adversa es el evaluado; la condición normal es la referencia.
   - Especie: la especie distinta de la vaca es el evaluado; la leche de vaca es la referencia.
   - Raza o genotipo: la raza/genotipo que el estudio destaca es el evaluado; Holstein o el
     genotipo común es la referencia.
   - En otros casos: el tratamiento o la intervención es el evaluado; el control es la referencia.
2. `efecto` = qué le pasa a la variable medida en el FACTOR EVALUADO frente a la REFERENCIA,
   desde el punto de vista de la calidad de la leche y la salud del consumidor:
   - mejora: más proteína o nutrientes, mejor digestibilidad, menos síntomas o inflamación,
     menor carga microbiana, mayor vida útil, mejor sabor o aceptación, mayor estabilidad.
   - empeora: lo contrario.
   - sin_diferencia: el paper reporta que no hay diferencia significativa.
   - mixto: unas cosas mejoran y otras empeoran dentro de la misma variable medida.
   Ejemplo: si el paper dice "la leche cruda conservó más vitaminas que la UHT", entonces
   factor_evaluado = "leche UHT", referencia = "leche cruda", efecto = "empeora".
3. Las características (`matriz`, `tipo_beta_caseina`, `especie_leche`, `raza`,
   `sistema_alimentacion`, `tratamiento_termico`, etc.) describen al GRUPO EVALUADO,
   no a la referencia. Ejemplo: "yogur A2 vs yogur A1" -> tipo_beta_caseina = "A2".
   `region` y `pais` son el origen de la leche o, si no se dice, el país del estudio.

REGLAS GENERALES
- Trata cada paper por separado: nunca mezcles datos de un paper con otro.
- Usa solo lo que dice el texto. Si un dato numérico no aparece, déjalo en null.
- Si una categoría no se menciona, usa "no_especificado" (o "no_aplica" para población).
- Convierte unidades: temperaturas a °C, tiempos a minutos, vida útil a días,
  composición a % (g/100 g), células somáticas a miles de células/mL.
- `cita_textual` debe ser una frase copiada LITERALMENTE del abstract de ESE paper, sin parafrasear.
- Si el texto no reporta ningún resultado concreto, devuelve una lista vacía.
- Si el paper no trata sobre lácteos o proteínas lácteas, marca es_relevante=false."""


# Se agrega al mensaje del usuario solo cuando algún paper del lote trae
# fragmentos del texto completo (fetch_fulltext.py). Va aparte de SYSTEM_PROMPT
# para que agregarlo no invalide la caché de los papers que solo tienen abstract.
INSTRUCCIONES_TEXTO_COMPLETO = """TEXTO COMPLETO
Algunos papers traen, además del abstract, "Fragmentos del texto completo": frases de
métodos y resultados, con su sección entre corchetes. Úsalos para:
- Completar los datos numéricos del grupo evaluado (temperatura_c, tiempo_min, ph,
  proteina_pct, grasa_pct, lactosa_pct, solidos_totales_pct, celulas_somaticas_miles_ml,
  vida_util_dias, tamano_muestra) y las categorías (raza, alimentación, tratamiento, país).
- Extraer comparaciones que el abstract no menciona, si los fragmentos reportan su resultado.
- `cita_textual` puede copiarse LITERALMENTE del abstract o de los fragmentos.
- Ignora los datos que el fragmento atribuye a OTROS estudios (frases con citas como
  [12] o "Smith et al. (2015)"): solo cuentan los resultados de ESTE paper."""


class PaperEnLote(BaseModel):
    paper_ref: str = Field(description="Identificador del paper tal como aparece arriba, ej. P3")
    es_relevante: bool = Field(description="False si el paper no trata sobre lácteos/proteínas lácteas")
    observaciones: list[Observacion] = Field(default_factory=list)


class ExtraccionLote(BaseModel):
    papers: list[PaperEnLote]


def _con_esquema(texto):
    return (texto + "\n\nResponde SOLO con un objeto JSON que cumpla este JSON Schema:\n"
            + json.dumps(ExtraccionLote.model_json_schema(), ensure_ascii=False, separators=(",", ":")))


SISTEMA_CON_ESQUEMA = _con_esquema(SYSTEM_PROMPT)

# Si cambia el esquema o las instrucciones, la caché queda inválida y se vuelve a extraer
VERSION_ESQUEMA = hashlib.sha256(SISTEMA_CON_ESQUEMA.encode()).hexdigest()[:12]


def cargar_env(ruta=config.ENV_PATH):
    """Carga variables KEY=valor desde .env sin dependencias extra."""
    if not os.path.exists(ruta):
        return
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if linea and not linea.startswith("#") and "=" in linea:
                clave, valor = linea.split("=", 1)
                os.environ.setdefault(clave.strip(), valor.strip().strip("'\""))


def verificar_configuracion():
    """True si hay lo necesario para llamar al proveedor configurado."""
    cargar_env()
    if config.LLM_PROVEEDOR == "ollama":
        return True
    if config.LLM_PROVEEDOR == "azure":
        faltan = [v for v in ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY") if not os.environ.get(v)]
        if faltan:
            print(f"ERROR: falta {' y '.join(faltan)} en el archivo .env.")
            return False
        return True
    print(f"ERROR: LLM_PROVEEDOR={config.LLM_PROVEEDOR!r} no existe; usa azure u ollama.")
    return False


class ErrorFatal(Exception):
    """Error que no se arregla reintentando (configuración inválida, API key
    inválida...): se detiene la corrida completa."""


def llamar_llm(lote, intentos=2):
    """Envía un lote de papers y devuelve ({paper_ref: PaperEnLote}, modelo_usado)."""
    mensaje = armar_mensaje_usuario(lote)
    if config.LLM_PROVEEDOR == "ollama":
        return _llamar_ollama(mensaje), config.OLLAMA_MODELO
    resultado = _llamar_azure(mensaje, intentos)
    return {p.paper_ref.strip(): p for p in resultado.papers}, config.AZURE_OPENAI_DEPLOYMENT


def texto_paper(paper):
    texto = f"Título: {paper['title']}\nAbstract: {recortar(paper['abstract'])}"
    if paper["fragmentos"]:
        texto += f"\nFragmentos del texto completo:\n{paper['fragmentos']}"
    return texto


def armar_mensaje_usuario(lote):
    papers = "\n\n".join(f"=== {ref} ===\n{texto_paper(paper)}" for ref, paper in lote.items())
    if any(paper["fragmentos"] for paper in lote.values()):
        papers = INSTRUCCIONES_TEXTO_COMPLETO + "\n\n" + papers
    return papers


def _azure_url():
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
    partes = urlsplit(endpoint)
    if not partes.scheme or not partes.netloc:
        raise ErrorFatal("AZURE_OPENAI_ENDPOINT no es una URL válida. Revisa el archivo .env.")
    return (f"{partes.scheme}://{partes.netloc}/openai/deployments/{config.AZURE_OPENAI_DEPLOYMENT}"
            f"/chat/completions?api-version={config.AZURE_OPENAI_API_VERSION}")


def _llamar_azure(mensaje, intentos):
    """Azure AI Foundry, API de chat completions compatible con OpenAI.

    Si la URL da 404, revisa en Foundry -> Deployments -> tu deployment ->
    "View code" la combinación exacta de ruta y api-version: puede variar
    según el tipo de recurso con el que se creó el deployment."""
    url = _azure_url()
    cuerpo = {
        # GPT-5.5 es un modelo de razonamiento: no acepta "temperature" distinto
        # del valor por defecto (1), a diferencia de los modelos de chat normales.
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SISTEMA_CON_ESQUEMA},
            {"role": "user", "content": mensaje},
        ],
    }
    cabeceras = {"api-key": os.environ.get("AZURE_OPENAI_API_KEY", "")}
    esperas_por_limite = 0
    intento = 0
    while intento < intentos:
        intento += 1
        try:
            resp = requests.post(url, json=cuerpo, headers=cabeceras, timeout=300)
        except requests.RequestException:
            if intento == intentos:
                raise
            time.sleep(15)
            continue
        if resp.status_code == 404:
            raise ErrorFatal(f"404 en {url}\nRevisa AZURE_OPENAI_ENDPOINT en .env y AZURE_OPENAI_DEPLOYMENT/"
                             "AZURE_OPENAI_API_VERSION en config_proc.py contra el código de ejemplo de Foundry.")
        if resp.status_code == 429:
            espera = float(resp.headers.get("retry-after") or 60)
            if espera > 300:
                raise ErrorFatal(f"Límite de uso alcanzado en {url}; se renueva en {espera / 60:.0f} min.")
            esperas_por_limite += 1
            if esperas_por_limite > 5:
                resp.raise_for_status()
            print(f"  -> límite por minuto; esperando {espera:.0f}s")
            time.sleep(espera)
            intento -= 1  # esperar el límite por minuto no cuenta como intento fallido
            continue
        if resp.status_code == 400 and "json_validate_failed" in resp.text:
            if intento == intentos:
                raise ValueError("el modelo devolvió JSON inválido")
            continue
        if resp.status_code == 413:
            raise ValueError(f"solicitud demasiado grande (413): {resp.text[:150]}")
        if 400 <= resp.status_code < 500:
            try:
                detalle = resp.json()["error"]["message"]
            except (ValueError, KeyError, TypeError):
                detalle = resp.text[:300]
            raise ErrorFatal(f"Azure respondió {resp.status_code}: {detalle}\n"
                             "Revisa AZURE_OPENAI_ENDPOINT y AZURE_OPENAI_API_KEY en .env.")
        if resp.status_code >= 500 and intento < intentos:
            time.sleep(15)
            continue
        resp.raise_for_status()
        return parsear_respuesta(resp.json()["choices"][0]["message"]["content"])


def parsear_respuesta(texto):
    """Convierte el JSON del modelo en ExtraccionLote. Una observación con un
    valor fuera del esquema (frecuente en modelos locales pequeños) se
    descarta sola, sin perder el resto del lote."""
    texto = texto.strip()
    if texto.startswith("```"):  # algunos modelos envuelven el JSON en ```json ... ```
        texto = texto.split("\n", 1)[1].rsplit("```", 1)[0]
    datos = json.loads(texto)
    papers, descartadas = [], 0
    for paper in datos.get("papers", []):
        observaciones = []
        for obs in paper.get("observaciones") or []:
            try:
                observaciones.append(Observacion.model_validate(obs))
            except ValidationError:
                descartadas += 1
        papers.append(PaperEnLote(
            paper_ref=str(paper.get("paper_ref", "")),
            es_relevante=bool(paper.get("es_relevante", True)),
            observaciones=observaciones,
        ))
    if descartadas:
        print(f"  -> {descartadas} observaciones descartadas por no cumplir el esquema")
    return ExtraccionLote(papers=papers)


def _llamar_ollama(mensaje):
    """Modelo local con Ollama (https://ollama.com). Sin cuotas: el límite es
    la velocidad de tu PC. `format` obliga al modelo a devolver JSON válido."""
    cuerpo = {
        "model": config.OLLAMA_MODELO,
        "stream": False,
        "format": ExtraccionLote.model_json_schema(),
        "messages": [
            {"role": "system", "content": SISTEMA_CON_ESQUEMA},
            {"role": "user", "content": mensaje},
        ],
        "options": {"temperature": 0, "num_ctx": config.OLLAMA_CONTEXTO},
    }
    try:
        resp = requests.post(config.OLLAMA_URL.rstrip("/") + "/api/chat", json=cuerpo,
                             timeout=config.OLLAMA_TIMEOUT_S)
    except requests.ConnectionError as exc:
        raise ErrorFatal(f"No se pudo conectar con Ollama en {config.OLLAMA_URL}. "
                         "¿Está corriendo? Ábrelo o ejecuta: ollama serve") from exc
    if resp.status_code == 404:
        raise ErrorFatal(f"Ollama no tiene el modelo {config.OLLAMA_MODELO}. "
                         f"Descárgalo con: ollama pull {config.OLLAMA_MODELO}")
    resp.raise_for_status()
    return parsear_respuesta(resp.json()["message"]["content"])


def recortar(abstract):
    return (abstract or "")[:config.MAX_CARACTERES_ABSTRACT]


def tokens_aprox(texto):
    return len(texto) // 4  # ~4 caracteres por token (inglés/español)


def armar_lotes(pendientes, tamano_lote, presupuesto=None):
    """Agrupa papers en lotes de hasta `tamano_lote`; si hay `presupuesto` de
    tokens de entrada, además corta el lote antes de pasarse de él."""
    if not presupuesto:
        return [pendientes[i:i + tamano_lote] for i in range(0, len(pendientes), tamano_lote)]
    fijo = tokens_aprox(SISTEMA_CON_ESQUEMA) + tokens_aprox(INSTRUCCIONES_TEXTO_COMPLETO)
    lotes, actual, usados = [], [], fijo
    for item in pendientes:
        paper = item[0]
        costo = tokens_aprox(texto_paper(paper)) + 20
        if actual and (len(actual) >= tamano_lote or usados + costo > presupuesto):
            lotes.append(actual)
            actual, usados = [], fijo
        actual.append(item)
        usados += costo
    if actual:
        lotes.append(actual)
    return lotes


def _hash(paper):
    """Cambia si cambia el abstract, el esquema/instrucciones o los fragmentos
    del texto completo (así un paper que gana texto completo se vuelve a extraer)."""
    base = f"{paper['title']}\n{paper['abstract'] or ''}\n{VERSION_ESQUEMA}"
    if paper["fragmentos"]:
        base += f"\n{paper['fragmentos']}"
    return hashlib.sha256(base.encode()).hexdigest()


def guardar_resultado(conn, paper, texto_hash, extraccion, modelo):
    """Valida y guarda la extracción de un paper. Devuelve su estado."""
    paper_id = paper["paper_id"]
    if extraccion is None:
        database.guardar_extraccion(conn, paper_id, modelo, "error", texto_hash,
                                    error="el modelo no devolvió este paper en el lote")
        return "error"
    respuesta = extraccion.model_dump(mode="json")
    if not extraccion.es_relevante:
        database.guardar_extraccion(conn, paper_id, modelo, "no_relevante", texto_hash, respuesta)
        return "no_relevante"
    # La cita se verifica contra el texto de ESTE paper, no del lote completo
    abstract = f"{paper['title']}\n{paper['abstract']}"
    texto_fuente = f"{abstract}\n{paper['texto_completo'] or ''}"
    observaciones = []
    for obs in respuesta["observaciones"]:
        obs, valida, problemas = validar_observacion(obs, texto_fuente)
        if obs["cita_verificada"]:
            obs["cita_en"] = "abstract" if cita_en_texto(obs["cita_textual"], abstract) else "texto_completo"
        observaciones.append((obs, valida, problemas))
    database.guardar_extraccion(conn, paper_id, modelo, "ok", texto_hash, respuesta,
                                observaciones=observaciones)
    return "ok"


def extraer(conn, top=None, forzar=False, pausa=None, tamano_lote=None, paper_ids=None, avance=None,
            al_terminar_paper=None, relanzar_fatal=False):
    """Si se da `paper_ids`, extrae solo esos papers (ignora `top`); si no,
    toma los top N del ranking. `avance(mensaje)`, si se da, recibe cada línea
    de progreso además de imprimirse; `al_terminar_paper(paper, estado)` se
    llama una vez por paper cuando queda resuelto (incluidos los de caché).
    Con `relanzar_fatal`, un ErrorFatal se vuelve a lanzar después de avisar
    (lo ya procesado queda guardado igual)."""
    def reportar(msg):
        print(msg)
        if avance:
            avance(msg)

    def terminado(paper, estado):
        if al_terminar_paper:
            al_terminar_paper(paper, estado)

    if config.LLM_PROVEEDOR == "ollama":
        tamano_lote = tamano_lote or config.PAPERS_POR_LOTE_LOCAL
        pausa = 0  # sin límite de solicitudes por minuto
    else:
        tamano_lote = tamano_lote or config.PAPERS_POR_LOTE_AZURE
        pausa = config.PAUSA_AZURE_S if pausa is None else pausa
    if paper_ids:
        marcadores = ", ".join("?" for _ in paper_ids)
        papers = conn.execute(
            f"""SELECT p.paper_id, p.title, p.abstract, t.fragmentos, t.texto AS texto_completo
               FROM papers p LEFT JOIN textos_completos t ON t.paper_id = p.paper_id AND t.estado = 'ok'
               WHERE p.paper_id IN ({marcadores})""", paper_ids
        ).fetchall()
    else:
        papers = conn.execute(
            """SELECT p.paper_id, p.title, p.abstract, t.fragmentos, t.texto AS texto_completo
               FROM papers p LEFT JOIN textos_completos t ON t.paper_id = p.paper_id AND t.estado = 'ok'
               ORDER BY p.score DESC LIMIT ?""", (top,)
        ).fetchall()
    if not papers:
        reportar("No hay papers en la base. Corre primero: python ../busqueda/main.py")
        return {}

    conteo = {}
    pendientes = []
    for paper in papers:
        texto_hash = _hash(paper)
        previa = database.extraccion_existente(conn, paper["paper_id"])
        if not forzar and previa and previa["texto_hash"] == texto_hash and previa["estado"] != "error":
            estado = "cache"
        elif len((paper["abstract"] or "").split()) < 30 and not paper["fragmentos"]:
            database.guardar_extraccion(conn, paper["paper_id"], None, "sin_abstract", texto_hash)
            estado = "sin_abstract"
        else:
            pendientes.append((paper, texto_hash))
            continue
        conteo[estado] = conteo.get(estado, 0) + 1
        terminado(paper, estado)

    presupuesto = config.MAX_TOKENS_ENTRADA_AZURE if config.LLM_PROVEEDOR == "azure" else None
    lotes = armar_lotes(pendientes, tamano_lote, presupuesto)
    reportar(f"{len(papers)} papers: {conteo.get('cache', 0)} ya procesados, "
             f"{conteo.get('sin_abstract', 0)} sin abstract, {len(pendientes)} por enviar "
             f"en {len(lotes)} solicitudes de hasta {tamano_lote} papers.")

    for n, lote in enumerate(lotes, 1):
        por_ref = {f"P{i}": item for i, item in enumerate(lote, 1)}
        reportar(f"Lote {n}/{len(lotes)}...")
        try:
            resultados, modelo = llamar_llm({ref: paper for ref, (paper, _) in por_ref.items()})
        except ErrorFatal as exc:
            reportar(f"Deteniendo: {exc}")
            reportar("Lo ya procesado quedó guardado; al volver a correr se retoma.")
            if relanzar_fatal:
                raise
            break
        except Exception as exc:
            for paper, texto_hash in lote:
                database.guardar_extraccion(conn, paper["paper_id"], None, "error", texto_hash, error=str(exc))
                terminado(paper, "error")
            conteo["error"] = conteo.get("error", 0) + len(lote)
            reportar(f"  -> lote fallido: {str(exc)[:150]}")
            continue

        for ref, (paper, texto_hash) in por_ref.items():
            estado = guardar_resultado(conn, paper, texto_hash, resultados.get(ref), modelo)
            conteo[estado] = conteo.get(estado, 0) + 1
            reportar(f"  {estado:<13} {(paper['title'] or '')[:80]}")
            terminado(paper, estado)
        if n < len(lotes):
            time.sleep(pausa)  # respetar el límite de solicitudes por minuto
    return conteo


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--top", type=int, default=config.MAX_PAPERS_TO_EXTRACT)
    parser.add_argument("--forzar", action="store_true", help="ignorar la caché y volver a extraer")
    args = parser.parse_args()

    if not verificar_configuracion():
        return

    conn = database.conectar(config.DB_PATH)
    conteo = extraer(conn, args.top, args.forzar)
    validas, total = conn.execute(
        "SELECT COALESCE(SUM(valida), 0), COUNT(*) FROM observaciones"
    ).fetchone()
    print(f"\nResumen por paper: {conteo}")
    print(f"Observaciones en la base: {total} ({validas} válidas).")
    print("Siguiente paso: python build_dataset.py")


if __name__ == "__main__":
    main()
