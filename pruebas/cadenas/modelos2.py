import json, sys, os
from concurrent.futures import ThreadPoolExecutor
S = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, S)
import modelos as m
if __name__ == "__main__":
    proy = [p for p in json.load(open(S + "/proyectos.json")) if p["queries"]]
    tareas = [(mod, modo, p) for mod in ("mistralai/mistral-large-4-1t-a52b", "openai/gpt-oss-20b") for modo in ("texto", "grupos") for p in proy]
    with ThreadPoolExecutor(2) as ex: res = list(ex.map(m.tarea, tareas))
    json.dump(res, open(S + "/resultados/modelos2_res.json", "w"), ensure_ascii=False, indent=1); print("LISTO", flush=True)
