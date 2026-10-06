# Procesamiento de los papers — IA en Alimentos (Selema / leche A2)

Toma los papers que trae la búsqueda (`../busqueda`) y los convierte en una tabla para el árbol de decisiones: descarga el texto completo de los de acceso abierto, extrae hallazgos con un LLM, los valida, los cruza con el mercado (USDA) y con la normatividad, y los muestra en una interfaz.

> Por ahora el trabajo se concentra en la búsqueda. Esta carpeta se conserva completa y funcional, pero aparte.

**Depende de la búsqueda:** usa su base de datos (`../busqueda/output/selema.db`, donde agrega sus propias tablas) y sus módulos `config`, `database` y `fetch_usda`. `config_proc.py` agrega `../busqueda` a la ruta de importación, por eso los scripts lo importan primero. La búsqueda, en cambio, no depende de esta carpeta.

## 1. Archivos

| Archivo | Qué hace |
|---|---|
| `config_proc.py` | Configuración: proveedor y modelo del LLM, tamaños de lote, normatividad, rutas. |
| `database_proc.py` | Tablas del procesamiento (`textos_completos`, `extracciones`, `observaciones`, `normas`, vista `evidencia_mercado`). |
| `fetch_fulltext.py` | Descarga el texto completo (Europe PMC o PDF) y selecciona los fragmentos para el LLM. |
| `extract_llm_insights.py` | El LLM extrae las observaciones de cada paper. |
| `esquema.py`, `validacion.py` | Esquema cerrado de una observación y control de calidad (citas, rangos). |
| `build_dataset.py` | Arma la tabla del árbol y exporta los CSV a `output/`. |
| `arbol_decision.py` | Entrena el árbol y muestra sus reglas. |
| `cruce_mercado.py` | Cruza una rama del árbol con los productos del USDA. |
| `normas.csv`, `normatividad.py` | Límites legales y su evaluación. |
| `app.py` | Interfaz gráfica (Streamlit). |

Las API keys del LLM van en el `.env` de la raíz del proyecto.

## 2. De papers a tabla para el árbol de decisiones

```bash
# 0. Pon tu API key de Gemini (gratis en https://aistudio.google.com/apikey) en ../.env:
#    GEMINI_API_KEY=tu_api_key
# 1. Corre antes la búsqueda (python ../busqueda/main.py): llena ../busqueda/output/selema.db
cd procesamiento
python fetch_fulltext.py         # texto completo de los papers de acceso abierto (métodos, resultados)
python extract_llm_insights.py   # el LLM extrae observaciones de los top 50 (abstract + fragmentos del texto completo)
python build_dataset.py          # guarda la tabla del árbol en selema.db (+ CSV) y muestra el reporte de calidad
python arbol_decision.py         # entrena el árbol y muestra sus reglas
```

**Qué datos tiene cada fuente:**

| Tabla | Fuente | Columnas |
|---|---|---|
| `observaciones` → `tabla_arbol.csv` | Papers + Gemini | Origen: especie, raza, sistema de alimentación (pastoreo/estabulado), región y país. Leche: tipo de beta-caseína, proteína, grasa, lactosa, sólidos totales, células somáticas. Proceso: tratamiento térmico, temperatura, tiempo, pH, homogeneización, deslactosado, probióticos/cepas, vida útil. Objetivo: `efecto` sobre la variable de resultado. |
| `alimentos_usda` | USDA FoodData Central | Por 100 g: energía, proteína, grasa, grasa saturada, carbohidratos, azúcares, lactosa, agua, colesterol, calcio, fósforo, potasio, sodio, magnesio, vitaminas D, A y B12. Deducidos de la descripción/ingredientes: tipo de producto, A2, raza (si la menciona), tratamiento térmico, nivel de grasa, homogeneizada, ultrafiltrada, sin lactosa, orgánica, pastoreo, probióticos. |

El USDA describe productos terminados, casi todos de EE. UU.: **no tiene pH, temperatura de proceso ni región de origen**. Esos datos solo salen de los papers.

**Qué LLM usar (`LLM_PROVEEDOR` en `config_proc.py`):**

