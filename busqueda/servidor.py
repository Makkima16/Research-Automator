"""
Interfaz web de la búsqueda ("Buscador"). Corre con:

    python servidor.py            # abre http://127.0.0.1:8000
    python servidor.py 8080       # otro puerto

Es un servidor local (solo escucha en 127.0.0.1) hecho con la librería
estándar: sirve la página de web/ y una API pequeña que usa los mismos
módulos de main.py (fetch_papers, fetch_semantic_scholar,
fetch_scopus, fetch_scihub, rank_and_filter).

Cada "proyecto" es un tema de investigación: se describe en lenguaje natural,
se generan cadenas de búsqueda (generar_cadenas.py), se editan y se lanzan
contra las plataformas activas en config.py. Cada proyecto se guarda en su
propia base SQLite, output/proyectos/<nombre_del_proyecto>.db (ver
almacen.py), y NO toca selema.db: esa base es la del caso Selema que lee
../procesamiento.
"""

import csv
import io
import json
import os
import re
import sqlite3
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import almacen
import config
import fetch_papers
import fetch_scihub
import fetch_scopus
import fetch_semantic_scholar
import generar_cadenas
import rank_and_filter

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
ESTATICOS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/nocturne.css": ("nocturne.css", "text/css; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}

NOMBRE_SIN_TITULO = "Proyecto sin título"
MAX_CADENAS_BUSQUEDA = 20
MAX_RESULTADOS_POR_CADENA = 500
COLUMNAS_CSV = ["openalex_id", "doi", "title", "year", "cited_by_count", "is_oa", "oa_url", "source",
                "abstract", "matched_query", "motor_busqueda", "motor_pdf", "pdf_url", "pagina_origen", "score", "seleccionado"]

_CANDADO = threading.RLock()
_PROYECTOS = {}


class ErrorAPI(Exception):
    def __init__(self, estado, mensaje):
        super().__init__(mensaje)
        self.estado = estado
        self.mensaje = mensaje


# ---------- proyectos en disco ----------

def _guardar(proyecto, con_papers=False):
    almacen.guardar(proyecto, con_papers)


def _migrar_json(nombre):
    """Pasa a .db un proyecto guardado como JSON por una versión anterior."""
    origen = os.path.join(config.PROYECTOS_DIR, nombre)
    with open(origen, encoding="utf-8") as f:
        proyecto = json.load(f)
    proyecto.setdefault("seleccion", [])
    proyecto.setdefault("papers", [])
    proyecto["archivo"] = almacen.nombre_archivo(proyecto["name"])
    _guardar(proyecto, con_papers=True)
    os.remove(origen)
    print(f"  {nombre} pasó a {proyecto['archivo']}")


def cargar_proyectos():
    os.makedirs(config.PROYECTOS_DIR, exist_ok=True)
    for nombre in sorted(os.listdir(config.PROYECTOS_DIR)):
        if nombre.endswith(".json"):
            try:
                _migrar_json(nombre)
            except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
                print(f"  [aviso] no se pudo convertir {nombre}: {exc}")
    for nombre in sorted(os.listdir(config.PROYECTOS_DIR)):
        if not nombre.endswith(".db"):
            continue
        try:
            proyecto = almacen.cargar(nombre)
        except (ValueError, sqlite3.Error) as exc:
            print(f"  [aviso] no se pudo leer {nombre}: {exc}")
            continue
        if proyecto is None:
            print(f"  [aviso] {nombre} no es la base de un proyecto; se ignora")
            continue
        if proyecto.get("stage") == "loading":
            # El servidor se cerró a mitad de una búsqueda: se vuelve a las cadenas
            proyecto["stage"] = "queries"
            proyecto["aviso"] = "La búsqueda anterior se interrumpió; vuelve a iniciarla."
            _guardar(proyecto)
        # Campos que no tenían los proyectos guardados por versiones anteriores
        proyecto.setdefault("min_year", config.MIN_PUBLICATION_YEAR)
        proyecto.setdefault("max_resultados", config.MAX_RESULTS_PER_QUERY)
        proyecto.setdefault("cadenas_usadas", len(proyecto["queries"]) if proyecto.get("papers") else 0)
        _PROYECTOS[proyecto["id"]] = proyecto


