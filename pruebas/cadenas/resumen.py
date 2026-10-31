import json, re, statistics, sys, os
S = os.path.dirname(os.path.abspath(__file__))
res = json.load(open(S + "/resultados/banco_res.json"))
CONDS = ["historico", "gpt_viejo", "gpt_nuevo", "nvidia_viejo", "nvidia_nuevo"]
def forma(c):
    grupos = re.split(r"\s+AND\s+", c)
    pos = [g for g in grupos if not re.match(r"^NOT\s", g)]
    return len(pos), [len(re.split(r"\s+OR\s+", g)) for g in pos], any(re.match(r"^NOT\s", g) for g in grupos)
tab = {c: {"cad": 0, "grupos": [], "alts": [], "not": 0, "cero": 0, "angosta": 0, "ancha": 0, "hits": [], "prec": [], "err": 0} for c in CONDS}
por_tema = {}
for r in res:
    t = tab[r["cond"]]
    if r.get("error"): t["err"] += 1; print("ERROR", r["nombre"], r["cond"], r["error"])
    for e in r["evals"]:
        if e["hits"] is None: continue
        ng, alts, neg = forma(e["cadena"])
        t["cad"] += 1; t["grupos"].append(ng); t["alts"] += alts; t["not"] += neg
        t["cero"] += e["hits"] == 0; t["angosta"] += e["hits"] < 20; t["ancha"] += e["hits"] > 200000
        t["hits"].append(e["hits"])
        if e["rel"]: t["prec"].append(sum(e["rel"]) / len(e["rel"]))
        por_tema.setdefault(r["nombre"], {}).setdefault(r["cond"], []).append(sum(e["rel"]) / len(e["rel"]) if e["rel"] else None)
m = lambda l: f"{statistics.mean(l):.2f}" if l else "-"
print(f'{"condición":14}{"cadenas":>8}{"grupos":>8}{"alt/grupo":>10}{"con NOT":>9}{"0 hits":>8}{"<20":>6}{">200k":>7}{"mediana hits":>14}{"PRECISIÓN@8":>13}')
for c in CONDS:
    t = tab[c]
    print(f'{c:14}{t["cad"]:>8}{m(t["grupos"]):>8}{m(t["alts"]):>10}{t["not"]:>9}{t["cero"]:>8}{t["angosta"]:>6}{t["ancha"]:>7}{(statistics.median(t["hits"]) if t["hits"] else 0):>14.0f}{m(t["prec"]):>13}')
print("\nPrecisión@8 por tema:")
print(f'{"tema":38}' + "".join(f"{c:>14}" for c in CONDS))
for n, d in por_tema.items():
    print(f"{n[:37]:38}" + "".join(f'{m([x for x in d.get(c, []) if x is not None]):>14}' for c in CONDS))
