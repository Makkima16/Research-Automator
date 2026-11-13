# Pendientes

Última actualización: 2026-11-13

## 0. Optimizaciones detectadas en la limpieza (y su estado)

- [x] **Variante «pares de grupos»: aplicada el 2026-10-30.** Medida en el banco de amplitud (0,73
      estricta / 0,97 laxa y mediana de 332 resultados contra 0,66 / 0,97 y 129 de la cadena completa),
      ahora `fetch_papers.py` la aplica como primer rescate cuando una cadena de 3 o más grupos trae
      menos de `UMBRAL_RESCATE_FULLTEXT` (15) resultados en título y abstract; el texto completo
      (`default.search`) quedó como segundo rescate. Relevo con las 37 cadenas del banco y juez
      GPT-5.5: misma cantidad entregada (909 papers) con mejor calidad (estricta 0,66 → 0,69, laxa
      0,99 → 1,00); ninguna cadena entregó menos papers que antes.
- [x] `busqueda/main.py` rankeaba con keywords sucias (`q.split()` incluía `AND`/`OR`/`NOT` y comillas
      pegadas): 923 keywords sucias contra 210 limpias; un abstract con «and» repetido puntuaba 424,7
      por los operadores sueltos y ahora 0,2. Unificado en `rank_and_filter.palabras_clave`, que
      `api/servidor.py` ya usaba con la misma lógica (verificado: salida idéntica sobre las 37
      cadenas reales del banco).
- [x] **Semantic Scholar re-rankeado en local: aplicado el 2026-10-30.** Su búsqueda bulk solo ordena
      por citas y los primeros resultados se desviaban del tema (sonda del 2026-10-29: el más citado,
      683 citas, estaba fuera). Ahora `buscar_semantic_scholar` trae un pool de hasta 100 y devuelve los
      `max_results` mejor puntuados localmente con las keywords de la propia cadena, al mismo costo en
      solicitudes (la bulk devuelve hasta 100 por página). Medido con `pruebas/cadenas/sonda_s2_v2.py`
      (juez Nemotron): con pool lleno, el top elegido por citas daba 12/26 de estricta/laxa contra
      15/30 del top re-rankeado. Restricción pendiente: Semantic Scholar sigue dando 429 incluso con
      key (cayó 4 de 9 cadenas de la sonda); su cuota es el problema, no el orden.
- [x] `pruebas/cadenas/banco.py` y `azure_prueba.py` dependían de Azure/GPT-5.5, cuya suscripción venció
      el 2026-10-30: **borrados** (decisión del usuario). Los resultados que produjeron se conservan en
      `pruebas/cadenas/resultados/`; `amplitud.py` y `relevo.py` quedaron con el juez Nemotron fijo.
- [x] Limpieza final de Azure (2026-10-31, pedido del usuario): las variables `AZURE_*` ya no existían en
      el código ni en `.env.example`. Se borraron `pruebas/fichas_pdf/` (`fichas_vs_gpt.py` y
      `tablas_parse.py`, que solo servían para comparar Nemotron contra los datos legados de Azure en
      `prueba_lacteos_y_cafe.db`), el fallback al juez GPT-5.5 de `rellenar.py` y las etiquetas
      «Document Intelligence (antiguo)» de `frontend/web/app.js` y `frontend/web-next/src/lib/formato.ts`
      (las 11 estructuras viejas de la base se muestran con la clave cruda). Los datos legados de la
      base y las menciones históricas de la documentación se conservan.

## Migración de SQLite a PostgreSQL (2026-10-31)

- [x] **Hecha: reemplazo total de SQLite** (decisión del usuario: Postgres relacional + JSONB en una sola
      base; MongoDB descartado). Capa de datos en `busqueda/database.py` (psycopg3) con las tablas
      `papers` (pool compartido), `proyectos` (estado en JSONB), `papers_proyectos` (N:M con orden del
      ranking, score y selección), `estructuras` y `fichas` (payload en JSONB con índices GIN). La
      conexión sale de `DATABASE_URL` (`.env`; plan gratuito de Neon). `main.py`, `extract_ficha.py`,
      `almacen.py` y `servidor.py` ya escriben y leen Postgres; la verificación de sintaxis e imports
      pasó (`py_compile` + import de cada módulo).
- [x] Borradas a pedido del usuario todas las bases SQLite de prueba (`selema.db` y las 6 de
      `output/proyectos/`; no había datos reales).