def _resumen(proyecto):
    return {k: v for k, v in proyecto.items() if k != "papers"}


def _obtener(pid):
    proyecto = _PROYECTOS.get(pid)
    if proyecto is None:
        raise ErrorAPI(404, "Ese proyecto no existe.")
    return proyecto


def crear_proyecto():
    proyecto = {
        "id": uuid.uuid4().hex[:12],
        "name": NOMBRE_SIN_TITULO,
        "stage": "empty",
        "creado": len(_PROYECTOS),
        "prompt": "",
        "num": 5,
        "idioma": "es",
        "queries": [],
        "min_year": config.MIN_PUBLICATION_YEAR,       # None = sin límite inferior
        "max_resultados": config.MAX_RESULTS_PER_QUERY,  # por cadena y por plataforma
        "busqueda": None,       # identificador de la búsqueda en curso (ver _buscar)
        "cadenas_usadas": 0,    # cuántas cadenas produjeron los papers guardados
        "aviso": None,
        "progreso": [],
        "fuentes": 0,
        "seleccion": [],
        "papers": [],
    }
    with _CANDADO:
        proyecto["creado"] = max((p["creado"] for p in _PROYECTOS.values()), default=-1) + 1
        proyecto["archivo"] = almacen.nombre_archivo(proyecto["name"])
        _PROYECTOS[proyecto["id"]] = proyecto
        _guardar(proyecto)
    return proyecto


def _cadenas_validas(valor):
    if not isinstance(valor, list) or not all(isinstance(c, str) for c in valor):
        raise ErrorAPI(400, "Las cadenas deben ser una lista de textos.")
    return valor[:MAX_CADENAS_BUSQUEDA]


def _parametros_busqueda(proyecto, datos):
    """Año mínimo y resultados por cadena, tal como llegan de la página."""
    if "min_year" in datos:
        try:
            proyecto["min_year"] = max(1900, min(int(datos["min_year"]), 2100))
        except (TypeError, ValueError):
            proyecto["min_year"] = None  # campo vacío: sin límite inferior
    if "max_resultados" in datos:
        try:
            proyecto["max_resultados"] = max(1, min(int(datos["max_resultados"]), MAX_RESULTADOS_POR_CADENA))
        except (TypeError, ValueError):
            pass


def actualizar_proyecto(pid, datos):
    with _CANDADO:
        proyecto = _obtener(pid)
        if "name" in datos:
            nombre = " ".join(str(datos["name"]).split())[:80]
            if not nombre:
                raise ErrorAPI(400, "El título no puede quedar vacío.")
            # Un título puesto a mano ya no se reemplaza al generar cadenas
            proyecto.update(name=nombre, nombre_manual=True)
            almacen.renombrar(proyecto)  # el .db se llama como el proyecto
            if set(datos) == {"name"}:  # renombrar sí se permite durante una búsqueda
                _guardar(proyecto)
                return dict(proyecto)
        if proyecto["stage"] == "loading":
            raise ErrorAPI(409, "Hay una búsqueda en curso en este proyecto.")
        if "prompt" in datos:
            proyecto["prompt"] = str(datos["prompt"])[:4000]
        if "num" in datos:
            try:
                proyecto["num"] = max(1, min(int(datos["num"]), generar_cadenas.MAX_CADENAS))
            except (TypeError, ValueError):
                pass
        if datos.get("idioma") in generar_cadenas.IDIOMAS:
            proyecto["idioma"] = datos["idioma"]
        if "queries" in datos:
            proyecto["queries"] = _cadenas_validas(datos["queries"])
        if "seleccion" in datos and isinstance(datos["seleccion"], list):
            proyecto["seleccion"] = [str(s) for s in datos["seleccion"]]
            almacen.guardar_seleccion(proyecto)
        _parametros_busqueda(proyecto, datos)
        if datos.get("stage") in ("empty", "queries"):
            proyecto["stage"] = datos["stage"]
            proyecto["aviso"] = None
        if datos.get("stage") == "results":  # volver a los resultados de la última búsqueda
            if not proyecto["papers"]:
                raise ErrorAPI(400, "Este proyecto todavía no tiene resultados.")
            proyecto["stage"] = "results"
            proyecto["aviso"] = None
        if datos.get("reiniciar"):
            proyecto.update(stage="empty", prompt="", queries=[], papers=[], seleccion=[],
                            progreso=[], fuentes=0, cadenas_usadas=0, aviso=None)
        _guardar(proyecto, con_papers=bool(datos.get("reiniciar")))
        return dict(proyecto)