| Proveedor | Costo | Límite | Velocidad |
|---|---|---|---|
| `gemini` | Gratis | ~20 solicitudes/día por modelo, con saturaciones frecuentes | Rápido |
| `ollama` | Gratis, corre en tu PC | Ninguno | Lento en CPU (minutos por paper) |
| `openai` (Groq, OpenRouter, Mistral…) | Planes gratuitos o de pago | Según el servicio | Rápido |

Para Ollama: instálalo desde https://ollama.com, corre `ollama pull qwen2.5:7b` y pon `LLM_PROVEEDOR = "ollama"`. Para una API compatible con OpenAI: ajusta `OPENAI_BASE_URL` y `OPENAI_MODELO`, y pon la key en `../.env` como `LLM_API_KEY=...`.

**Cómo se garantiza la calidad de la tabla:**

- **Dirección fija de cada comparación**: cada hallazgo tiene `factor_evaluado` (lo que se estudia), `referencia` (el control) y `categoria_factor` (beta-caseína, tratamiento térmico, alimentación…). El prompt fija la dirección (por ejemplo, el proceso más intenso siempre es el evaluado: "UHT vs cruda", nunca al revés; A2 siempre frente a A1/convencional), así que "mejora" y "empeora" significan lo mismo en todas las filas. Las características de la fila describen al grupo evaluado.

