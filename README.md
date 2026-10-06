# IA en Alimentos (Selema / leche A2)

El proyecto está separado en dos carpetas:

| Carpeta | Qué hace | Estado |
|---|---|---|
| [`busqueda/`](busqueda/README.md) | Busca papers en OpenAlex y Semantic Scholar (indicando qué plataforma encontró cada uno y si su PDF está bloqueado) y composición de lácteos en USDA FoodData Central; rankea todo y lo guarda en `busqueda/output/` (CSV y `selema.db`). Es autónoma. | **En foco** |
| [`procesamiento/`](procesamiento/README.md) | Procesa los papers que trae la búsqueda: texto completo (PDF / Europe PMC), extracción con LLM, tabla del árbol de decisiones, cruce con el mercado, normatividad e interfaz gráfica. Usa la base y los módulos de `busqueda/`. | Aparte, se conserva |

```
├── busqueda/
│   ├── main.py                     # python main.py
│   ├── config.py                   # búsquedas, API keys (USDA, Semantic Scholar), rutas
│   ├── fetch_papers.py             # OpenAlex
│   ├── fetch_semantic_scholar.py   # Semantic Scholar + revisión de PDF bloqueado
│   ├── rank_and_filter.py          # puntuación de los papers
│   ├── fetch_usda.py               # USDA FoodData Central
│   ├── database.py                 # tablas papers y alimentos_usda
│   └── output/                     # selema.db y proyectos/<nombre>.db (interfaz web)
├── procesamiento/
│   ├── config_proc.py, database_proc.py
│   ├── fetch_fulltext.py, extract_llm_insights.py, esquema.py, validacion.py
│   ├── build_dataset.py, arbol_decision.py, cruce_mercado.py
│   ├── normas.csv, normatividad.py
│   ├── app.py               # streamlit run app.py
│   └── output/              # tabla_arbol.csv, evidencia_mercado.csv, ...
├── .env                     # API keys del LLM (solo las usa el procesamiento)
├── requirements.txt         # dependencias de todo el proyecto
└── venv/
```

## Uso rápido

```bash
source venv/bin/activate
cd busqueda && python main.py          # la búsqueda
```

El procesamiento se corre después, desde su carpeta (ver [`procesamiento/README.md`](procesamiento/README.md)).
