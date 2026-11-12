"""Testeo general del proyecto: flujo completo de escritura contra el backend
real, con un proyecto de prueba que se borra al final. Verifica: página y
estáticos, API de proyectos, aclaración, generación de cadenas, búsqueda real
en los motores, procesamiento de PDFs (estructuras + fichas) y borrado.
Al terminar, output/proyectos debe quedar exactamente como estaba.
"""

import json
import subprocess
import sys
import time
import urllib.request

RAIZ = "/home/makkima16/Universidad/Proyecto_cafe/automatización"
PUERTO = 8099
BASE = f"http://127.0.0.1:{PUERTO}"


def api(metodo, ruta, cuerpo=None):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(BASE + ruta, data=datos, method=metodo,
                                 headers={"Content-Type": "application/json"} if datos else {})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def paso(nombre, ok, detalle=""):
    print(f"  {'OK ' if ok else 'FALLO'}  {nombre}  {detalle}")
    if not ok:
        raise SystemExit(f"FALLÓ: {nombre} {detalle}")


def main():
    import os
    antes = sorted(os.listdir(os.path.join(RAIZ, "busqueda/output/proyectos")))

    servidor = subprocess.Popen([f"{RAIZ}/venv/bin/python", "servidor.py", str(PUERTO)],
                                cwd=f"{RAIZ}/api", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(3)
        # 1. página y estáticos
        for ruta, tipo in [("/", "text/html"), ("/app.js", "text/javascript"),
                           ("/app.css", "text/css"), ("/nocturne.css", "text/css")]:
            with urllib.request.urlopen(BASE + ruta, timeout=10) as r:
                paso(f"GET {ruta}", r.status == 200 and tipo in r.headers["Content-Type"])

        # 2. lista de proyectos existentes (solo lectura)
        lista = api("GET", "/api/proyectos")
        paso("GET /api/proyectos", isinstance(lista, list) and len(lista) >= 1, f"{len(lista)} proyectos")

        # 3. crear proyecto de prueba y configurarlo
        p = api("POST", "/api/proyectos")
        pid = p["id"]
        p = api("PUT", f"/api/proyectos/{pid}", {"name": "limpieza test general",
                                                 "prompt": "Digestibilidad de proteínas de la leche con el modelo INFOGEST",
                                                 "num": 2, "idioma": "en"})
        paso("crear y configurar proyecto", p["name"] == "limpieza test general")

        # 4. aclaración (1 llamada a Nemotron)
        acl = api("POST", f"/api/proyectos/{pid}/aclarar",
                  {"prompt": "Digestibilidad de proteínas de la leche con el modelo INFOGEST", "historial": []})
        paso("aclaración", "tema_refinado" in acl, f"suficiente={acl.get('suficiente')}")

        # 5. generación de cadenas (1-2 llamadas a Nemotron)
        p = api("POST", f"/api/proyectos/{pid}/cadenas",
                {"prompt": "Digestibilidad de proteínas de la leche con el modelo INFOGEST",
                 "tema_refinado": acl.get("tema_refinado") or "", "historial": [], "num": 2, "idioma": "en"})
        paso("generar cadenas", len(p["queries"]) >= 1, f"{len(p['queries'])} cadenas; aviso={p.get('aviso')}")
        print("        cadenas:", [c[:60] for c in p["queries"]])

        # 6. búsqueda real: una sola cadena, tope 5 por motor
        cadena = p["queries"][0]
        api("PUT", f"/api/proyectos/{pid}", {"queries": [cadena], "max_resultados": 5, "min_year": 2015})
        api("POST", f"/api/proyectos/{pid}/buscar", {"queries": [cadena], "min_year": 2015, "max_resultados": 5})
        t0 = time.time()
        while True:
            time.sleep(2)
            p = api("GET", f"/api/proyectos/{pid}")
            if p["stage"] != "loading":
                break
            if time.time() - t0 > 300:
                paso("búsqueda a tiempo", False, "más de 5 min")
        paso("búsqueda real (3 motores)", len(p["papers"]) > 0,
             f"{len(p['papers'])} papers en {time.time()-t0:.0f}s; fuentes={p['fuentes']}")
        print("        ejemplos:", [x["title"][:50] for x in p["papers"][:3]])

        # 7. procesar 2 papers seleccionados con tope=1: el tope es editable y el
        #    backend debe pedir solo 1 (el techo lo sigue fijando MAX_PAPERS_PROCESAR_WEB)
        ids = [x["id"] for x in p["papers"][:2]]
        api("PUT", f"/api/proyectos/{pid}", {"seleccion": ids})
        api("POST", f"/api/proyectos/{pid}/procesar", {"alcance": "sel", "tope": 1})
        t0 = time.time()
        while True:
            time.sleep(3)
            p = api("GET", f"/api/proyectos/{pid}")
            pr = p["procesamiento"]
            if not pr["activo"]:
                break
            if time.time() - t0 > 420:
                paso("procesamiento a tiempo", False, f"más de 7 min: {pr}")
        paso("tope editable (pidió 1 de 2)", pr["total"] == 1,
             f"total={pr['total']}, tope={pr['tope']}")
        fichas = api("GET", f"/api/proyectos/{pid}/fichas")
        paso("procesamiento (estructuras+fichas)", len(fichas) >= 1,
             f"{len(fichas)} fichas en {time.time()-t0:.0f}s; conteos={pr.get('conteos')}")
        if fichas:
            f0 = fichas[0]
            print("        ficha 1:", json.dumps({k: f0.get(k) for k in ("estado", "resumen")},
                                                 ensure_ascii=False)[:220])

        # 8. CSV
        with urllib.request.urlopen(f"{BASE}/api/proyectos/{pid}/papers.csv", timeout=30) as r:
            csv = r.read().decode()
        paso("exportar CSV", "doi" in csv.splitlines()[0], f"{len(csv.splitlines())-1} filas")

        # 9. borrar el proyecto de prueba y verificar que output/proyectos quedó igual
        api("DELETE", f"/api/proyectos/{pid}")
        despues = sorted(os.listdir(os.path.join(RAIZ, "busqueda/output/proyectos")))
        paso("borrar proyecto de prueba", antes == despues,
             f"{len(antes)} archivos antes y después")

        print("\nTESTEO GENERAL COMPLETO: TODO OK")
    finally:
        servidor.terminate()
        try:
            servidor.wait(timeout=5)
        except subprocess.TimeoutExpired:
            servidor.kill()


if __name__ == "__main__":
    main()