def borrar_proyecto(pid):
    """Borra el proyecto y su base. Si tiene una búsqueda en curso, el hilo
    termina sus solicitudes y descarta el resultado (ver _marcar y _terminar)."""
    with _CANDADO:
        almacen.borrar(_obtener(pid))
        del _PROYECTOS[pid]


def generar(pid, datos):
    tema = str(datos.get("prompt") or "").strip()
    if not tema:
        raise ErrorAPI(400, "Escribe primero el tema que quieres investigar.")
    actualizar_proyecto(pid, {k: datos[k] for k in ("prompt", "num", "idioma") if k in datos})
    with _CANDADO:
        proyecto = _obtener(pid)
        num, idioma = proyecto["num"], proyecto["idioma"]
    cadenas, aviso = generar_cadenas.generar(tema, num, idioma)  # lento: fuera del candado
    with _CANDADO:
        proyecto = _obtener(pid)
        proyecto.update(stage="queries", queries=cadenas, aviso=aviso)
        if not proyecto.get("nombre_manual"):
            proyecto["name"] = tema if len(tema) <= 36 else tema[:34] + "…"
            almacen.renombrar(proyecto)
        _guardar(proyecto)
        return dict(proyecto)


# ---------- búsqueda ----------

def _fuentes():
    """(nombre, activa, función(cadenas, año mínimo, límite)) de cada plataforma, según config.py."""
    return [
        ("OpenAlex", True, lambda qs, anio, lim: fetch_papers.fetch_all(
            qs, config.CONTACT_EMAIL, anio, lim)),
        ("Semantic Scholar", config.USAR_SEMANTIC_SCHOLAR, lambda qs, anio, lim: fetch_semantic_scholar.fetch_all(
            qs, config.SEMANTIC_SCHOLAR_API_KEY, anio, lim)),
        ("Scopus", config.USAR_SCOPUS and bool(config.SCOPUS_API_KEY),
         lambda qs, anio, lim: fetch_scopus.fetch_all(
             qs, config.SCOPUS_API_KEY, anio, lim)),
    ]


class Cancelada(Exception):
    """La búsqueda se canceló (o se borró el proyecto) mientras corría."""


def _vigente(pid, token):
    """True si `token` sigue siendo la búsqueda en curso del proyecto. Cancelar
    o borrar el proyecto la invalida: el hilo lo nota y deja de buscar."""
    proyecto = _PROYECTOS.get(pid)
    return proyecto is not None and proyecto.get("busqueda") == token


def _unir(vistos, filas, cadena):
    """Suma a `vistos` los resultados de una cadena, sin repetir papers (igual
    que fetch_all de cada plataforma cuando recibe varias cadenas)."""
    for fila in filas:
        clave = fila.get("doi") or fila.get("openalex_id")
        if not clave:
            continue
        if clave in vistos:
            if cadena not in vistos[clave]["matched_query"]:
                vistos[clave]["matched_query"] += f"; {cadena}"
        else:
            vistos[clave] = fila


def _palabras_clave(cadenas):
    """Términos de las cadenas (frases entre comillas enteras), sin operadores."""
    claves = []
    for cadena in cadenas:
        for frase, palabra in re.findall(r'"([^"]+)"|([^\s()"]+)', cadena):
            termino = frase or palabra
            if termino not in ("AND", "OR", "NOT") and termino not in claves:
                claves.append(termino)
    return claves


