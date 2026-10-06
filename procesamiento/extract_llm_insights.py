"""
Extrae observaciones estructuradas de los abstracts con Gemini y las guarda
en la base de datos (tabla `observaciones`), ya validadas.

    python extract_llm_insights.py            # procesa los top N papers del ranking
    python extract_llm_insights.py --top 100  # procesa más papers
    python extract_llm_insights.py --forzar   # vuelve a extraer aunque ya estén en caché

Envía varios papers por solicitud (config.PAPERS_POR_LOTE) para rendir la cuota
gratuita de Gemini, que es de pocas solicitudes por día.

Es incremental: un paper cuyo abstract no cambió no se vuelve a enviar al LLM.
"""

import argparse
import hashlib
import json
import os
import time

import requests

from pydantic import BaseModel, Field, ValidationError

import config_proc as config
import database_proc as database
from esquema import Observacion
from validacion import cita_en_texto, validar_observacion

PROMPT = """Eres un investigador experto en ciencia de los alimentos y tecnología láctea
(leche A2, caseínas, digestibilidad, formulación de productos lácteos).

Abajo hay varios papers, cada uno con un identificador (P1, P2...). Para CADA paper
devuelve un elemento en `papers` con su `paper_ref`, y extrae una OBSERVACIÓN por cada
comparación + variable medida que su abstract reporte.

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
- Si el paper no trata sobre lácteos o proteínas lácteas, marca es_relevante=false.

{papers}
"""


# Se agrega al prompt solo cuando algún paper del lote trae fragmentos del texto
# completo (fetch_fulltext.py). Va aparte de PROMPT para que agregarlo no
# invalide la caché de los papers que solo tienen abstract.
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


# Si cambia el esquema o el prompt, la caché queda inválida y se vuelve a extraer
VERSION_ESQUEMA = hashlib.sha256(
    (json.dumps(ExtraccionLote.model_json_schema(), sort_keys=True) + PROMPT).encode()
).hexdigest()[:12]


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


def crear_cliente():
    """Devuelve el cliente de Gemini, o el nombre del proveedor si es uno
    que se llama por HTTP (ollama u openai). None si falta configuración."""
    cargar_env()
    if config.LLM_PROVEEDOR == "ollama":
        return "ollama"
    if config.LLM_PROVEEDOR == "openai":
        if not os.environ.get("LLM_API_KEY"):
            print("ERROR: falta LLM_API_KEY. Agrégala al archivo .env así:")
            print("LLM_API_KEY=tu_api_key")
            return None
        return "openai"
    if config.LLM_PROVEEDOR != "gemini":
        print(f"ERROR: LLM_PROVEEDOR={config.LLM_PROVEEDOR!r} no existe; usa gemini, ollama u openai.")
        return None
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        print("ERROR: falta GEMINI_API_KEY. Agrégala al archivo .env así:")
        print("GEMINI_API_KEY=tu_api_key")
        return None
    from google import genai
    from google.genai import types
    # La librería reintenta sola hasta 5 veces cada error, lo que multiplica las
    # solicitudes contra la cuota; los reintentos los controla este script.
    return genai.Client(api_key=key, http_options=types.HttpOptions(
        retry_options=types.HttpRetryOptions(attempts=1)))


MAX_LOTES_FALLIDOS_SEGUIDOS = 3


class ErrorFatal(Exception):
    """Error que no se arregla reintentando (modelo inexistente, API key
    inválida, cuota diaria agotada): se detiene la corrida completa."""


class CuotaDiariaAgotada(ErrorFatal):
    """La cuota gratuita es por modelo y por día: se puede pasar a otro modelo."""


_modelos_agotados = set()


def llamar_llm(client, lote, intentos=2):
    """Envía un lote de papers y devuelve ({paper_ref: PaperEnLote}, modelo_usado).
    Con Gemini, si un modelo está saturado (503) o agotó su cuota diaria,
    prueba el siguiente de config.LLM_MODELOS_RESPALDO."""
    prompt = armar_prompt(lote)
    if config.LLM_PROVEEDOR == "ollama":
        resultado, modelo = _llamar_ollama(prompt), config.OLLAMA_MODELO
    elif config.LLM_PROVEEDOR == "openai":
        resultado, modelo = _llamar_openai(prompt, intentos), config.OPENAI_MODELO
    else:
        return _llamar_gemini(client, prompt, intentos)
    return {p.paper_ref.strip(): p for p in resultado.papers}, modelo


def texto_paper(paper):
    texto = f"Título: {paper['title']}\nAbstract: {recortar(paper['abstract'])}"
    if paper["fragmentos"]:
        texto += f"\nFragmentos del texto completo:\n{paper['fragmentos']}"
    return texto


def armar_prompt(lote):
    papers = "\n\n".join(f"=== {ref} ===\n{texto_paper(paper)}" for ref, paper in lote.items())
    if any(paper["fragmentos"] for paper in lote.values()):
        papers = INSTRUCCIONES_TEXTO_COMPLETO + "\n\n" + papers
    return PROMPT.format(papers=papers)


