# Research Automator (SciToMarket Pipeline)

Research Automator es una herramienta automatizada de inteligencia y extracción de conocimiento. Está diseñada para realizar revisiones de literatura científica de manera autónoma, cruzar esos hallazgos con bases de datos de mercado (como la composición de productos en USDA) y normatividad, y presentar los resultados a través de un árbol de decisiones y una interfaz web interactiva.

El proyecto está estructurado en dos módulos principales: **Búsqueda** (recolección de datos) y **Procesamiento** (extracción y análisis con LLM).

---

## 1. Módulo de Búsqueda (`busqueda/`)

Automatiza la recolección de información científica y de mercado.

- **Papers científicos**: Busca de forma paralela en [OpenAlex](https://openalex.org), [Semantic Scholar](https://www.semanticscholar.org) y Scopus. Fusiona los resultados, los rankea y busca copias de acceso abierto.
- **Acceso a texto completo**: Integra [Sci-Hub](https://sci-hub.ru) (opcional y configurable) para resolver PDFs por DOI cuando las plataformas tradicionales tienen el archivo bloqueado.
- **Datos de mercado (Composición)**: Consulta bases de datos como USDA FoodData Central para extraer información nutricional y atributos de productos comerciales.
- **Autonomía**: Todo se guarda en una base de datos SQLite (`selema.db`). Este módulo funciona de forma independiente y no requiere de un LLM para la búsqueda básica (excepto en la interfaz web para generar cadenas de búsqueda).

### Instalación y Ejecución de la Búsqueda

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cd busqueda
python main.py
```

### Configuración de Búsqueda (`busqueda/config.py`)
- `PAPER_QUERIES`: Lista de búsquedas de papers con sintaxis booleana (AND, OR, NOT).
- `USDA_QUERIES`: Términos de búsqueda para productos comerciales.
- Se requieren API keys para USDA, Semantic Scholar y Scopus (todas tienen opciones gratuitas).
- `USAR_SCIHUB`: Activa o desactiva la descarga alternativa de PDFs.

### Interfaz Web de Búsqueda
Incluye un servidor local para crear proyectos de búsqueda mediante lenguaje natural:
```bash
cd busqueda
python servidor.py
```

---

## 2. Módulo de Procesamiento (`procesamiento/`)

Toma los papers recopilados por la búsqueda y extrae *insights* concretos usando Modelos de Lenguaje (LLMs). Cruza esta evidencia científica con el mercado y las normativas.

- **Descarga de Texto Completo**: Obtiene los métodos y resultados directamente de Europe PMC o del PDF.
- **Extracción con LLM**: Lee los fragmentos clave y extrae hallazgos estructurados (factor evaluado, variable de resultado, efecto). Compatible con Gemini, Ollama (local) y APIs compatibles con OpenAI.
- **Validación de Calidad**: Verifica que las citas existan realmente en el texto y que los rangos físicos (como pH o temperatura) tengan sentido. Protege contra alucinaciones del LLM.
- **Árbol de Decisiones**: Entrena un árbol de decisiones basado en la evidencia para guiar el desarrollo de productos.
- **Cruce de Mercado y Normatividad**: Evalúa si los procesos descritos en la ciencia cumplen con los límites legales (definidos en `normas.csv`) y los compara con productos reales del mercado.

### Ejecución del Procesamiento

1. Configura tu API key del LLM en el archivo `.env` de la raíz (ej. `GEMINI_API_KEY=tu_api_key`).
2. Asegúrate de haber ejecutado la búsqueda primero.

```bash
cd procesamiento
python fetch_fulltext.py         # Descarga texto completo
python extract_llm_insights.py   # Extrae hallazgos con el LLM
python build_dataset.py          # Arma la tabla y genera CSVs
python arbol_decision.py         # Entrena el árbol de decisiones
```

### Interfaz Gráfica de Análisis
Muestra el mapa de evidencia, comparaciones de mercado y normatividad.
```bash
cd procesamiento
streamlit run app.py
```

---

## Estructura del Proyecto

```text
├── busqueda/
│   ├── main.py                     # Ejecuta la recolección de datos
│   ├── config.py                   # Configuración de búsquedas y APIs
│   ├── fetch_*.py                  # Módulos para OpenAlex, Semantic Scholar, Sci-Hub, USDA
│   ├── servidor.py                 # Interfaz web de búsqueda
│   └── output/                     # Bases de datos SQLite y exportaciones CSV
├── procesamiento/
│   ├── app.py                      # Dashboard de análisis en Streamlit
│   ├── fetch_fulltext.py           # Descarga de PDFs y texto completo
│   ├── extract_llm_insights.py     # Extracción de datos con LLMs
│   ├── build_dataset.py            # Consolidación de datos
│   ├── arbol_decision.py           # Generación de reglas
│   ├── cruce_mercado.py            # Comparativa con productos comerciales
│   └── normas.csv                  # Límites regulatorios
├── .env                            # Variables de entorno y API keys
└── requirements.txt                # Dependencias del proyecto
```
