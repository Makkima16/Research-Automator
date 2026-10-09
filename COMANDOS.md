Entorno (venv)

┌────────────────────────────────────┬────────────────────────────────────┐
│              Comando               │              Qué hace              │
├────────────────────────────────────┼────────────────────────────────────┤
│ python3 -m venv venv               │ Crea el entorno (solo la primera   │
│                                    │ vez; ya existe)                    │
├────────────────────────────────────┼────────────────────────────────────┤
│ source venv/bin/activate           │ Lo activa (hazlo en cada terminal  │
│                                    │ nueva)                             │
├────────────────────────────────────┼────────────────────────────────────┤
│ pip install -r requirements.txt    │ Instala todo: búsqueda +           │
│                                    │ procesamiento                      │
├────────────────────────────────────┼────────────────────────────────────┤
│ pip install -r                     │ Instala solo lo de la búsqueda     │
│ busqueda/requirements.txt          │                                    │
├────────────────────────────────────┼────────────────────────────────────┤
│ deactivate                         │ Sale del entorno                   │
└────────────────────────────────────┴────────────────────────────────────┘

Búsqueda

┌─────────────┬───────────────────────────────────────────────────────────┐
│   Comando   │                         Qué hace                          │
├─────────────┼───────────────────────────────────────────────────────────┤
│ cd busqueda │ Entra a la carpeta                                        │
├─────────────┼───────────────────────────────────────────────────────────┤
│ python      │ Busca papers (OpenAlex, Semantic Scholar, Scopus), los    │
│ main.py     │ rankea y guarda todo en busqueda/output/                  │
└─────────────┴───────────────────────────────────────────────────────────┘

Las búsquedas, el año mínimo y las keys se cambian en busqueda/config.py.

Procesamiento

Primero cd procesamiento. El orden normal es de arriba hacia abajo.

┌───────────────────────────────────────┬─────────────────────────────────┐
│                Comando                │            Qué hace             │
├───────────────────────────────────────┼─────────────────────────────────┤
│ python fetch_fulltext.py              │ Descarga el texto completo de   │
│                                       │ los papers de acceso abierto    │
├───────────────────────────────────────┼─────────────────────────────────┤
│ python fetch_fulltext.py --top 50     │ Lo mismo, solo para los 50      │
│                                       │ primeros del ranking            │
├───────────────────────────────────────┼─────────────────────────────────┤
│ python fetch_fulltext.py --forzar     │ Vuelve a descargar aunque ya    │
│                                       │ estén                           │
├───────────────────────────────────────┼─────────────────────────────────┤
│ python extract_llm_insights.py        │ El LLM extrae los hallazgos de  │
│                                       │ los 50 primeros papers          │
├───────────────────────────────────────┼─────────────────────────────────┤
│ python extract_llm_insights.py --top  │ Procesa más papers              │
│ 150                                   │                                 │
├───────────────────────────────────────┼─────────────────────────────────┤
│ python extract_llm_insights.py        │ Vuelve a extraer aunque estén   │
│ --forzar                              │ en caché                        │
├───────────────────────────────────────┼─────────────────────────────────┤
│                                       │ Arma la tabla del árbol y       │
│ python build_dataset.py               │ exporta los CSV a               │
│                                       │ procesamiento/output/           │
├───────────────────────────────────────┼─────────────────────────────────┤
│ python arbol_decision.py              │ Entrena el árbol y muestra sus  │
│                                       │ reglas                          │
├───────────────────────────────────────┼─────────────────────────────────┤
│ python arbol_decision.py --resultado  │ Árbol para una sola variable de │
│ sintomas_gastrointestinales           │  resultado                      │
├───────────────────────────────────────┼─────────────────────────────────┤
│ python arbol_decision.py              │ Limita el árbol (las dos        │
│ --solo-primaria --profundidad 3       │ opciones también sirven por     │
│                                       │ separado)                       │
├───────────────────────────────────────┼─────────────────────────────────┤
│ python arbol_decision.py              │ Excluye hallazgos obtenidos     │
│ --dentro-de-norma                     │ fuera de la norma               │
├───────────────────────────────────────┼─────────────────────────────────┤
│ python cruce_mercado.py --matriz      │ Cruza un perfil con los         │
│ leche_liquida --tipo_beta_caseina A2  │ productos del USDA              │
├───────────────────────────────────────┼─────────────────────────────────┤
│ python cruce_mercado.py --matriz      │                                 │
│ leche_liquida --tratamiento_termico   │ Otro perfil de ejemplo          │
│ uht                                   │                                 │
├───────────────────────────────────────┼─────────────────────────────────┤
│ python normatividad.py                │ Qué hallazgos y productos       │
│                                       │ cumplen o incumplen la norma    │
├───────────────────────────────────────┼─────────────────────────────────┤
│ python normatividad.py --matriz       │                                 │
│ leche_liquida --tratamiento_termico   │ Requisitos legales de un perfil │
│ uht                                   │                                 │
├───────────────────────────────────────┼─────────────────────────────────┤
│ python normatividad.py --matriz       │ Variante con --todas (no revisé │
│ leche_liquida --nivel_grasa entera    │  qué amplía exactamente)        │
│ --todas                               │                                 │
├───────────────────────────────────────┼─────────────────────────────────┤
│ streamlit run app.py                  │ Abre la interfaz gráfica en el  │
│                                       │ navegador                       │
└───────────────────────────────────────┴─────────────────────────────────┘

extract_llm_insights.py necesita la API key del LLM en el .env de la raíz (LLM_API_KEY o GEMINI_API_KEY, según LLM_PROVEEDOR en config_proc.py).

Secuencia completa

source venv/bin/activate
cd busqueda && python main.py
cd ../procesamiento
python fetch_fulltext.py
python extract_llm_insights.py
python build_dataset.py
python arbol_decision.py
streamlit run app.py