# Orden en que se consultan las plataformas: al fusionar, los datos de un paper
# (incluido su enlace de acceso abierto) quedan de la primera que lo encontró
ORDEN_MOTORES = ["openalex", "semantic_scholar", "scopus"]


def _marcar_origen_pdf(papers):
    """Llena motor_pdf y pdf_url: de qué plataforma salió el enlace al texto
    del paper ("ninguno" si ninguna dio uno). main.py lo hace al revisar el
    acceso al PDF; aquí no se revisa, solo se anota el origen."""
    for paper in papers:
        if paper.get("motor_pdf"):
            continue
        if not paper.get("oa_url"):
            paper["motor_pdf"], paper["pdf_url"] = "ninguno", None
            continue
        motores = (paper.get("motor_busqueda") or "").split("; ")
        paper["motor_pdf"] = next((m for m in ORDEN_MOTORES if m in motores), motores[0])
        paper["pdf_url"] = paper["oa_url"]


def _marcar(pid, token, indice, estado, texto=None):
    with _CANDADO:
        if not _vigente(pid, token):
            raise Cancelada()
        paso = _PROYECTOS[pid]["progreso"][indice]
        paso["estado"] = estado
        if texto:
            paso["texto"] = texto
        _guardar(_PROYECTOS[pid])


def _terminar(pid, token, **cambios):
    with _CANDADO:
        if not _vigente(pid, token):
            return
        _PROYECTOS[pid].update(cambios, busqueda=None)
        _guardar(_PROYECTOS[pid], con_papers="papers" in cambios)


def _buscar(pid, token, cadenas, min_year, max_resultados):
    """Corre en un hilo aparte; la página consulta el avance en `progreso`.
    Busca cadena por cadena para poder mostrar el avance y parar pronto si
    cancelan la búsqueda."""
    fuentes = _fuentes()
    try:
        papers, con_resultados = [], 0
        for i, (nombre, activa, buscar) in enumerate(fuentes, start=1):
            if not activa:
                _marcar(pid, token, i, "done", f"{nombre} — desactivada en config.py")
                continue
            print(f"== Buscando en {nombre} ==")
            vistos = {}
            for n, cadena in enumerate(cadenas, start=1):
                _marcar(pid, token, i, "active", f"{nombre} — cadena {n} de {len(cadenas)}…")
                _unir(vistos, buscar([cadena], min_year, max_resultados), cadena)
            encontrados = list(vistos.values())
            _marcar(pid, token, i, "done", f"{nombre} — {len(encontrados)} resultados")
            if encontrados:
                con_resultados += 1
            # La primera fuente con resultados queda como base (fusionar_por_doi
            # descartaría sus papers sin DOI si entraran como secundarios)
            papers = fetch_semantic_scholar.fusionar_por_doi(papers, encontrados, nombre) if papers else encontrados

        ultimo = len(fuentes) + 1
        _marcar(pid, token, ultimo, "active")
        if not papers:
            _terminar(pid, token, stage="queries", aviso="Ninguna plataforma devolvió papers para estas cadenas. "
                      "Revisa la sintaxis (AND / OR / NOT) o prueba con términos más generales; si las "
                      "plataformas están saturadas (429), espera un momento y vuelve a intentar.")
            return
        ranked = rank_and_filter.rank_papers(papers, _palabras_clave(cadenas))
        for n, paper in enumerate(ranked):
            paper["id"] = paper.get("doi") or paper.get("openalex_id") or f"sin-id-{n}"
        _marcar_origen_pdf(ranked)
        _marcar(pid, token, ultimo, "done", f"Deduplicación por DOI — {len(ranked)} papers únicos")
        # Sci-Hub no busca por cadenas: resuelve por DOI los papers sin PDF abierto
        if config.USAR_SCIHUB:
            en_scihub = fetch_scihub.completar(
                ranked, config.SCIHUB_MIRRORS, config.MAX_PAPERS_SCIHUB,
                lambda n, total: _marcar(pid, token, ultimo + 1, "active", f"Sci-Hub — paper {n} de {total}…"))
            _marcar(pid, token, ultimo + 1, "done", f"Sci-Hub — {en_scihub} PDF encontrados")
            if en_scihub:
                con_resultados += 1
        else:
            _marcar(pid, token, ultimo + 1, "done", "Sci-Hub — desactivado en config.py")
        _terminar(pid, token, stage="results", papers=ranked, fuentes=con_resultados, seleccion=[],
                  cadenas_usadas=len(cadenas), aviso=None)
    except Cancelada:
        print("  Búsqueda cancelada.")
    except Exception as exc:  # un fallo inesperado no debe dejar el proyecto en "loading" para siempre
        print(f"  [error] la búsqueda falló: {type(exc).__name__}: {exc}")
        _terminar(pid, token, stage="queries", aviso=f"La búsqueda falló ({type(exc).__name__}: {exc}).")