- [x] **Base creada y verificada (2026-11-04).** La conexión se configura con una variable por dato
      (`NEON_HOST`, `NEON_DATABASE`, `NEON_USER`, `NEON_PASSWORD`, `NEON_SSL_MODE`; `config.py` arma la
      URL; `DATABASE_URL` ya no se usa). `python probar_postgres.py` pasa y las cinco tablas con sus dos
      índices GIN quedaron creadas en Neon. Se corrigieron dos fallos: `probar_postgres.py` dejaba su
      paper de prueba sin borrar, y `database.conectar()` no usaba autocommit, así que toda escritura
      hecha después de una lectura en la misma conexión (el caso de `extract_ficha.procesar`: estructuras
      y fichas) se perdía al cerrar; ahora la conexión es autocommit y se verificó que persiste.
- [x] Recorrido de punta a punta con la interfaz (crear proyecto → cadenas → búsqueda → fichas): hecho
      en el navegador, confirmado por el usuario el 2026-11-13.
      (La API ya responde contra Neon: `GET /api/proyectos` → 200.)
- [x] `pruebas/cadenas/estrictez.py` (pendiente 2) adaptado (2026-11-04): lee los papers objetivo de
      PostgreSQL (`proyectos` → `papers_proyectos` → `papers`) en solo lectura. Compila y consulta la
      base; no se corrió la prueba completa porque la base aún no tiene papers (hay que crear antes un
      proyecto con búsqueda).

## 1. Terminar las pruebas de validación de las cadenas

**Contexto.** Se cambió la generación de cadenas de GPT-5.5 (Azure) a Nemotron (NVIDIA). Con el prompt
original Nemotron escribía cadenas mucho más pobres (1,14 alternativas por grupo contra 3,29 de GPT-5.5).
Se resolvió pidiéndole solo los términos de cada grupo y armando la sintaxis en código (`generar_cadenas.py`,
formato de grupos), con un paso de restauración de tildes para español y «Ambos». En **estructura** el
resultado es equivalente al de GPT-5.5 (3,0 a 5,0 alternativas por grupo, sin grupos de un solo término).

**Hecho el 2026-10-29/30 (banco de amplitud, `pruebas/cadenas/amplitud.py`).** El problema de "busca muy
pocos papers" no estaba en las cadenas sino en cómo se ejecutaban. Medido sobre 8 temas y 37 cadenas con
juez GPT-5.5 (criterio 0/1/2: 2 = trata el tema o varios conceptos; 1 = toca un concepto; 0 = desviado):

- Frases exactas (comillas) innecesariamente restrictivas: sin comillas, mediana de resultados
  129 → 148, cadenas con 0 resultados 3 → 1, precisión igual (0,66/0,67 estricta; 0,97/0,99 laxa).
- Cadenas de 3 grupos AND muy estrictas: cada par de grupos por separado da mediana 332 con la mejor
  precisión de todas (0,73 estricta / 0,97 laxa). Queda como opción a explorar.
- El tope de 10 papers por cadena y motor (`MAX_RESULTS_PER_QUERY`) era el limitante real de cantidad:
  temas con miles de resultados entregaban 50.
- Rescate en texto completo: si la cadena trae < 15 resultados en título y abstract, repetirla con
  `default.search` rescata las cadenas con 0 (21, 8 y 39 resultados) con laxa 0,98.
- OpenAlex se agota a diario (429 por IP compartida); Semantic Scholar también dio 429 y su orden por
  citas trajo el paper más citado desviado (muestra chica, no concluyente).
- Acuerdo del juez Nemotron con GPT-5.5: 0,66 exacto — tras el vencimiento de Azure (2026-10-30) los
  números nuevos no son comparables con los históricos.

**Cambios aplicados al producto (verificados con `pruebas/cadenas/relevo.py`):**

- [x] `fetch_papers.py`: ignorar las comillas al traducir a OpenAlex y rescate en texto completo si la
      cadena trae < 15 resultados (`UMBRAL_RESCATE_FULLTEXT`).
- [x] `config.py`: `MAX_RESULTS_PER_QUERY` de 10 a 25 (los proyectos ya guardados conservan su valor;
      se sube a mano en la interfaz).
- [x] Soporte de `OPENALEX_API_KEY` (config + `fetch_papers.py` + `.env.example`).
- [x] Relevo con el código nuevo: 307 → 909 papers entregados (×3) con la misma calidad
      (estricta 0,66, laxa 0,99; juez GPT-5.5 sobre 370 títulos).

**Qué falta.**

- [x] Key de OpenAlex: ya está en el `.env` como `OPENALEX_API_KEY` y las búsquedas del 2026-11-13
      respondieron sin 429.
