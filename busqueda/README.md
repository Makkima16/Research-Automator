# Búsqueda — IA en Alimentos (Selema / leche A2)

Automatiza la recolección de:

1. **Papers científicos** sobre leche A2, digestibilidad y formulación de lácteos, buscando en dos plataformas independientes:
   - [OpenAlex](https://openalex.org) (índice abierto con más de 270 millones de trabajos, sin necesidad de API key).
   - [Semantic Scholar](https://www.semanticscholar.org) (base del Allen Institute for AI; a veces encuentra papers o PDF que OpenAlex no tiene). **Desactivada temporalmente** (`config.USAR_SEMANTIC_SCHOLAR = False`) mientras se aprueba la solicitud de API key.
   - [Sci-Hub](https://sci-hub.ru), como cuarto motor (`fetch_scihub.py`). No busca por palabras clave: resuelve por DOI el PDF de los papers que los otros motores dejaron sin PDF accesible. **No es acceso abierto legal** (ver "Sci-Hub" más abajo); se apaga con `config.USAR_SCIHUB = False`.
2. **Datos de composición de lácteos**, vía [USDA FoodData Central](https://fdc.nal.usda.gov/) (API key gratuita e instantánea).

Esta carpeta es autónoma: no usa nada de `../procesamiento`. `main.py` no necesita un LLM; la interfaz web usa uno (Gemini) solo para generar las cadenas de búsqueda.

## 1. Archivos

| Archivo | Qué hace |
|---|---|
| `main.py` | Punto de entrada: busca en las dos plataformas, fusiona, rankea, revisa el acceso al PDF y guarda. |
| `config.py` | Búsquedas, año mínimo, API keys (USDA, Semantic Scholar) y rutas. |
| `fetch_papers.py` | Consulta OpenAlex y deduplica por DOI. |
| `fetch_semantic_scholar.py` | Consulta Semantic Scholar, fusiona sus resultados con los de OpenAlex, y revisa si el PDF de cada paper está bloqueado (buscando una copia alternativa cuando lo está). |
| `fetch_scopus.py` | Consulta Scopus (Elsevier) y deduplica por DOI. |
| `fetch_scihub.py` | Busca en Sci-Hub, por DOI, el PDF de los papers mejor rankeados que quedaron sin PDF accesible. |
| `rank_and_filter.py` | Puntúa los papers (citas, recencia, acceso abierto, palabras clave). |
| `fetch_usda.py` | Consulta USDA FoodData Central y deduce los atributos de cada producto. |
| `database.py` | Base SQLite con las tablas `papers` y `alimentos_usda`. |

## 2. Instalación

Desde la raíz del proyecto:

```bash
python -m venv venv
source venv/bin/activate      # en Windows: venv\Scripts\activate
pip install -r busqueda/requirements.txt   # solo la búsqueda (pandas, requests, LangChain para la interfaz web, y bs4 + scihub para Sci-Hub)
# o: pip install -r requirements.txt       # búsqueda + procesamiento
```

## 3. Configuración (`config.py`)

- **`CONTACT_EMAIL`**: pon tu correo. OpenAlex da respuestas más rápidas y estables a quienes se identifican con "mailto" ("polite pool"); no implica ningún registro.
- **`PAPER_QUERIES`**: la lista de búsquedas de papers, con sintaxis AND/OR/NOT (ver la sección "Sintaxis de las búsquedas" más abajo). Importa más la precisión de cada una que la cantidad.
- **`MIN_PUBLICATION_YEAR`**: año mínimo de publicación.
- **`MAX_RESULTS_PER_QUERY`**: cuántos papers se traen por cada cadena de búsqueda en cada plataforma (10 por defecto).
- **`PAUSA_ENTRE_PETICIONES_S`**: segundos entre una solicitud y la siguiente a las plataformas de papers (2 por defecto), para no saturar las APIs. La pausa es una sola para todas (función `esperar_turno()` del mismo `config.py`).
- **`USDA_QUERIES`**: términos de búsqueda de productos lácteos.
- **`USDA_API_KEY`**: consigue la tuya gratis en 1 minuto en https://fdc.nal.usda.gov/api-key-signup — el valor `DEMO_KEY` funciona, pero con un límite muy bajo (30 solicitudes/hora).
- **`USAR_SEMANTIC_SCHOLAR`**: `False` mientras se aprueba la solicitud de API key (ver más arriba). En `False`, el código de Semantic Scholar no se llama para nada (ni para buscar, ni para buscar PDF alternativo); solo queda la revisión del PDF que ya trae OpenAlex. Vuelve a poner `True` cuando llegue la key.
- **`SEMANTIC_SCHOLAR_API_KEY`**: opcional (solo aplica si `USAR_SEMANTIC_SCHOLAR = True`). Sin ella, Semantic Scholar funciona pero con una cuota baja y *compartida* entre todo el que use la API sin key (es normal ver avisos `429 Too Many Requests`: el script reintenta un par de veces y, si sigue saturado, sigue con lo demás en vez de fallar). Pide una gratis en https://www.semanticscholar.org/product/api#api-key-form si quieres una cuota propia.
- **`USAR_SCIHUB`**: `True` para buscar en Sci-Hub los papers sin PDF accesible; `False` para no usarlo.
- **`SCIHUB_MIRRORS`**: dominios de Sci-Hub, en el orden en que se prueban. Cambian con el tiempo: si uno deja de responder (el script lo avisa), quítalo o reemplázalo.
- **`MAX_PAPERS_SCIHUB`**: cuántos de los papers mejor rankeados sin PDF accesible se buscan en Sci-Hub (30 por defecto; hasta una solicitud por mirror por cada paper).
- **`MAX_PAPERS_VERIFICAR_PDF`**: cuántos de los papers mejor rankeados se revisan contra bloqueo de PDF (una o dos solicitudes HTTP por paper, así que con un número alto se vuelve lento).

## Sintaxis de las búsquedas (`PAPER_QUERIES`)

Cada búsqueda se escribe como en el buscador avanzado de ScienceDirect:

```python
'"A2 beta-casein" OR "A1 beta-casein" AND digestibility OR "gastrointestinal symptoms" AND NOT "infant formula"'
```

- **`"frase exacta"`**: las comillas buscan esa frase tal cual (con su raíz: "digestibility" también encuentra "digestible", "digestion"...). Sin comillas, cada palabra se busca por separado.
- **`AND`** separa los "grupos" de conceptos que un paper relevante debe tener **todos**. **`OR`** une alternativas/sinónimos dentro de un mismo grupo. Es decir, `A OR B AND C OR D` se traduce a `(A OR B) AND (C OR D)` — el AND manda, nunca queda como `A OR (B AND C) OR D`.
- Puedes poner paréntesis si te ayudan a leerlo (`(A OR B) AND (C OR D)`); el código los ignora al traducir la búsqueda, así que no cambian el resultado, son solo para ti.
- **`NOT`** excluye un término o una frase (no admite `OR` dentro del mismo `NOT`).

Esto se traduce internamente al filtro real y estable de OpenAlex (`title_and_abstract.search`, con coma=AND, `|`=OR, `!`=NOT — verificado contra la API en vivo). **No** se usa el parámetro `search=` simple de OpenAlex para esto, porque esa vía resultó ser inconsistente con AND/OR/NOT en pruebas reales (la misma búsqueda, corrida dos veces, a veces los respetaba y a veces no). Ver el docstring de `fetch_papers.py` para el detalle.

## 4. Ejecutar

```bash
cd busqueda
python main.py
```

Guarda todo en `output/selema.db`, una base SQLite con las tablas `papers` (título, año, citas, acceso abierto, link, abstract, `score` del ranking y las columnas de acceso al PDF de abajo) y `alimentos_usda` (productos lácteos con sus nutrientes clave y los atributos deducidos de la descripción). Es la que lee `../procesamiento`, que le agrega sus propias tablas. Ya no se generan `papers.csv`, `papers_ranked.csv` ni `usda_dairy.csv`: traían lo mismo que la base.

Volver a correr la búsqueda actualiza los papers y los alimentos sin tocar lo que haya guardado el procesamiento.

**Columnas sobre dónde se encontró cada paper y su PDF** (en la tabla `papers`):

| Columna | Qué indica |
|---|---|
| `motor_busqueda` | Qué plataforma(s) encontraron el paper: `openalex`, `semantic_scholar`, `scopus`, o varias (`openalex; semantic_scholar`). Se suma `scihub` si además está en Sci-Hub. |
| `motor_pdf` | Qué plataforma dio el enlace de PDF que terminó usándose (puede ser distinta a `motor_busqueda`, si la plataforma original tenía el PDF bloqueado): `openalex`, `semantic_scholar`, `scihub`, o `ninguno` si no se encontró ningún PDF. |
| `pdf_url` | Ese enlace. |
| `pdf_bloqueado` | `si` si se intentó acceder y el servidor lo rechazó (403/406, típico de editoriales que bloquean descargas automáticas), `no` si se pudo acceder, o vacío si no se revisó (ver `MAX_PAPERS_VERIFICAR_PDF`; los enlaces de Sci-Hub tampoco se revisan) o no hay ningún PDF. |

Solo se revisan los `MAX_PAPERS_VERIFICAR_PDF` papers mejor rankeados (no los ~1000+ de la lista completa): primero se prueba el enlace que ya se tenía; si está bloqueado o no existe, se busca una copia alternativa en Semantic Scholar por DOI y se prueba también. Esa revisión no evade ningún bloqueo de copyright: solo busca una copia de acceso abierto *legal*, en otro repositorio, que sí autorice la descarga.

### Sci-Hub

Después de esa revisión, los papers que siguen sin PDF accesible (sin enlace de acceso abierto, o con el enlace bloqueado) se buscan por DOI en Sci-Hub, hasta `MAX_PAPERS_SCIHUB`. Los que están quedan con `motor_pdf = scihub` y su enlace en `pdf_url`; los que no, quedan como estaban, para revisarlos a mano.

- Sci-Hub **no tiene búsqueda por palabras clave** (ni el sitio ni la librería `scihub`): por eso no recibe las cadenas de `PAPER_QUERIES` y no aporta papers nuevos, solo el PDF de los que ya encontraron los otros motores.
- Dejó de incorporar papers hacia 2021: los más recientes no están.
- La librería `scihub` de PyPI es de 2018 y su lista de mirrors está caída; `fetch_scihub.py` la adapta (ver su docstring).
- **A diferencia de las demás fuentes, Sci-Hub sí salta el bloqueo de las editoriales**: reparte copias sin su permiso, y usarlo puede infringir derechos de autor según el país y las normas de la institución. Con `USAR_SCIHUB = False` no se hace ninguna solicitud a Sci-Hub.

## Interfaz web (Buscador)

```bash
cd busqueda
python servidor.py        # abre http://127.0.0.1:8000 (otro puerto: python servidor.py 8080)
```

Es una página local para buscar papers de cualquier tema, por proyectos: escribes el tema en lenguaje natural, se generan cadenas de búsqueda (con la sintaxis de arriba), las editas, y se lanzan contra las plataformas activas en `config.py`. El resultado se rankea igual que en `main.py`, se puede filtrar, marcar papers ("Añadir a selección") y exportar a CSV.

- `servidor.py` (servidor y API, solo con la librería estándar), `generar_cadenas.py` (tema → cadenas) y `web/` (la página).
- Las cadenas las genera un modelo de Gemini (Google AI Studio) por medio de LangChain (`LLM_MODELO` en `config.py`; `LLM_API_KEY` en `../.env`).
- En la pantalla de cadenas se eligen el año mínimo y los resultados por cadena de ese proyecto (por defecto, los de `config.py`). Una búsqueda en curso se puede cancelar, y desde las cadenas se puede volver a los resultados de la última búsqueda.
- En los resultados, «★ Selección» muestra solo los papers marcados; con ese filtro activo, el CSV exporta solo la selección. Sin key, o si el LLM falla, se arman cadenas básicas con las palabras del tema y la página lo avisa.
- Cada proyecto se guarda en su propia base SQLite, `output/proyectos/<nombre_del_proyecto>.db` (ver `almacen.py`): tabla `papers` con los resultados (mismas columnas que en `selema.db`, más `seleccionado`) y tabla `proyecto` con el título, el prompt, las cadenas y los parámetros. El archivo se renombra cuando cambia el título del proyecto. La interfaz **no** escribe en `selema.db` y no revisa el acceso al PDF.

## 5. No repetir papers entre corridas

Antes de buscar, `main.py` lee los DOI que ya están guardados en `selema.db`. Al terminar la búsqueda, cuenta cuántos de los papers encontrados *no* estaban ya ahí ("nuevos") y lo informa en consola. La búsqueda se hace una sola vez: `MAX_RESULTS_PER_QUERY` papers por cada cadena en cada plataforma, sin ampliar el límite ni reintentar para llegar a una meta de papers nuevos.

Como ya no se amplía el límite, correr `python main.py` de nuevo con las mismas cadenas trae en general los mismos papers: para sumar material distinto hay que cambiar o agregar cadenas en `PAPER_QUERIES`. Solo se comparan los papers con DOI (los pocos que no tienen nunca se consideran "ya existentes").

Para borrar la base y partir de cero:

```bash
rm busqueda/output/selema.db                # Linux / Mac
Remove-Item busqueda\output\selema.db        # Windows (PowerShell)
```

Se vuelve a crear vacía la próxima vez que corras `python main.py`.

## 6. Notas

- Todas las APIs usadas son gratuitas para uso académico/no comercial.
- El script hace pausas cortas entre solicitudes para no saturar las APIs públicas; con las queries por defecto tarda varios minutos en total (la revisión de acceso al PDF agrega tiempo aparte, según `MAX_PAPERS_VERIFICAR_PDF`).
- Si una búsqueda falla (por ejemplo, por conexión, o Semantic Scholar saturado con `429`), el script avisa en consola y sigue con las demás en lugar de detenerse por completo.
- El USDA describe productos terminados, casi todos de EE. UU.: no tiene pH, temperatura de proceso ni región de origen.
- Unpaywall (otra plataforma de acceso abierto) ya no sirve para esto: retiró su búsqueda por palabras clave en septiembre de 2026 y ahora corre sobre la misma base de datos de OpenAlex, así que deja de ser una fuente independiente.
