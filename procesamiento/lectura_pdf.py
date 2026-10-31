"""
Lee la estructura de un paper y se queda solo con lo que le interesa al proyecto:

- abstract
- penúltimo y último párrafo de la introducción (donde los autores plantean el
  problema y declaran el objetivo)
- conclusiones
- tablas: nombre (caption) y atributos (encabezados de columna)

Es el paso barato: el LLM (Nemotron) ya no recibe el paper entero, solo estas
piezas (ver extract_ficha.py). Nemotron Parse (NVIDIA) lee páginas como imagen y
es lento (decenas de segundos por página), así que el PDF se lee en dos tiempos
(estructura_hibrida):
1. En local y gratis con pymupdf, solo en memoria (el PDF nunca se guarda en
   disco): abstract, introducción y conclusiones salen del texto, y se anota en
   qué páginas aparecen los títulos "Table N".
2. Nemotron Parse recibe únicamente esas páginas, para leer bien las tablas. Si
   el PDF no tiene texto o el lector local no encuentra la introducción y el
   abstract, se le envían las páginas que pymupdf ubicó (las primeras, las de las
   conclusiones y las de las tablas) o, si el PDF no tiene texto, las primeras y las últimas.
Los papers que están en Europe PMC ya traen su estructura en XML gratis: para
esos no se usa ni lo uno ni lo otro (ver estructura_europepmc).

    python lectura_pdf.py ruta/al/paper.pdf     # prueba con un PDF local (usa el modo híbrido)
"""

import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

import requests

import config_proc as config

MAX_BYTES_PDF = 40 * 1024 * 1024
MAX_ATRIBUTOS_POR_TABLA = 30
MAX_CARACTERES_NOMBRE_TABLA = 300
MIN_CARACTERES_PARRAFO = 150          # un "último párrafo" más corto suele ser una frase suelta o un pie
MAX_CARACTERES_SECCION = 3000         # tope por pieza que se envía al LLM

RE_ABSTRACT = re.compile(r"^\W*(?:\d+\.?\s*)?(abstract|summary|resumen)\W*$", re.I)
RE_INTRO = re.compile(r"^\W*(?:\d+\.?\s*)?(introduc|background)", re.I)
RE_CONCLUSION = re.compile(r"^\W*(?:\d+\.?\s*)?(conclu|concluding|final remarks|resumen y conclu)", re.I)
# Encabezados que cierran la introducción (los de la subsección 1.1 no)
RE_FIN_INTRO = re.compile(r"method|material|experimental|result|discussion|conclu|procedure|"
                          r"related work|theor|model|approach|literature", re.I)
RE_NUMERO_SECCION = re.compile(r"^\W*(\d{1,2})(?:\.\d+)*\.?\s")


def _numero_principal(titulo):
    """Número de la sección de nivel superior ('3.1 Encoder' -> 3), o None."""
    m = RE_NUMERO_SECCION.match(titulo)
    return int(m.group(1)) if m else None


def _termina_intro(titulo, num_intro):
    """True si este encabezado cierra la introducción. Con secciones numeradas, el
    primer encabezado de otro número principal; si no, uno de los títulos típicos."""
    numero = _numero_principal(titulo)
    if numero is not None and num_intro is not None:
        return numero != num_intro
    return bool(RE_FIN_INTRO.search(titulo))


RE_REFERENCIAS = re.compile(r"^\W*(?:\d+\.?\s*)?(references|bibliography|literature cited|acknowledg|funding|"
                            r"conflicts? of interest|declaration|author contribution|appendix)", re.I)


class ErrorLecturaPDF(Exception):
    """Fallo al leer un PDF con Nemotron Parse. `fatal` = reintentar no sirve
    (key inválida): hay que detener la corrida."""

    def __init__(self, mensaje, fatal=False):
        super().__init__(mensaje)
        self.fatal = fatal


def configurado():
    return bool(config.NVIDIA_PARSE_API_KEY)


# --------------------------------------------------------------- Nemotron Parse

# Bloques que Nemotron Parse devuelve como <x_..><y_..>texto<x_..><y_..><class_Clase>
RE_BLOQUE = re.compile(r"<x_[\d.]+><y_[\d.]+>(.*?)<x_[\d.]+><y_[\d.]+><class_([\w-]+)>", re.S)
CLASES_IGNORADAS = {"Page-header", "Page-footer", "Footnote", "Formula", "Picture", "Chart", "Bibliography"}
DPI_PARSE = 130