- [x] Variante "pares de grupos" para cadenas de 3+ grupos: evaluada y aplicada (ver sección 0).
- [x] Comparación con GPT-5.5 como generador: el usuario la midió por su cuenta (2026-11-13) y las
      cadenas de Nemotron resultaron similares, aunque GPT-5.5 sigue siendo algo mejor. No hay archivo de
      resultados de esa medición; los históricos están en `pruebas/cadenas/resultados/`.
- [x] Defectos de las cadenas en español, revisados el 2026-11-13 con 2 temas en `es` y `ambos`:
      concordancia y tildes salen bien (`robot colaborativo`, `gérmenes`, `México`) y los duplicados
      ignorando mayúsculas ya los quita `_normalizar`. Se corrigió un defecto real: los `detalles` de la
      ventana «cadenas usadas» guardaban la cadena sin normalizar y la interfaz los emparejaba por texto
      exacto, así que caía al índice; ahora cada detalle lleva su cadena normalizada. Quedan, sin regla
      segura para corregirlos: alguna errata del modelo (`innocuidad`) y, en español, varias cadenas que
      repiten el primer grupo (se ve en lácteos).

## 2. Pruebas de estrictez: cuán restrictiva puede ser una cadena

**Objetivo.** Determinar hasta qué punto una cadena puede ser estricta (o flexible) y aun así devolver un
paper que se sabe que existe. Sirve para fijar cuántos grupos `AND` y cuántas alternativas `OR` conviene
pedirle al modelo.

- [x] Script creado y corrido el 2026-10-30 (`pruebas/cadenas/estrictez.py`): 10 papers objetivo de los
      proyectos guardados (solo lectura), 6 niveles de restricción por paper (de un grupo OR a frase
      exacta + NOT), en OpenAlex y con verificación por DOI de si el paper matchea la cadena aunque no
      esté en el top-300 (distinguir "enterrado" de "perdido"). Resultados (`resultados/estrictez_res.json`):
- Ningún nivel pierde el paper objetivo salvo el `NOT`: con `NOT review` se pierden 4 de 10 (papers del
      tema que mencionan "review"). Valida que el prompt solo admita NOT a pedido expreso del usuario.
- Tres grupos AND de un término posicionan el paper conocido en el puesto 16 (mediana) con 2.706
      resultados; dos grupos con OR lo dejan en el 102 con 594.644. La frase exacta no aporta nada
      frente a los términos sueltos (misma mediana de total, peor posición).
- Conclusión para la configuración: el formato actual del prompt (2-3 grupos AND con 2-4 alternativas
      OR, sin NOT, sin frases exactas en OpenAlex) es el equilibrio correcto entre encontrar el paper
      específico y no ahogar la cantidad de papers relacionados; no hace falta hacerlo configurable por
      el usuario. Si algún día se quiere un modo "encuentra este paper específico", la palanca es pedir
      3 grupos AND, no apretar comillas ni NOT.
- [x] Escala por motor (2026-11-13, `pruebas/cadenas/estrictez_motores.py`, 6 papers, tope de 100
      resultados; resultados en `resultados/estrictez_motores_res.json`). Scopus: el paper aparece en 2/6
      con la cadena flexible, 3/6 con dos grupos, 4/6 con frase exacta y 3/6 con tres grupos sueltos.
      Semantic Scholar: 0/6 en los niveles flexibles (L1 a L3, con 429 de por medio, así que no es
      concluyente) y 3 a 4/6 con tres grupos, frase exacta o NOT. Misma dirección que OpenAlex: las
      cadenas más estrictas ubican mejor al paper dentro de un tope y las flexibles lo entierran. No
      distingue «enterrado» de «perdido» y la muestra es chica; Semantic Scholar sigue dando 429.

## 3. Frontend: pasar de monolito a un proyecto Next.js propio

**Situación actual.** `api/servidor.py` es un único servidor en Python que expone la API
(`/api/proyectos…`) y además sirve la interfaz estática (`frontend/web/app.js`, `app.css`, `index.html`).

- [x] Separar la API del servidor (2026-11-04): `servidor.py` ya no sirve archivos estáticos, solo `/api/*`
      (`/` da 404). Verificado: `GET /api/proyectos` → 200 contra Neon. Rutas documentadas en `COMANDOS.md`.
- [x] Crear un proyecto **Next.js** independiente para la interfaz, con su propio `package.json`, y
      reconstruir ahí las pantallas actuales (prompt y aclaración, cadenas, resultados de búsqueda,
      resultados de procesamiento). Hecho en `frontend/web-next/` (Next 16, React 19, TypeScript).
- [x] Mantener las pestañas separadas para búsqueda y procesamiento, y aplicar el diseño de Claude Design
      (sistema Organic, importado de `Research Automator.dc.html`).