def iniciar_busqueda(pid, datos):
    with _CANDADO:
        proyecto = _obtener(pid)
        if proyecto["stage"] == "loading":
            raise ErrorAPI(409, "Ya hay una búsqueda en curso en este proyecto.")
        cadenas = [c.strip() for c in _cadenas_validas(datos.get("queries", proyecto["queries"])) if c.strip()]
        if not cadenas:
            raise ErrorAPI(400, "Agrega al menos una cadena de búsqueda.")
        _parametros_busqueda(proyecto, datos)
        token = uuid.uuid4().hex
        pasos = ["Cadenas enviadas al servicio"] + [nombre for nombre, _, _ in _fuentes()] + ["Deduplicación por DOI", "Sci-Hub"]
        proyecto.update(
            stage="loading", queries=cadenas, aviso=None, busqueda=token,
            progreso=[{"texto": t, "estado": "done" if i == 0 else "pending"} for i, t in enumerate(pasos)],
        )
        _guardar(proyecto)
        respuesta = dict(proyecto)
    threading.Thread(target=_buscar, daemon=True,
                     args=(pid, token, cadenas, proyecto["min_year"], proyecto["max_resultados"])).start()
    return respuesta


def cancelar_busqueda(pid):
    """Vuelve a las cadenas de inmediato; el hilo de la búsqueda termina la
    solicitud que tenga en curso y descarta lo que llevaba (ver _vigente). Los
    resultados de la búsqueda anterior, si había, se conservan."""
    with _CANDADO:
        proyecto = _obtener(pid)
        if proyecto["stage"] == "loading":
            proyecto.update(stage="queries", busqueda=None, aviso="Búsqueda cancelada.")
            _guardar(proyecto)
        return dict(proyecto)


def _pagina_origen(paper):
    """Dominio de la página donde está el texto del paper (p. ej. mdpi.com):
    los motores de búsqueda solo lo indexan. '' si no trae enlace."""
    host = urlparse(paper.get("pdf_url") or paper.get("oa_url") or "").hostname or ""
    return host.removeprefix("www.")


def exportar_csv(pid, solo_seleccion=False):
    """Devuelve (nombre de archivo, contenido) del CSV de resultados."""
    with _CANDADO:
        proyecto = _obtener(pid)
        seleccion = set(proyecto["seleccion"])
        salida = io.StringIO()
        escritor = csv.DictWriter(salida, fieldnames=COLUMNAS_CSV, extrasaction="ignore")
        escritor.writeheader()
        for paper in proyecto["papers"]:
            if solo_seleccion and paper.get("id") not in seleccion:
                continue
            escritor.writerow({**paper, "pagina_origen": _pagina_origen(paper), "seleccionado": "si" if paper.get("id") in seleccion else ""})
        nombre = proyecto["archivo"][:-3] + ("_seleccion" if solo_seleccion else "") + ".csv"
        return nombre, salida.getvalue()


# ---------- HTTP ----------