def _parse_pagina(png):
    """Texto marcado que devuelve Nemotron Parse para la imagen de una página."""
    cabeceras = {"Authorization": f"Bearer {config.NVIDIA_PARSE_API_KEY}", "Accept": "application/json"}
    archivos = {"document": ("pagina.png", png, "image/png"),
                "options": (None, '{"decoding": {"max_output_tokens": 4096}}', "application/json")}
    for intento in range(1, 4):
        try:
            resp = requests.post(config.NVIDIA_URL_PARSE, headers=cabeceras, files=archivos, timeout=240)
        except requests.RequestException as exc:
            if intento == 3:
                raise ErrorLecturaPDF(f"Nemotron Parse no respondió: {exc}") from exc
            time.sleep(10)
            continue
        if resp.status_code == 429 and intento < 3:
            time.sleep(min(float(resp.headers.get("Retry-After") or 20), 60))
            continue
        break
    if resp.status_code in (401, 403, 404):
        raise ErrorLecturaPDF(f"Nemotron Parse respondió {resp.status_code}: revisa NVIDIA_PARSE_API_KEY en .env.",
                              fatal=True)
    if not resp.ok:
        raise ErrorLecturaPDF(f"Nemotron Parse respondió {resp.status_code}: {resp.text[:200]}")
    return resp.json().get("content") or ""


def analizar_paginas(pdf_bytes, paginas):
    """{número de página (desde 1): texto marcado} de las páginas pedidas, leídas en
    paralelo (el PDF se convierte a imagen en memoria)."""
    if len(pdf_bytes) > MAX_BYTES_PDF:
        raise ErrorLecturaPDF(f"el PDF pesa {len(pdf_bytes) // 1_000_000} MB; el máximo es "
                              f"{MAX_BYTES_PDF // 1_000_000} MB")
    import pymupdf
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        numeros = [n for n in sorted(set(paginas)) if 1 <= n <= len(doc)]
        imagenes = [doc[n - 1].get_pixmap(dpi=DPI_PARSE).tobytes("png") for n in numeros]
    finally:
        doc.close()
    with ThreadPoolExecutor(config.HILOS_PARSE) as pool:
        return dict(zip(numeros, pool.map(_parse_pagina, imagenes)))


def _paginas_respaldo(pdf_bytes, local):
    """Páginas que Nemotron Parse debe leer en un PDF cuya estructura el lector local no
    entendió. Si el PDF tiene texto, pymupdf ya ubicó las páginas exactas: las primeras
    (abstract e introducción), las de las conclusiones y las de los títulos "Table N".
    Si no (escaneado), no hay cómo ubicarlas y se leen las primeras y las últimas."""
    import pymupdf
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        total = len(doc)
    finally:
        doc.close()
    primeras = config.PAGINAS_INICIALES_PARSE
    if local:
        _, paginas_tabla, _, paginas_conclusion = local
        elegidas = set(range(1, primeras + 1)) | set(paginas_conclusion) | set(paginas_tabla[:config.MAX_PAGINAS_TABLAS_PARSE])
        return [n for n in sorted(elegidas) if n <= total]
    if total <= config.MAX_PAGINAS_PARSE:
        return list(range(1, total + 1))
    return list(range(1, primeras + 1)) + list(range(total - (config.MAX_PAGINAS_PARSE - primeras) + 1, total + 1))


def _sin_markdown(texto):
    """Nemotron Parse devuelve Markdown (## títulos, **negrita**, _cursiva_): se quita."""
    texto = re.sub(r"^\s*#+\s*", "", texto)
    texto = texto.replace("**", "")
    texto = re.sub(r"(?<!\w)_+(.+?)_+(?!\w)", r"\1", texto)
    return _limpiar(texto)


def _latex_a_texto(celda):
    celda = re.sub(r"\\(?:textbf|textit|mathrm|text|emph|multicolumn\{[^{}]*\}\{[^{}]*\})\{([^{}]*)\}", r"\1", celda)
    return _limpiar(re.sub(r"\\[a-zA-Z]+", " ", celda).replace("{", "").replace("}", ""))


def _encabezados_latex(tabular):
    """Celdas de la primera fila de un \\begin{tabular}...: los atributos de la tabla."""
    cuerpo = re.sub(r"\\(?:begin|end)\{tabular\}(?:\{[^{}]*\})?|\\hline", " ", tabular)
    filas = [f for f in re.split(r"\\\\", cuerpo) if f.strip()]
    if not filas:
        return []
    celdas = [_latex_a_texto(c) for c in filas[0].split("&")]
    return [c for c in celdas if c][:MAX_ATRIBUTOS_POR_TABLA]