- **Esquema cerrado** (`esquema.py`): cada fila es una *observación* (comparación + variable de resultado) con categorías fijas (tipo de beta-caseína, matriz, tratamiento térmico, población…). La columna objetivo es `efecto`: `mejora`, `sin_diferencia`, `empeora` o `mixto`.
- **Citas verificadas** (`validacion.py`): cada fila trae la frase del abstract que la respalda. Si esa frase no está realmente en el texto, la fila se descarta (protege contra alucinaciones).
- **Rangos físicos**: pH fuera de 0–14, temperaturas imposibles, etc. se borran y se anotan en `problemas`.
- **Deduplicación**: la misma observación repetida en un paper no cuenta doble.
- **Revisión humana**: las filas descartadas quedan en `output/observaciones_revisar.csv`. Abre `../busqueda/output/selema.db` con [DB Browser for SQLite](https://sqlitebrowser.org) y pon `aprobada` o `rechazada` en `observaciones.revision_humana`; `build_dataset.py` respeta esa decisión.
- **Caché**: si un abstract no cambió, no se vuelve a llamar al LLM (usa `--forzar` para repetir).

**Interfaz gráfica:** `streamlit run app.py` abre en el navegador una app organizada por preguntas:
- **Qué dice la ciencia**: mapa de evidencia (tipo de factor × variable medida). El color indica si la mayoría de los hallazgos dice que mejora o empeora, y el número cuántos hay; al hacer clic en una celda aparecen sus hallazgos con cita y DOI. Tiene filtros en cascada que solo muestran opciones con datos.
- **Comparar en el mercado**: grupo A contra grupo B de productos del USDA (por ejemplo, A2 vs convencional), con el mismo nivel de grasa, solo productos comparables, una conclusión en texto e indicación de si cada diferencia es consistente (prueba de Mann-Whitney) o podría ser azar.
- **Árbol de decisiones**: reglas en lenguaje claro, con controles de profundidad y variable medida.
- **Explorar datos**: tabla de productos, completitud de los hallazgos y descarga de la tabla del árbol.

La tabla del árbol vive en la base (`tabla_arbol` en `selema.db`); `tabla_arbol.csv` es solo una exportación.

**Del árbol al mercado (`cruce_mercado.py`):** los papers y el USDA no comparten una llave, pero sí características (tipo de beta-caseína, tratamiento térmico, especie, raza, pastoreo, sin lactosa, tipo de producto). Con las condiciones de una rama del árbol, el script muestra la evidencia de los papers y los productos del mercado que cumplen ese perfil, con su composición comparada contra el resto:

```bash
python cruce_mercado.py --matriz leche_liquida --tipo_beta_caseina A2
python cruce_mercado.py --matriz leche_liquida --tratamiento_termico uht
```

En la base, la vista `evidencia_mercado` hace el mismo cruce para cada hallazgo, y las tablas `equiv_matriz` y `equiv_tratamiento` traducen el vocabulario de los papers al del USDA. Se excluyen los productos saborizados, para que el azúcar agregado no distorsione los promedios.

**Normatividad (`normas.csv` + `normatividad.py`):** los límites legales que delimitan el diseño y el proceso: temperatura y tiempo de pasteurización/UHT, composición mínima de la leche cruda y de la leche entera o descremada, requisitos del yogur, cadena de frío, límites microbiológicos, rotulado y registro sanitario. Cada fila de `normas.csv` es un parámetro con su mínimo y su máximo, filtrado por tipo de producto, tratamiento térmico, nivel de grasa y especie. Las filas con el mismo `norma_id` forman un requisito, y si hay varias `alternativa` basta cumplir una (por ejemplo, pasteurización lenta **o** rápida). El CSV es la fuente de verdad: se copia a la tabla `normas` de `selema.db` cada vez que se abre la base. En `JURISDICCIONES_NORMAS` (`config_proc.py`) se eligen las jurisdicciones que se evalúan (por defecto `colombia` y `codex`; `ee_uu` y `union_europea` quedan como referencia).

> **Importante:** todas las filas vienen con `verificado = no`. Los valores se transcribieron sin confrontarlos con el texto oficial vigente. Revisa cada uno (en especial el Decreto 616 de 2006, la Res. 810 de 2021 y sus modificaciones), corrígelo si hace falta y pon `verificado = si`.

```bash
python normatividad.py                                   # qué hallazgos y productos cumplen o incumplen
python normatividad.py --matriz leche_liquida --tratamiento_termico uht   # requisitos de un perfil
python arbol_decision.py --dentro-de-norma               # árbol sin hallazgos obtenidos fuera de la norma
```

- `tabla_arbol` gana las columnas `estado_normativo` (`cumple` / `fuera_de_norma` / `sin_datos`) y `detalle_normativo`. No son variables del árbol; sirven para filtrar.
- Cada regla del árbol (en la consola y en la app) lista los requisitos legales que activa y recibe un **veredicto normativo** según los hallazgos que respaldan su efecto:
  - **Fuera de norma:** más de la mitad de los hallazgos se obtuvo con un proceso ilegal.
  - **Permitida:** ningún hallazgo está fuera de norma, sus requisitos están verificados y, si tiene límites de proceso, la mayoría de los hallazgos demuestra cumplirlos.
  - **Requiere verificación:** todo lo demás, con el motivo.
- Además, `cruce_mercado.py` agrega una sección 3 con los requisitos del perfil.
- La pestaña **Normatividad** de la app muestra los límites por perfil, los hallazgos fuera de norma y los productos del USDA que no cumplen su denominación.
- Si un hallazgo trae `temperatura_c` < 50 °C, se toma como temperatura de almacenamiento y no de proceso. Los hallazgos de estrés térmico de las vacas no se evalúan.

Opciones útiles: `extract_llm_insights.py --top 150`, `arbol_decision.py --resultado sintomas_gastrointestinales --solo-primaria --profundidad 3`.

Para agregar o cambiar columnas, edita `esquema.py` y borra `../busqueda/output/selema.db` (se regenera corriendo de nuevo la búsqueda; la extracción del LLM habría que repetirla).

**Texto completo (`fetch_fulltext.py`):** los abstracts casi nunca dan temperatura, tiempo, pH o composición exactos, y los métodos del paper sí. El script busca cada paper de acceso abierto en [Europe PMC](https://europepmc.org), que entrega el texto por secciones. Si no está ahí, intenta el PDF de acceso abierto; muchas editoriales (MDPI, Elsevier, Wiley) bloquean las descargas automáticas, así que esos papers quedan como `no_disponible`. El texto se guarda en la tabla `textos_completos`. El LLM no recibe el paper entero, porque no cabe en la cuota: recibe las frases con más datos de proceso, priorizando la sección de métodos, hasta `MAX_CARACTERES_TEXTO_COMPLETO` (`config_proc.py`) caracteres. La cita de cada observación se verifica contra el texto completo, y `observaciones.cita_en` dice si vino del `abstract` o del `texto_completo`. Al correr `extract_llm_insights.py` después, solo se re-extraen los papers que ganaron texto; los demás siguen en caché.

**Limitaciones:** los papers que no están en Europe PMC ni tienen un PDF descargable siguen dependiendo del abstract, así que en ellos los datos numéricos suelen quedar vacíos. Los fragmentos son una selección automática: una condición descrita sin números (por ejemplo, "pasteurizada según el método estándar") no se detecta.
