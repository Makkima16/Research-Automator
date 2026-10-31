# Pendientes

Última actualización: 2026-10-31

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
      `frontend/servidor.py` ya usaba con la misma lógica (verificado: salida idéntica sobre las 37
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

- [ ] Conseguir la key gratuita de OpenAlex y agregarla al `.env` como `OPENALEX_API_KEY` (el código ya
      la envía; el `.env` no lo edita el agente). Pedirla en https://openalex.org/users/me.
- [ ] Opcional: evaluar la variante "pares de grupos" para cadenas de 3+ grupos (triplica las búsquedas
      por cadena; precisión 0,73, mediana 332).
- [ ] La comparación de precisión con las condiciones históricas (GPT-5.5 como generador) no se repitió
      antes del vencimiento de Azure; los resultados guardados están en `pruebas/cadenas/resultados/`.
- [ ] Defectos menores de las cadenas en español siguen abiertos: errores de concordancia
      (`robot colaborativa`), palabras sin tilde (`germenes`), estrategias que repiten el primer grupo y
      calcos raros en inglés (`"entera leche"`).

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
- [ ] Falta repetir la escala por motor (Scopus y Semantic Scholar interpretan la sintaxis distinto);
      Semantic Scholar sigue dando 429 incluso con key, así que su corrida espera presupuesto estable.

## 3. Frontend: pasar de monolito a un proyecto Next.js propio

**Situación actual.** `frontend/servidor.py` es un único servidor en Python que expone la API
(`/api/proyectos…`) y además sirve la interfaz estática (`frontend/web/app.js`, `app.css`, `index.html`).

- [ ] Separar la API del servidor: dejar en Python solo la API (proyectos, aclaración, cadenas, búsqueda,
      procesamiento, exportación) y documentar sus rutas.
- [x] Crear un proyecto **Next.js** independiente para la interfaz, con su propio `package.json`, y
      reconstruir ahí las pantallas actuales (prompt y aclaración, cadenas, resultados de búsqueda,
      resultados de procesamiento). Hecho en `frontend/web-next/` (Next 16, React 19, TypeScript).
- [x] Mantener las pestañas separadas para búsqueda y procesamiento, y aplicar el diseño de Claude Design
      (sistema Organic, importado de `Research Automator.dc.html`).
- [x] Definir cómo se comunican ambos: el navegador solo habla con Next, que reenvía `/api/*` al backend
      (`API_URL`, por defecto `http://127.0.0.1:8000`) con un Route Handler; no hace falta CORS. El sondeo
      cada 1 s se mantiene. Documentado en `README.md` y `COMANDOS.md`.
- [ ] Verificar el flujo completo con escritura desde la interfaz Next **en el navegador** (con el
      usuario). Estado al 2026-10-30: backend verificado con escritura (`pruebas/testeo_general.py`,
      tres corridas OK) y web-next sirviendo contra él (página en el 3000, proxy `/api/*` al 8000
      devolviendo los 6 proyectos). Falta el recorrido a mano: crear proyecto → aclarar → cadenas →
      buscar → procesar (probar el tope editable) → fichas → exportar. Con eso se confirma la paridad
      para decidir el punto siguiente.
- [x] Tope «Máx. papers por corrida» editable: hecho el 2026-10-30. `POST /procesar` acepta `tope`
      (1 a `MAX_PAPERS_PROCESAR_WEB`, que sigue siendo el techo) y la tarjeta de «Procesar PDFs» de
      web-next lo deja bajar (por defecto queda en el techo). Verificado end-to-end: selección de 2
      con tope 1 → procesa 1.
- [ ] Decidir qué pasa con `frontend/web/` (la interfaz anterior que aún sirve `servidor.py`):
      eliminarla cuando se confirme la paridad en el recorrido de arriba. Con eso `servidor.py` queda
      solo como API.
