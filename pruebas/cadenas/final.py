import os
import json, re, statistics, sys
from concurrent.futures import ThreadPoolExecutor
RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(RAIZ, "busqueda"))
import os
import generar_cadenas as g
S = os.path.dirname(os.path.abspath(__file__))
proy = [p for p in json.load(open(S + "/proyectos.json")) if p["queries"]]
casos0 = [((p["tema_refinado"] or p["prompt"]).strip(), p["num"] or 5, p["idioma"] or "en", p["archivo"][:-3]) for p in proy]
casos0 += [("Efecto de la pasteurización UHT en la leche entera y su vida útil", 5, "es", "extra_leche_es"),
          ("Harina de banano verde en panificación sin gluten", 5, "es", "extra_banano_es"),
          ("Tratamientos de cáncer de mama con inmunoterapia", 4, "es", "extra_cancer_es"),
          ("Robots colaborativos en logística y almacenes", 4, "ambos", "extra_cobots_ambos"),
          ("Digestibilidad de proteínas de la leche con el modelo INFOGEST", 4, "ambos", "extra_infogest_ambos")]
def forma(c):
    gs = re.split(r"\s+AND\s+", c); pos = [x for x in gs if not re.match(r"^NOT\s", x)]
    return [len(re.split(r"\s+OR\s+", x)) for x in pos], any(re.match(r"^NOT\s", x) for x in gs)
SIN_TILDE = re.compile(r"\b[a-zñ]+(?:cion|sion)(?:es)?\b|\b(?:robotica|automatica|mecanica|logistica|electronica|quimica|nutricion|dieta|ninos?)\b", re.I)
CON_TILDE = re.compile(r"[áéíóúñ]", re.I)
def una(c):
    tema, n, idioma, nombre = c
    try:
        cads, aviso, info = g.generar_con_info(tema, n, idioma)
        return nombre, idioma, n, cads, aviso, info
    except Exception as e:
        return nombre, idioma, n, [], f"ERROR {e}", {}
def main():
    casos = [c for c in casos0 if c[2] != "en"] if "--solo-no-en" in sys.argv else casos0
    with ThreadPoolExecutor(3) as ex: res = list(ex.map(una, casos))
    json.dump([{"nombre": r[0], "idioma": r[1], "cadenas": r[3], "aviso": r[4], "detalles": (r[5] or {}).get("detalles")} for r in res], open(S + "/resultados/final_res.json", "w"), ensure_ascii=False, indent=1)
    print(f'{"tema":38}{"idioma":7}{"cadenas":>8}{"alt/grupo":>10}{"1-solo":>7}{"NOT":>5}{"sin tilde":>10}{"con tilde":>10}  aviso')
    for nombre, idioma, n, cads, aviso, info in res:
        alts = [a for c in cads for a in forma(c)[0]]
        st = sum(len(SIN_TILDE.findall(c)) for c in cads); ct = sum(len(CON_TILDE.findall(c)) for c in cads)
        print(f'{nombre[:37]:38}{idioma:7}{len(cads):>5}/{n:<2}{(statistics.mean(alts) if alts else 0):>10.2f}{sum(a==1 for a in alts):>7}{sum(forma(c)[1] for c in cads):>5}{st:>10}{ct:>10}  {str(aviso or "")[:60]}')
    for nombre, idioma, n, cads, aviso, info in res:
        if idioma != "en":
            print("\n##", nombre, idioma)
            for c in cads: print("   ", c[:200])


if __name__ == "__main__":
    main()
