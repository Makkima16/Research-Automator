# Contexto de las pruebas de calidad

Última actualización: 2026-10-30

Resumen de lo hecho hasta ahora para que cualquier agente o persona pueda retomar las pruebas de
`PENDIENTES.md` (puntos 1 y 2) sin haber visto la conversación. Solo hechos terminados y resultados medidos.

## 1. Cambios hechos en el proyecto

**Interfaz (prompt y aclaración).** Al volver al prompt después de generar cadenas se conservan las preguntas
y respuestas (campo `aclaraciones` del proyecto) y el prompt queda bloqueado. Solo se edita con «Rehacer
prompt» (`rehacer_prompt` en `frontend/servidor.py`), que borra preguntas, intención, cadenas, papers
buscados, selección y procesamiento, con confirmación.

**Azure reemplazado por NVIDIA.**
- LLM: `nvidia/nemotron-3.5-super-vl-120b-a12b` sin razonamiento (`enable_thinking: false`), en
  `busqueda/llm_nvidia.py`, compartido por búsqueda y procesamiento. Modelo y URLs en `busqueda/config.py`.
- Lector de PDFs: `procesamiento/lectura_pdf.py` (antes `document_intelligence.py`). PyMuPDF lee en local; a
  Nemotron Parse solo van las páginas con títulos «Table N», las de las conclusiones y las primeras. Un PDF
  escaneado usa las primeras y las últimas, hasta `MAX_PAGINAS_PARSE` (10).
- Fichas: lotes de 8 papers, `HILOS_LOTES_FICHA` (2) lotes a la vez.
- Se borró todo el código de Azure del proyecto. Keys: `NVIDIA_API_KEY` y `NVIDIA_PARSE_API_KEY` en `.env`.

**Generación de cadenas (`busqueda/generar_cadenas.py`).**
- Formato de grupos: el modelo entrega solo los términos de cada grupo (`INSTRUCCIONES_GRUPOS`) y el código arma
  la cadena (`_armar_cadena`: frases de varias palabras entre comillas, `OR`, `AND`, `NOT`).
- `_normalizar`: quita paréntesis y alternativas o grupos repetidos, deja un único `NOT` al final con un solo
  término y descarta las cadenas de un solo grupo (salvo en español, donde el prompt las pide a propósito).
- Tildes: en «es» y «Ambos», un segundo paso con el LLM (`_restaurar_tildes`) añade tildes y ñ; solo se acepta
  si, quitando las tildes, la cadena queda idéntica a la original.
- Gemini dejó de ser respaldo de la generación de cadenas y se eliminó del proyecto el 2026-10-30
  (key `LLM_API_KEY`, `LLM_MODELO`, `CADENAS_PROVEEDOR`, `_con_gemini` con LangChain y las líneas de
  `langchain-google-genai` de los requirements): su capacidad era muy limitada frente a Nemotron y no
  servía ni como reemplazo. El respaldo cuando Nemotron no responde son las cadenas básicas sin LLM
  (`cadenas_basicas`). El prompt de cadenas escritas (`INSTRUCCIONES`) se movió a
  `cadenas/modelos.py`, único script que lo usa (comparación de formatos).

## 2. Hallazgos medidos

**Estructura de las cadenas** (8 temas guardados, mismo prompt y mismas respuestas de aclaración):

| Condición | Alternativas por grupo | Grupos de un solo término |
|---|---|---|
| Históricas (proyectos guardados) | 2,20 | 48 % |
| GPT-5.5, prompt original | 3,29 | 0 % |
| GPT-5.5, prompt actual | 3,36 | 0 % |
| Nemotron, prompt original | 1,14 | 88 % |
| Nemotron, prompt actual (cadena escrita) | 1,71 | 69 % |
| Nemotron, formato de grupos (actual) | 3,0 a 5,0 | 0 % |

Con el prompt de cadenas escritas, Nemotron a veces devolvía palabras sueltas sin operadores (tema de la
harina de banano).

**Precisión de los primeros 8 resultados** (juez GPT-5.5 sobre títulos, resultados parciales: 13 a 18 cadenas
por condición, solo 3 temas, no concluyentes): GPT-5.5 prompt actual 0,41; históricas 0,30; GPT-5.5 prompt
original 0,19; Nemotron prompt original 0,04. **Con el formato de grupos no se midió.**