def secciones_y_tablas_desde_parse(paginas):
    """`paginas` = {n: texto marcado}. Devuelve ([(título, [párrafos])], [{nombre, atributos}]).
    Cada título de tabla ("Table 2: ...") se empareja, por orden de aparición en la
    página, con el bloque de tabla que Nemotron Parse leyó; sin bloque, queda sin atributos."""
    secciones, titulo, actual, tablas = [], "", [], []
    for n in sorted(paginas):
        captions, bloques_tabla = [], []
        for crudo, clase in RE_BLOQUE.findall(paginas[n]):
            if clase in CLASES_IGNORADAS:
                continue
            if clase == "Table":
                bloques_tabla.append(crudo)
                continue
            texto = _sin_markdown(crudo)
            if not texto:
                continue
            if clase == "Caption" and RE_CAPTION_TABLA.match(texto):
                captions.append(texto[:MAX_CARACTERES_NOMBRE_TABLA])
            elif clase in ("Title", "Section-header"):
                if actual or titulo:
                    secciones.append((titulo, actual))
                titulo, actual = texto, []
            elif clase in ("Text", "List-item") and len(texto) >= 40:
                actual.append(texto)
        for i, caption in enumerate(captions):
            atributos = _encabezados_latex(bloques_tabla[i]) if i < len(bloques_tabla) else []
            tablas.append({"nombre": caption, "atributos": atributos})
    if actual or titulo:
        secciones.append((titulo, actual))
    return secciones, tablas


# ------------------------------------------------- estructura -> piezas útiles

def _limpiar(texto):
    return re.sub(r"\s+", " ", texto or "").strip()


def _recortar(texto, maximo=MAX_CARACTERES_SECCION):
    texto = _limpiar(texto)
    return texto if len(texto) <= maximo else texto[:maximo].rsplit(" ", 1)[0] + "…"


def _ultimos_parrafos(parrafos):
    """(penúltimo, último) párrafo de la introducción; cualquiera puede ser None.
    Se prefieren los párrafos de cuerpo (largos): uno corto suele ser una frase
    suelta o un pie. Solo si ninguno es largo se usan los últimos que haya."""
    largos = [p for p in parrafos if len(p) >= MIN_CARACTERES_PARRAFO]
    elegidos = largos[-2:] if largos else parrafos[-2:]
    if not elegidos:
        return None, None
    return (elegidos[0] if len(elegidos) == 2 else None), elegidos[-1]


def piezas_desde_secciones(secciones):
    """`secciones` = [(título, [párrafos])] en orden. Devuelve (abstract,
    penultimo_parrafo_intro, ultimo_parrafo_intro, conclusion); cada una puede
    ser None."""
    abstract = conclusion = None
    en_intro, parrafos_intro, num_intro = False, [], None
    for titulo, parrafos in secciones:
        if RE_REFERENCIAS.search(titulo):
            break
        if RE_ABSTRACT.search(titulo) and abstract is None:
            abstract = _recortar(" ".join(parrafos)) or None
        elif RE_CONCLUSION.search(titulo):
            texto = _recortar(" ".join(parrafos))
            if texto and not conclusion:
                conclusion = texto
        elif RE_INTRO.search(titulo) and not en_intro and not parrafos_intro:
            en_intro, parrafos_intro, num_intro = True, list(parrafos), _numero_principal(titulo)
        elif en_intro and not _termina_intro(titulo, num_intro):
            parrafos_intro += parrafos      # subsección de la introducción (ej. "1.1 Antecedentes")
        else:
            en_intro = False
    penultimo, ultimo = _ultimos_parrafos(parrafos_intro)
    return (abstract, _recortar(penultimo) if penultimo else None, _recortar(ultimo) if ultimo else None,
            conclusion)


def estructura_desde_parse(paginas, fuente_url=None):
    secciones, tablas = secciones_y_tablas_desde_parse(paginas)
    abstract, penultimo, ultimo, conclusion = piezas_desde_secciones(secciones)
    return {"fuente": "nemotron_parse", "url": fuente_url, "abstract": abstract,
            "intro_penultimo_parrafo": penultimo, "intro_ultimo_parrafo": ultimo, "conclusion": conclusion,
            "tablas": tablas, "paginas": len(paginas)}


# ---------------------------------------------------- lectura local (gratis)

RE_ENCABEZADO = re.compile(
    r"^\W*(?:\d+(?:\.\d+)*\.?\s*|[IVX]+\.\s*)?(abstract|summary|resumen|introduc\w*|background|"
    r"materials?(?: and methods?)?|methods?|experimental(?: section| procedures?)?|results?(?: and discussion)?|"
    r"discussion|conclusions?|concluding remarks|references|bibliography|acknowledg\w*|funding|"
    r"declaration\w*|conflicts? of interest|author contributions?|appendix)\W*$", re.I)