- [x] Definir cómo se comunican ambos: el navegador solo habla con Next, que reenvía `/api/*` al backend
      (`API_URL`, por defecto `http://127.0.0.1:8000`) con un Route Handler; no hace falta CORS. El sondeo
      cada 1 s se mantiene. Documentado en `README.md` y `COMANDOS.md`.
- [x] (Confirmado por el usuario el 2026-11-13.) Verificar el flujo completo con escritura desde la interfaz Next **en el navegador** (con el
      usuario). Estado al 2026-10-30: backend verificado con escritura (`pruebas/testeo_general.py`,
      tres corridas OK) y web-next sirviendo contra él (página en el 3000, proxy `/api/*` al 8000
      devolviendo los 6 proyectos). Falta el recorrido a mano: crear proyecto → aclarar → cadenas →
      buscar → procesar (probar el tope editable) → fichas → exportar. Con eso se confirma la paridad
      para decidir el punto siguiente.
- [x] Tope «Máx. papers por corrida» editable: hecho el 2026-10-30. `POST /procesar` acepta `tope`
      (1 a `MAX_PAPERS_PROCESAR_WEB`, que sigue siendo el techo) y la tarjeta de «Procesar PDFs» de
      web-next lo deja bajar (por defecto queda en el techo). Verificado end-to-end: selección de 2
      con tope 1 → procesa 1.
- [x] `frontend/web/` (la interfaz anterior) borrada el 2026-11-04 a pedido del usuario, que confirmó que
      el proyecto funcionó bien. `servidor.py` y `almacen.py` se movieron a `api/` (raíz del proyecto).

## 4. Fichas: extracción, presentación y validación (2026-11-12)

- [x] **Esquema nuevo de la ficha** (`extract_ficha.py`): frase de síntesis, relevancia para el tema
      (alta / media / baja / nula) con motivo, qué aporta al tema, objetivo, método (tipo de estudio,
      muestra, contexto), hasta 4 hallazgos, hasta 3 conclusiones y limitaciones declaradas. El prompt
      prohíbe mencionar los otros papers del lote (en la primera corrida una ficha decía «copia idéntica
      de P3»).
- [x] **«Procesar PDFs» solo procesa la selección** (decisión del usuario): la API ignora `alcance` y
      responde 400 si no hay papers marcados; la interfaz ya no ofrece «Todos».
- [x] **Interfaz de fichas**: cerrada muestra título, relevancia con motivo y una frase; abierta, tres
      solapas (Lo esencial · Método y conclusiones · Texto original). Fichas ordenadas por relevancia y
      filtros por nivel. `next build` pasa.
- [x] **Prueba `pruebas/fichas/validar_fichas.py`** corrida sobre el único proyecto de la base
      («mujeres jóvenes en ingeniería»; sin selección, muestra de 10 del tope + 5 de control): 11 fichas
      validadas (4 papers sin abstract no tienen ficha). Estructura 1,0; cifras respaldadas 1,0; acuerdo
      útil/no útil con el juez 1,0; acuerdo exacto de nivel 0,82; afirmaciones respaldadas 1,0; aporte
      pertinente 1,0. Resultado en `pruebas/fichas/resultados/`.
- [x] **Resuelto el 2026-11-13: con el concepto central como término obligatorio, el ranking lo respeta.**
      Con «mujeres», «ingeniería» y «deserción» como obligatorios (búsqueda real, 209 papers), 8 de los 10
      primeros son pertinentes y 3 son centrales (puestos 1, 3 y 4); queda un editorial de abstract largo
      en el puesto 6. No hizo falta cambiar el ranking: lo que faltaba era marcar la deserción como
      obligatoria. Problema original:
      **Los resultados de la búsqueda no siguen la intención del tema.** Los 10 primeros del ranking
      tratan de predicción de deserción en general; ninguno aborda mujeres ni variables de género. El
      único paper sobre barreras de género para mujeres (Tanzania) estaba al final del ranking. Las
      fichas lo detectan bien (motivo: «no aborda mujeres en ingeniería»), pero el problema está en las
      cadenas o en el ranking.
- [x] **Error al marcar papers (2026-11-12)**: «AttributeError: 'Connection' object has no attribute
      'executemany'» al guardar la selección. Resto de la migración desde SQLite en
      `api/almacen.guardar_seleccion` (en psycopg3 `executemany` es del cursor). Corregido y verificado con
      `PUT /api/proyectos/{id}` (la selección queda en `papers_proyectos`); no quedan otros usos de la API
      de SQLite en el código.