**Banco de amplitud de la búsqueda** (`cadenas/amplitud.py`, 2026-10-29/30: 8 temas, 37 cadenas con el
formato de grupos, ejecutadas en OpenAlex con año mínimo 2015; juez GPT-5.5 con criterio nuevo 0/1/2:
2 = trata el tema o varios conceptos de la cadena, 1 = toca un concepto, 0 = desviado — **no comparable**
con la precisión 0/1 histórica). Variantes de ejecución sobre cada cadena, mediana de resultados y
fracción de puntos 2 / ≥1 sobre los primeros títulos:

| Variante | Mediana de resultados | Estricta (=2) | Laxa (≥1) |
|---|---|---|---|
| base (tal cual) | 129 | 0,66 | 0,97 |
| sin comillas | 148 | 0,67 | 0,99 |
| pares de grupos (solo cadenas de 3+) | 332 | 0,73 | 0,97 |
| texto completo (`default.search`) | 2.235 | 0,56 | 0,98 |
| todo unido con OR (control) | 165.565 | 0,37 | 0,96 |

Conclusiones de ese banco: las cadenas estaban bien; lo que limitaba la cantidad de papers era (1) el tope
de 10 por cadena y motor, (2) las frases exactas y (3) cadenas de 3 grupos demasiado estrictas, que a
veces devolvían 0 (3 cadenas de 37). El rescate en texto completo trajo 21, 8 y 39 resultados para esas
cadenas con 0, con laxa 0,99 (relacionados) y estricta 0,21 (pocos tratan el tema de frente). Semantic
Scholar dio 429 en una de tres cadenas y su orden por citas trajo el paper más citado desviado (muestra
chica). Acuerdo del juez Nemotron con el de GPT-5.5: 0,66 exacto sobre 80 títulos (después de que Azure
venza, los números nuevos no son comparables con los de GPT-5.5).

**Cambios aplicados al producto tras el banco** (verificados con `cadenas/relevo.py` sobre las mismas 37
cadenas): ignorar comillas al traducir a OpenAlex, rescate en texto completo si la cadena trae menos de
`UMBRAL_RESCATE_FULLTEXT` (15) resultados, `MAX_RESULTS_PER_QUERY` de 10 a 25 y soporte de
`OPENALEX_API_KEY`. Resultado del relevo: 307 → 909 papers entregados, con la misma calidad del top
(estricta 0,66, laxa 0,99; juez GPT-5.5 sobre 370 títulos).

**Optimizaciones de la limpieza del 2026-10-30** (relevo repetido con las mismas 37 cadenas y el mismo
juez): el rescate por pares de grupos (aplicado como primer escalón antes del texto completo) mantuvo la
cantidad entregada (909 papers) y mejoró la calidad del top: estricta 0,66 → 0,69 y laxa 0,99 → 1,00;
ninguna cadena entregó menos papers que antes y 7 mejoraron su top. La cadena de cobots que traía 1
resultado pasó a 20, todos en tema. Además, `main.py` ahora rankea con keywords limpias
(`rank_and_filter.palabras_clave`, la misma que usaba el frontend): 923 keywords sucias → 210 limpias.
El testeo general del flujo completo (crear proyecto → aclarar → cadenas → búsqueda real → procesar →
fichas → CSV → borrar) pasó con `pruebas/testeo_general.py` y dejó `busqueda/output/proyectos/`
exactamente como estaba.

**Semantic Scholar re-rankeado en local (2026-10-30, `cadenas/sonda_s2_v2.py`).** Su búsqueda bulk solo
ordena por citas y los primeros resultados se desviaban. Sonda con 9 cadenas y juez Nemotron (0/1/2):
con pool lleno, el top-10 por citas daba 12/26 de estricta/laxa contra 15/30 del top-10 re-rankeado con
`rank_and_filter` y las keywords de la cadena; el mejor caso pasó de 3 a 7 papers en tema de 10. Aplicado
a `fetch_semantic_scholar.buscar_semantic_scholar`: trae hasta 100 y devuelve los mejor puntuados, al
mismo costo en solicitudes. Semantic Scholar siguió dando 429 incluso con key (4 de 9 cadenas de la
sonda cayeron): su cuota es el problema, no el orden.

**Pruebas de estrictez (2026-10-30, `cadenas/estrictez.py`).** 10 papers objetivo de los proyectos
guardados, 6 niveles de restricción en OpenAlex, con verificación por DOI de si el paper matchea la
cadena fuera del top-300 (distinguir «enterrado» de «perdido»):