def _llamar_gemini(client, prompt, intentos):
    modelos = [m for m in [config.LLM_MODEL] + config.LLM_MODELOS_RESPALDO
               if m not in _modelos_agotados]
    if not modelos:
        raise ErrorFatal("Todos los modelos agotaron su cuota diaria gratuita. Vuelve a correr mañana.")

    ultimo_error = None
    for modelo in modelos:
        try:
            resultado = _llamar_modelo(client, modelo, prompt, intentos)
            print(f"  -> respondió {modelo}")
            return {p.paper_ref.strip(): p for p in resultado.papers}, modelo
        except CuotaDiariaAgotada:
            _modelos_agotados.add(modelo)
            print(f"  -> {modelo} agotó su cuota diaria")
        except ErrorFatal:
            raise
        except Exception as exc:
            if getattr(exc, "code", None) != 503:
                raise
            print(f"  -> {modelo} saturado")
            ultimo_error = exc
    if ultimo_error is None:
        raise ErrorFatal("Todos los modelos agotaron su cuota diaria gratuita. Vuelve a correr mañana.")
    raise ultimo_error  # saturación temporal: el lote queda como error y se reintenta después


def _llamar_modelo(client, modelo, prompt, intentos):
    from google.genai import types

    for intento in range(1, intentos + 1):
        try:
            response = client.models.generate_content(
                model=modelo,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ExtraccionLote,
                    temperature=0.0,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                ),
            )
            return parsear_respuesta(response.text)
        except ValidationError:
            raise
        except Exception as exc:
            codigo = getattr(exc, "code", None)
            if codigo == 429 and "PerDay" in str(exc):
                raise CuotaDiariaAgotada(str(exc)) from exc
            if isinstance(codigo, int) and 400 <= codigo < 500 and codigo != 429:
                raise ErrorFatal(f"{exc}\nRevisa LLM_MODEL en config_proc.py y GEMINI_API_KEY en .env.") from exc
            if intento == intentos:
                raise
            espera = 60 if codigo == 429 else 15  # 429 por minuto: esperar a que se renueve
            print(f"  -> {modelo}: error {codigo or exc}; reintentando en {espera}s")
            time.sleep(espera)


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


def _prompt_con_esquema(prompt):
    return (prompt + "\n\nResponde SOLO con un objeto JSON que cumpla este JSON Schema:\n"
            + json.dumps(ExtraccionLote.model_json_schema(), ensure_ascii=False, separators=(",", ":")))


def _llamar_ollama(prompt):
    """Modelo local con Ollama (https://ollama.com). Sin cuotas: el límite es
    la velocidad de tu PC. `format` obliga al modelo a devolver JSON válido."""
    cuerpo = {
        "model": config.OLLAMA_MODELO,
        "stream": False,
        "format": ExtraccionLote.model_json_schema(),
        "messages": [{"role": "user", "content": _prompt_con_esquema(prompt)}],
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


def _llamar_openai(prompt, intentos):
    """Cualquier API compatible con OpenAI (Groq, OpenRouter, Mistral, etc.)."""
    url = config.OPENAI_BASE_URL.rstrip("/") + "/chat/completions"
    cuerpo = {
        "model": config.OPENAI_MODELO,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "user", "content": _prompt_con_esquema(prompt)}],
    }
    cabeceras = {"Authorization": f"Bearer {os.environ.get('LLM_API_KEY', '')}"}
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
            # El modelo generó JSON inválido: es un fallo de ese intento, no de la configuración
            if intento == intentos:
                raise ValueError("el modelo devolvió JSON inválido")
            continue
        if resp.status_code == 413:
            # Solicitud demasiado grande para el límite por minuto: falla este lote, no la corrida
            raise ValueError(f"solicitud demasiado grande (413): {resp.text[:150]}")
        if 400 <= resp.status_code < 500:
            raise ErrorFatal(f"{resp.status_code}: {resp.text[:300]}\n"
                             "Revisa OPENAI_BASE_URL y OPENAI_MODELO en config_proc.py y LLM_API_KEY en .env.")
        if resp.status_code >= 500 and intento < intentos:
            time.sleep(15)
            continue
        resp.raise_for_status()
        return parsear_respuesta(resp.json()["choices"][0]["message"]["content"])


def recortar(abstract):
    return (abstract or "")[:config.MAX_CARACTERES_ABSTRACT]


def tokens_aprox(texto):
    return len(texto) // 4  # ~4 caracteres por token (inglés/español)