# Encabezado numerado de cualquier título ("3 Model Architecture", "3.1 Encoder"): corto y sin punto final
RE_ENCABEZADO_NUMERADO = re.compile(r"^\d{1,2}(?:\.\d+)*\.?\s+[A-Z][^.!?]{2,80}$")
# Manuscritos con números de línea en el margen ("480 5. Conclusion"): se quitan antes de buscar el encabezado
RE_NUMERO_LINEA = re.compile(r"^\d{1,4}\s+(?=\d+(?:\.\d+)*\.?\s)")
RE_CAPTION_TABLA = re.compile(r"^\s*(?:table|tabla)\s+(?:[0-9]+|[IVX]+)\s*[.:|\-–—]", re.I)
# Algunas revistas escriben "Table 1 Composition of..." sin puntuación: solo vale en bloques cortos,
# para no tomar por título una frase como "Table 1 shows..."
RE_CAPTION_TABLA_SIN_PUNTO = re.compile(r"^\s*(?:table|tabla)\s+(?:[0-9]+|[IVX]+)\s+[A-Z]", re.I)
MAX_CARACTERES_CAPTION_SIN_PUNTO = 250
MIN_CARACTERES_POR_PAGINA = 300     # menos que esto de texto por página: PDF escaneado


def leer_local(pdf_bytes):
    """Lee el PDF en memoria con pymupdf (gratis; nada se escribe en disco).
    Devuelve (secciones, paginas_con_tabla, captions, paginas_conclusion) o None
    si el PDF no tiene texto utilizable. `secciones` = [(título, [párrafos])] en
    orden de lectura; `paginas_con_tabla` = números de página (desde 1) donde
    empieza el título de una tabla; `captions` = esos títulos;
    `paginas_conclusion` = página del encabezado de las conclusiones y la
    siguiente (el texto puede seguir allí)."""
    try:
        import pymupdf
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return None
    try:
        secciones, titulo, actual = [], "", []
        paginas_tabla, captions, paginas_conclusion, total = [], [], [], 0
        for n, pagina in enumerate(doc, 1):
            for bloque in pagina.get_text("blocks"):
                if bloque[6] != 0:      # 0 = texto; 1 = imagen
                    continue
                texto = _limpiar(re.sub(r"-\n(?=[a-z])", "", bloque[4]))
                if not texto:
                    continue
                total += len(texto)
                if RE_CAPTION_TABLA.match(texto) or (len(texto) <= MAX_CARACTERES_CAPTION_SIN_PUNTO
                                                     and RE_CAPTION_TABLA_SIN_PUNTO.match(texto)):
                    if n not in paginas_tabla:
                        paginas_tabla.append(n)
                    captions.append(texto[:MAX_CARACTERES_NOMBRE_TABLA])
                    continue
                encabezado = RE_NUMERO_LINEA.sub("", texto)
                if (len(encabezado) <= 60 and RE_ENCABEZADO.match(encabezado)) or \
                        (len(encabezado) <= 90 and RE_ENCABEZADO_NUMERADO.match(encabezado)):
                    if actual or titulo:
                        secciones.append((titulo, actual))
                    titulo, actual = encabezado, []
                    if RE_CONCLUSION.search(encabezado):
                        paginas_conclusion += [n, n + 1]
                elif len(texto) >= 40:  # descarta números de página, pies y etiquetas sueltas
                    actual.append(texto)
        if actual or titulo:
            secciones.append((titulo, actual))
        if total < MIN_CARACTERES_POR_PAGINA * max(len(doc), 1):
            return None
        return secciones, paginas_tabla, captions, [n for n in paginas_conclusion if n <= len(doc)]
    finally:
        doc.close()