| Nivel | En top-300 | Enterrados | Perdidos | Posición mediana | Resultados mediana |
|---|---|---|---|---|---|
| Un grupo OR | 6/10 | 4 | 0 | 8 | 11.049.237 |
| Dos grupos con OR | 8/10 | 2 | 0 | 102 | 594.644 |
| Dos términos AND | 2/10 | 8 | 0 | 148 | 74.980 |
| Tres términos AND | 8/10 | 2 | 0 | **16** | 2.706 |
| Frase exacta + término | 7/10 | 3 | 0 | 84 | 2.706 |
| Frase + término + NOT | 5/10 | 1 | **4** | 73 | 1.940 |

Conclusiones: ningún nivel pierde el paper conocido salvo el `NOT` (mata 4 de 10, papers del tema que
mencionan «review»: valida que el prompt solo lo admita a pedido); tres grupos AND posicionan el paper
específico en el puesto 16 pero reducen el total a 2.706; la frase exacta no aporta nada frente a los
términos sueltos. El formato actual del prompt (2-3 grupos AND con 2-4 alternativas OR) es el equilibrio
correcto y no hace falta configurarlo por el usuario.

**Tope «Máx. papers por corrida» editable (2026-10-30).** `POST /procesar` acepta `tope` (1 a
`MAX_PAPERS_PROCESAR_WEB`, que sigue de techo) y la tarjeta de web-next lo deja bajar. Verificado
end-to-end: selección de 2 con tope 1 → procesa 1.

**Otros modelos de NVIDIA** (estructura, 8 temas): Nemotron 3 Ultra 550B, Mistral Large 4 y gpt-oss-20b dan
3,4 a 3,8 alternativas por grupo, pero tardan 35 a 65 s por llamada (Nemotron 3.5 Super VL: 11 s) y en
formato de cadena escrita fallan más (25 de 45 cadenas con Mistral y gpt-oss). `kimi-k2.6` y
`nemotron-3-super-120b-a12b` responden 404 en esta cuenta; DeepSeek V4.1 Flash, GLM 5.3 Flash y Gemma 4 se
quedaron colgados más de 60 s. No hay motivo para cambiar de modelo.

**Lectura de PDFs y fichas.** En 8 papers con fichas de GPT-5.5 ya guardadas, Nemotron coincidió en
`es_relevante` en 7 y no inventó cifras. Nemotron Parse reprodujo las dos tablas de un paper con los mismos
nombres y atributos que Document Intelligence (una sola muestra). Parse tarda unos 26 s por página en
documentos largos.

## 3. Bloqueos y plazos

- **OpenAlex** devuelve HTTP 429 «Insufficient budget» cuando se agota el presupuesto diario gratuito,
  compartido por IP; se renueva a las 00:00 UTC (19:00 en Colombia), aunque el 2026-10-30 tardó unos
  minutos más. `busqueda/fetch_papers.py` ya envía `OPENALEX_API_KEY` si existe en el `.env` (hace falta
  conseguirla; ver `PENDIENTES.md`); sin key, en tandas largas de pruebas hay que contar con huecos de
  429 (el script `cadenas/rellenar.py` repite después las búsquedas caídas).
- **Azure (GPT-5.5)** solo estuvo disponible hasta el **2026-10-30**. Pasado ese día, la condición
  «GPT-5.5» no se puede volver a generar: solo quedan los resultados guardados en `cadenas/resultados/`.
  El juez de reemplazo es Nemotron; su acuerdo con GPT-5.5 fue 0,66 exacto, así que los números nuevos
  **no son comparables** con los medidos hasta esa fecha; para comparar, repetir las condiciones de
  referencia con el juez nuevo.

## 4. Defectos conocidos de las cadenas

- Errores de concordancia en español (`robot colaborativa`) y alguna palabra sin tilde (`germenes`).
- Varias estrategias repiten el mismo primer grupo y cambian solo el segundo (cáncer en español).
- Calcos raros al generar en «ambos»: `"entera leche"` (orden invertido) en el tema UHT.
- Las cadenas siguen siendo más específicas que las históricas (la más amplia del tema UHT pasó de 436 a
  83 resultados en título y abstract); la pérdida de resultados se compensa en el motor con el rescate en
  texto completo, no relajando la generación.

## 5. Qué sigue

Ver `PENDIENTES.md`, puntos 1 (qué falta del banco de amplitud: key de OpenAlex, variante «pares») y 2
(pruebas de estrictez), y la metodología en el skill `research-automator-cadenas`. Cómo correr los
scripts: `README.md` de esta carpeta.