def armar_lotes(pendientes, tamano_lote, presupuesto=None):
    """Agrupa papers en lotes de hasta `tamano_lote`; si hay `presupuesto` de
    tokens de entrada, además corta el lote antes de pasarse de él."""
    if not presupuesto:
        return [pendientes[i:i + tamano_lote] for i in range(0, len(pendientes), tamano_lote)]
    fijo = (tokens_aprox(PROMPT) + tokens_aprox(INSTRUCCIONES_TEXTO_COMPLETO)
            + tokens_aprox(json.dumps(ExtraccionLote.model_json_schema(), separators=(",", ":"))))
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
    """Cambia si cambia el abstract, el esquema/prompt o los fragmentos del texto
    completo (así un paper que gana texto completo se vuelve a extraer)."""
    base = f"{paper['title']}\n{paper['abstract'] or ''}\n{VERSION_ESQUEMA}"
    if paper["fragmentos"]:
        base += f"\n{paper['fragmentos']}\n{INSTRUCCIONES_TEXTO_COMPLETO}"
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


def extraer(conn, client, top, forzar=False, pausa=None, tamano_lote=None):
    pausa = config.PAUSA_ENTRE_LLAMADAS_S if pausa is None else pausa
    if config.LLM_PROVEEDOR == "ollama":
        tamano_lote = tamano_lote or config.PAPERS_POR_LOTE_LOCAL
        pausa = 0  # sin límite de solicitudes por minuto
    elif config.LLM_PROVEEDOR == "openai":
        tamano_lote = tamano_lote or config.PAPERS_POR_LOTE_API
        pausa = config.PAUSA_API_S if pausa is None else pausa
    tamano_lote = tamano_lote or config.PAPERS_POR_LOTE
    papers = conn.execute(
        """SELECT p.paper_id, p.title, p.abstract, t.fragmentos, t.texto AS texto_completo
           FROM papers p LEFT JOIN textos_completos t ON t.paper_id = p.paper_id AND t.estado = 'ok'
           ORDER BY p.score DESC LIMIT ?""", (top,)
    ).fetchall()
    if not papers:
        print("No hay papers en la base. Corre primero: python ../busqueda/main.py")
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

    presupuesto = config.MAX_TOKENS_ENTRADA_API if config.LLM_PROVEEDOR == "openai" else None
    lotes = armar_lotes(pendientes, tamano_lote, presupuesto)
    print(f"{len(papers)} papers: {conteo.get('cache', 0)} ya procesados, "
          f"{conteo.get('sin_abstract', 0)} sin abstract, {len(pendientes)} por enviar "
          f"en {len(lotes)} solicitudes de hasta {tamano_lote} papers.")

    fallidos_seguidos = 0
    for n, lote in enumerate(lotes, 1):
        por_ref = {f"P{i}": item for i, item in enumerate(lote, 1)}
        print(f"Lote {n}/{len(lotes)}...")
        try:
            resultados, modelo = llamar_llm(client, {ref: paper for ref, (paper, _) in por_ref.items()})
        except ErrorFatal as exc:
            print(f"\nDeteniendo: {exc}")
            print("Lo ya procesado quedó guardado; al volver a correr se retoma.")
            break
        except Exception as exc:
            for paper, texto_hash in lote:
                database.guardar_extraccion(conn, paper["paper_id"], None, "error", texto_hash, error=str(exc))
            conteo["error"] = conteo.get("error", 0) + len(lote)
            fallidos_seguidos += 1
            print(f"  -> lote fallido: {str(exc)[:150]}")
            if getattr(exc, "code", None) == 503 and fallidos_seguidos < MAX_LOTES_FALLIDOS_SEGUIDOS:
                print(f"  -> todos los modelos saturados; esperando {config.ESPERA_SATURACION_S}s")
                time.sleep(config.ESPERA_SATURACION_S)
            if fallidos_seguidos >= MAX_LOTES_FALLIDOS_SEGUIDOS:
                print(f"\nDeteniendo: {fallidos_seguidos} lotes seguidos fallaron (Gemini saturado o sin conexión).")
                print("Intenta más tarde; lo ya procesado quedó guardado y al volver a correr se retoma.")
                break
            continue

        fallidos_seguidos = 0
        for ref, (paper, texto_hash) in por_ref.items():
            estado = guardar_resultado(conn, paper, texto_hash, resultados.get(ref), modelo)
            conteo[estado] = conteo.get(estado, 0) + 1
            print(f"  {estado:<13} {(paper['title'] or '')[:80]}")
        if n < len(lotes):
            time.sleep(pausa)  # respetar el límite de solicitudes por minuto
    return conteo


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--top", type=int, default=config.MAX_PAPERS_TO_EXTRACT)
    parser.add_argument("--forzar", action="store_true", help="ignorar la caché y volver a extraer")
    args = parser.parse_args()

    client = crear_cliente()
    if client is None:
        return

    conn = database.conectar(config.DB_PATH)
    conteo = extraer(conn, client, args.top, args.forzar)
    validas, total = conn.execute(
        "SELECT COALESCE(SUM(valida), 0), COUNT(*) FROM observaciones"
    ).fetchone()
    print(f"\nResumen por paper: {conteo}")
    print(f"Observaciones en la base: {total} ({validas} válidas).")
    print("Siguiente paso: python build_dataset.py")


if __name__ == "__main__":
    main()