def estructura_hibrida(pdf_bytes, fuente_url=None, abstract_conocido=False):
    """Estructura del PDF gastando lo mínimo en Nemotron Parse (ver el docstring
    del módulo). Agrega a la estructura `paginas_parse`: cuántas páginas se
    enviaron. `abstract_conocido`: el paper ya tiene abstract en la base, así que
    no hace falta encontrarlo en el PDF.

    El lector local se acepta si halló la introducción y el abstract (el del PDF
    o el conocido). Si no, se envían las primeras y últimas páginas a Nemotron
    Parse: es el respaldo para tesis, revisiones y formatos que el lector local
    no entiende."""
    local = leer_local(pdf_bytes)
    if local:
        secciones, paginas_tabla, captions, _ = local
        abstract, penultimo, ultimo, conclusion = piezas_desde_secciones(secciones)
        if ultimo and (abstract or abstract_conocido):   # el lector local entendió la estructura
            tablas, enviadas = [], 0
            if paginas_tabla:
                paginas = paginas_tabla[:config.MAX_PAGINAS_TABLAS_PARSE]
                try:
                    tablas = secciones_y_tablas_desde_parse(analizar_paginas(pdf_bytes, paginas))[1]
                    enviadas = len(paginas)
                except ErrorLecturaPDF as exc:
                    if exc.fatal:
                        raise
                if not tablas:           # sin Parse (o sin tablas legibles): al menos los títulos
                    tablas = [{"nombre": c, "atributos": []} for c in captions]
            return {"fuente": "local+nemotron_parse" if enviadas else "local", "url": fuente_url,
                    "abstract": abstract, "intro_penultimo_parrafo": penultimo,
                    "intro_ultimo_parrafo": ultimo, "conclusion": conclusion,
                    "tablas": tablas, "paginas": None, "paginas_parse": enviadas}
    # Escaneado o con un formato que no se pudo leer en local: solo las páginas que hacen falta a Nemotron Parse
    paginas = analizar_paginas(pdf_bytes, _paginas_respaldo(pdf_bytes, local))
    estructura = estructura_desde_parse(paginas, fuente_url)
    estructura["paginas_parse"] = len(paginas)
    return estructura


# ------------------------------------------------------------- Europe PMC (gratis)

def _texto(nodo):
    return _limpiar(" ".join(nodo.itertext())) if nodo is not None else ""


def _tabla_xml(wrap, n):
    caption = wrap.find("caption")
    titulo = _texto(caption.find("title")) if caption is not None and caption.find("title") is not None else ""
    nombre = " ".join(x for x in (_texto(wrap.find("label")), titulo or _texto(caption)) if x) or f"Tabla {n}"
    tabla = wrap.find(".//table")
    atributos = []
    if tabla is not None:
        filas = tabla.findall("./thead/tr") or tabla.findall("./tbody/tr")[:1] or tabla.findall("./tr")[:1]
        columnas = {}
        for fila in filas:
            columna = 0
            for celda in fila:
                if celda.tag not in ("th", "td"):
                    continue
                texto = _texto(celda)
                for _ in range(int(celda.get("colspan") or 1)):
                    if texto:
                        columnas.setdefault(columna, []).append(texto)
                    columna += 1
        atributos = [" / ".join(dict.fromkeys(v)) for _, v in sorted(columnas.items())]
        atributos = [a for i, a in enumerate(atributos) if i == 0 or a != atributos[i - 1]]  # colspan repite el nombre
    return {"nombre": nombre[:MAX_CARACTERES_NOMBRE_TABLA], "atributos": atributos[:MAX_ATRIBUTOS_POR_TABLA]}


def estructura_europepmc(xml_bytes, url=None):
    """Mismas piezas que estructura_desde_parse, leídas del XML JATS de Europe PMC."""
    raiz = ET.fromstring(xml_bytes)
    abstract = None
    nodo_abs = raiz.find(".//front//abstract")
    if nodo_abs is not None:
        abstract = _recortar(" ".join(_texto(p) for p in nodo_abs.iter("p")) or _texto(nodo_abs)) or None
    cuerpo = raiz.find(".//body")
    secciones = []
    if cuerpo is not None:
        for sec in cuerpo.findall("./sec"):
            titulo = _texto(sec.find("title"))
            parrafos = [_texto(p) for p in sec.findall("./p")]
            secciones.append((titulo, [p for p in parrafos if p]))
            for sub in sec.findall("./sec"):    # subsecciones: heredan el flujo de la sección
                secciones.append((_texto(sub.find("title")), [_texto(p) for p in sub.findall("./p") if _texto(p)]))
    _, penultimo, ultimo, conclusion = piezas_desde_secciones(secciones)
    tablas = [_tabla_xml(w, n) for n, w in enumerate(raiz.iter("table-wrap"), 1)]
    return {"fuente": "europepmc", "url": url, "abstract": abstract, "intro_penultimo_parrafo": penultimo,
            "intro_ultimo_parrafo": ultimo, "conclusion": conclusion, "tablas": tablas, "paginas": None}


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return
    if not configurado():
        print("Falta NVIDIA_PARSE_API_KEY en .env")
        return
    with open(sys.argv[1], "rb") as f:
        estructura = estructura_hibrida(f.read())
    import json
    print(json.dumps(estructura, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
