import json, os, re, sys, time, statistics
from concurrent.futures import ThreadPoolExecutor
import os
import requests
RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(RAIZ, "busqueda"))
S = os.path.dirname(os.path.abspath(__file__))
import generar_cadenas as g, config

MODELOS = ["nvidia/nemotron-3.5-super-vl-120b-a12b", "nvidia/nemotron-3-super-120b-a12b", "nvidia/nemotron-3-ultra-550b-a55b",
           "deepseek-ai/deepseek-v4.1-flash", "moonshotai/kimi-k2.6", "mistralai/mistral-large-4-1t-a52b",
           "z-ai/glm-5.3-flash", "google/gemma-4-31b-it", "openai/gpt-oss-20b"]

def llamar(modelo, sistema, usuario, timeout=150):
    cuerpo = {"model": modelo, "max_tokens": 6000, "temperature": 0.2,
              "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}]}
    if "nemotron" in modelo: cuerpo["chat_template_kwargs"] = {"enable_thinking": False}
    for i in range(3):
        t = time.time()
        r = requests.post(config.NVIDIA_URL_CHAT, json=cuerpo, headers={"Authorization": f"Bearer {config.NVIDIA_API_KEY}"}, timeout=timeout)
        if r.status_code == 429: time.sleep(20); continue
        if not r.ok: raise RuntimeError(f"{r.status_code} {r.text[:120]}")
        txt = r.json()["choices"][0]["message"].get("content") or ""
        i0, i1 = txt.find("{"), txt.rfind("}")
        return json.loads(txt[i0:i1 + 1]), time.time() - t
    raise RuntimeError("429")

SUFIJO_TEXTO = '\n\nResponde SOLO con un objeto JSON de la forma {"cadenas": ["...", "..."], "intencion_consolidada": "...", "detalles": [{"cadena": "...", "intencion": "...", "alcance": "..."}]}.'

# Prompt de cadenas escritas (el formato viejo, que el producto ya no usa: hoy Nemotron
# recibe solo los términos de cada grupo y el código arma la sintaxis). Este script lo
# conserva para la comparación de formatos de la corrida del 2026-10-29 (resultados en
# resultados/modelos_res.json); el texto no se toca para que la comparación siga siendo
# comparable con esa corrida.
INSTRUCCIONES = """Eres un bibliotecario experto en búsquedas bibliográficas. A partir del tema \
del usuario escribe {n} cadenas de búsqueda distintas y complementarias (cada una cubre un ángulo \
diferente del tema) para bases académicas (OpenAlex, Semantic Scholar, Scopus). El tema puede \
venir en cualquier idioma: tradúcelo al idioma pedido para los términos.

Sintaxis obligatoria de cada cadena:
- Operadores AND, OR y NOT en mayúsculas, separados por espacios.
- "frase exacta" entre comillas dobles para los términos de más de una palabra.
- AND separa grupos de conceptos que el paper debe tener todos; OR une sinónimos dentro de un \
grupo. Es decir, A OR B AND C OR D significa (A OR B) AND (C OR D). No uses paréntesis.
- NOT solo admite un término o una frase, y va como último grupo: ... AND NOT "término".
- Cada grupo debe tener varias alternativas unidas con OR (sinónimos, variantes y términos \
relacionados): un grupo con un solo término vuelve la cadena tan restrictiva que no encuentra nada, \
porque el paper tendría que usar justo esas palabras. Las alternativas de un grupo deben ser distintas \
entre sí (nada de repetir el mismo término).
- Cada cadena cubre el núcleo del tema, no todos sus detalles a la vez: un dato de contexto (país, \
variedad, población, año) no es un grupo AND propio; ponlo solo en una o dos cadenas, o como una \
alternativa más.
- No uses NOT salvo que el usuario pida excluir algo de forma explícita. Nunca excluyas conceptos \
que pertenecen al tema (por ejemplo, otro tratamiento o variante del mismo proceso): se perderían \
papers pertinentes.
- {estructura}
- Sin filtros de fecha, de campo ni comodines.
- Los motores limitan el largo de la consulta (OpenAlex ~4 KB de URL, Scopus ~50 operadores): \
no pases de 12 alternativas OR en total por cadena y pon primero las más importantes de cada grupo.

Idioma de los términos: {idioma}."""
INSTR_GRUPOS = """Eres un bibliotecario experto en búsquedas bibliográficas. A partir del tema del usuario \
diseña {n} estrategias de búsqueda distintas y complementarias (cada una cubre un ángulo diferente del tema) \
para bases académicas (OpenAlex, Semantic Scholar, Scopus). El tema puede venir en cualquier idioma: tradúcelo \
al idioma pedido para los términos.

Cada estrategia es una lista de GRUPOS de conceptos. El paper debe contener al menos un término de CADA grupo. \
Dentro de un grupo van las alternativas del mismo concepto: sinónimos, variantes, abreviaturas y términos relacionados.
- {estructura}
- Las alternativas de un grupo son distintas entre sí y se escriben como las usaría un autor en el título o el \\
resumen, SIN comillas y SIN operadores (el sistema las agrega).
- Prefiere términos de 1 a 3 palabras. No pases de 12 alternativas en total por estrategia; las más importantes primero.
- Un dato de contexto (país, variedad, población) no es un grupo propio: ponlo solo en una o dos estrategias.
- "excluir": null, salvo que el usuario pida excluir algo de forma explícita; entonces un único término.

Idioma de los términos: {idioma}.

Responde SOLO con un objeto JSON: {{"estrategias": [{{"grupos": [["alternativa", "alternativa", "..."], ["..."]], "excluir": null, "intencion": "qué busca esta estrategia"}}], "intencion_consolidada": "resumen de 2-4 frases de la intención de búsqueda"}}."""

def armar(estrategia):
    def t(x):
        x = " ".join(str(x).replace('"', "").replace("(", "").replace(")", "").split())
        return f'"{x}"' if " " in x else x
    grupos = []
    for gr in estrategia.get("grupos", []):
        alts = list(dict.fromkeys(t(a) for a in gr if str(a).strip()))
        if alts: grupos.append(" OR ".join(alts))
    ex = estrategia.get("excluir")
    if ex and str(ex).strip(): grupos.append("NOT " + t(ex))
    return " AND ".join(grupos)

def forma(c):
    gs = re.split(r"\s+AND\s+", c); pos = [x for x in gs if not re.match(r"^NOT\s", x)]
    return len(pos), [len(re.split(r"\s+OR\s+", x)) for x in pos], any(re.match(r"^NOT\s", x) for x in gs)

def tarea(t):
    modelo, modo, p = t
    tema = (p["tema_refinado"] or p["prompt"]).strip(); n = p["num"] or 5; idioma = p["idioma"] or "en"
    en, est = g.IDIOMAS[idioma]
    try:
        if modo == "texto":
            j, dt = llamar(modelo, INSTRUCCIONES.format(n=n, idioma=en, estructura=est) + SUFIJO_TEXTO, f"Tema: {tema}")
            cads = g._limpiar(j.get("cadenas", []), n, idioma)          # igual que el pipeline actual
            brutas = [c for c in j.get("cadenas", []) if isinstance(c, str)]
        else:
            j, dt = llamar(modelo, INSTR_GRUPOS.format(n=n, idioma=en, estructura=est), f"Tema: {tema}")
            brutas = [armar(e) for e in j.get("estrategias", [])]
            cads = g._limpiar(brutas, n, idioma)
        return {"modelo": modelo, "modo": modo, "tema": p["archivo"][:-3], "idioma": idioma, "n": n, "cadenas": cads, "brutas": len(brutas), "dt": dt}
    except Exception as e:
        return {"modelo": modelo, "modo": modo, "tema": p["archivo"][:-3], "idioma": idioma, "n": n, "cadenas": [], "brutas": 0, "error": str(e)[:150], "dt": 0}

if __name__ == "__main__":
    proy = [p for p in json.load(open(S + "/proyectos.json")) if p["queries"]]
    tareas = [(m, modo, p) for m in MODELOS for modo in ("texto", "grupos") for p in proy]
    print(len(tareas), flush=True)
    with ThreadPoolExecutor(4) as ex: res = list(ex.map(tarea, tareas))
    json.dump(res, open(S + "/resultados/modelos_res.json", "w"), ensure_ascii=False, indent=1)
    print("LISTO", flush=True)