- [x] **Deduplicación por DOI sensible a mayúsculas: corregida el 2026-11-12.** El mismo paper entraba
      dos veces con `paper_id` distinto (`10.1109/ICETAS59148…` y `10.1109/icetas59148…`). Nuevo módulo
      `busqueda/doi.py` (formato único: `https://doi.org/` + minúsculas), usado por OpenAlex, Scopus,
      Semantic Scholar y `database.py`. Los datos guardados se migraron con
      `busqueda/normalizar_dois.py --aplicar`: 14 IDs renombrados y 6 duplicados fusionados (109 → 103
      papers; fichas 15 → 13, porque los dos pares duplicados de la prueba se fusionaron). Verificado:
      0 duplicados, 0 filas huérfanas, `probar_postgres.py` OK y la API devuelve 103 papers sin IDs
      con mayúsculas. El JSON de `pruebas/fichas/resultados/` es anterior a la migración y todavía
      muestra los dos pares duplicados.
- [ ] Cobertura baja: 9 de 11 fichas son parciales (sin PDF de acceso abierto) y 4 de 5 papers de control
      no tenían abstract, así que el grupo de control (1 ficha) no alcanza para medir discriminación.
- [ ] El juez de la prueba es el mismo modelo que redacta las fichas: el acuerdo mide consistencia, no
      exactitud independiente. Validar a mano una muestra cuando haya papers seleccionados.

## 5. Búsqueda guiada por el usuario y filtros de resultados (2026-11-12)

- [x] **Tope de «Procesar PDFs» trabado**: con 3 seleccionados solo dejaba procesar 1. El campo `tope`
      era a la vez el techo del servidor y lo pedido en la última corrida; tras una corrida con tope 1, la
      interfaz tomaba 1 como techo. Ahora el techo va aparte (`procesamiento.tope_max`, siempre
      `MAX_PAPERS_PROCESAR_WEB`). No tenía relación con el acceso abierto.
      **Causa de raíz (encontrada después):** con el tope en el máximo la interfaz no envía `tope`, y
      `iniciar_procesamiento` lo convertía en 0 y luego `max(1, 0)` = 1: toda corrida sin tocar el tope
      procesaba 1 solo paper. Corregido: sin `tope` se usa el techo. Se confirmó en la base con un proyecto
      nuevo (3 seleccionados, corrida registrada con `tope: 1` y `tope_max: 100`).
- [x] **Términos obligatorios** (hasta 5, AND entre ellos; decisión del usuario): chips en el prompt y en el
      prompt ya usado («Regenerar cadenas»). El código garantiza que estén en todas las cadenas, el rescate
      por pares de grupos los conserva y el ranking suma `OBLIGATORIO_BONUS` por cada uno. Verificado con
      Nemotron sobre el tema del proyecto existente con «mujeres» e «ingeniería»: 5/5 cadenas en inglés y
      5/5 en «Ambos» con los dos términos; y por la API con un proyecto temporal (borrado al final):
      «infogest» y «leche, lácteos» en las 3 cadenas.
- [x] **Filtros de resultados**: por cadena y por términos en título y abstract (chips, interruptor AND/OR;
      decisión del usuario), más la ventana «cadenas usadas · ver» con la intención de cada cadena y
      cuántos papers trajo. `tsc` y `next build` pasan.
- [x] **Navegación hacia atrás desde los resultados**: los pasos del encabezado (Tema, Cadenas,
      Resultados) se pueden pulsar, y la vista de resultados tiene «Volver a las cadenas» y «Ver el prompt».
      Solo cambian la etapa del proyecto: no borran cadenas, papers ni fichas.
- [x] **Recorrido por la API contra Neon (2026-11-13)**: proyecto nuevo «mujeres jóvenes en ingeniería /
      deserción» con términos obligatorios «mujeres» e «ingeniería» → 5 cadenas, todas con ambos términos →
      búsqueda real: OpenAlex 108, Semantic Scholar 110 (sin 429 esta vez) y Scopus 78 resultados; 262
      papers únicos tras la deduplicación por DOI, guardados en Neon (proyecto `18f9774e76b7`). Los 10
      primeros del ranking tratan todos de mujeres/género en ingeniería o STEM (antes ninguno), pero solo
      2 son centrales a la deserción femenina en ingeniería (puestos 5 y 9); el resto es adyacente (brecha
      de género en STEM, mentoría, pertenencia) y uno es sobre profesoras. Se probó puntuar por conceptos
      cubiertos por grupo de cadena: no cambió el orden (las 5 cadenas comparten los dos primeros grupos),
      así que no se aplicó.
- [x] Recorrido en el navegador (filtros, ventana de cadenas, procesar varios seleccionados):
      confirmado por el usuario el 2026-11-13 («ya quedó ok»).