RUTA_PROYECTO = re.compile(r"^/api/proyectos/([0-9a-f]{1,32})(/cadenas|/buscar|/cancelar|/papers\.csv)?$")


class Manejador(BaseHTTPRequestHandler):
    def log_message(self, formato, *args):
        pass  # la página consulta el avance cada segundo: no llenar la consola

    def _responder(self, estado, cuerpo, tipo, extra=None):
        self.send_response(estado)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        for clave, valor in (extra or {}).items():
            self.send_header(clave, valor)
        self.end_headers()
        self.wfile.write(cuerpo)

    def _json(self, datos, estado=200):
        self._responder(estado, json.dumps(datos, ensure_ascii=False).encode("utf-8"),
                        "application/json; charset=utf-8")

    def _cuerpo(self):
        largo = int(self.headers.get("Content-Length") or 0)
        if not largo:
            return {}
        try:
            datos = json.loads(self.rfile.read(largo))
        except ValueError:
            raise ErrorAPI(400, "El cuerpo de la solicitud no es JSON válido.")
        if not isinstance(datos, dict):
            raise ErrorAPI(400, "El cuerpo de la solicitud debe ser un objeto JSON.")
        return datos

    def _atender(self, metodo):
        ruta = self.path.split("?", 1)[0]
        try:
            if metodo == "GET" and ruta in ESTATICOS:
                archivo, tipo = ESTATICOS[ruta]
                with open(os.path.join(WEB_DIR, archivo), "rb") as f:
                    return self._responder(200, f.read(), tipo)
            if ruta == "/api/proyectos":
                if metodo == "GET":
                    with _CANDADO:
                        lista = sorted(_PROYECTOS.values(), key=lambda p: p["creado"])
                        return self._json([_resumen(p) for p in lista])
                if metodo == "POST":
                    return self._json(crear_proyecto(), 201)
            coincide = RUTA_PROYECTO.match(ruta)
            if coincide:
                pid, accion = coincide.groups()
                if metodo == "GET" and accion is None:
                    with _CANDADO:
                        return self._json(_obtener(pid))
                if metodo == "GET" and accion == "/papers.csv":
                    nombre, contenido = exportar_csv(pid, "seleccion=1" in self.path)
                    return self._responder(200, contenido.encode("utf-8"), "text/csv; charset=utf-8",
                                           {"Content-Disposition": f'attachment; filename="{nombre}"'})
                if metodo == "DELETE" and accion is None:
                    borrar_proyecto(pid)
                    return self._json({"ok": True})
                if metodo == "PUT" and accion is None:
                    return self._json(actualizar_proyecto(pid, self._cuerpo()))
                if metodo == "POST" and accion == "/cadenas":
                    return self._json(generar(pid, self._cuerpo()))
                if metodo == "POST" and accion == "/cancelar":
                    return self._json(cancelar_busqueda(pid))
                if metodo == "POST" and accion == "/buscar":
                    return self._json(iniciar_busqueda(pid, self._cuerpo()))
            raise ErrorAPI(404, "No existe esa ruta.")
        except ErrorAPI as exc:
            self._json({"error": exc.mensaje}, exc.estado)
        except Exception as exc:
            print(f"  [error] {metodo} {ruta}: {type(exc).__name__}: {exc}")
            self._json({"error": f"Error interno: {type(exc).__name__}: {exc}"}, 500)

    def do_GET(self):
        self._atender("GET")

    def do_POST(self):
        self._atender("POST")

    def do_PUT(self):
        self._atender("PUT")

    def do_DELETE(self):
        self._atender("DELETE")


def main():
    puerto = int(sys.argv[1]) if len(sys.argv) > 1 else config.WEB_PUERTO
    cargar_proyectos()
    servidor = ThreadingHTTPServer(("127.0.0.1", puerto), Manejador)
    print(f"Buscador listo en http://127.0.0.1:{puerto}  ({len(_PROYECTOS)} proyectos guardados). Ctrl+C para salir.")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido.")


if __name__ == "__main__":
    main()
