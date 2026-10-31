# Pruebas de calidad (cadenas, fichas y lectura de PDFs)

Scripts de prueba usados para validar el paso de GPT-5.5/Azure a Nemotron/NVIDIA y las optimizaciones
de la búsqueda. **No** forman parte de la aplicación. Antes de usarlos, leer `CONTEXTO.md` (qué se
hizo y qué se midió) y `../PENDIENTES.md`.

## `testeo_general.py` (en esta carpeta, se ejecuta con la raíz del proyecto como cwd)

Corre el flujo completo contra un backend real levantado al vuelo: crea un proyecto de prueba,
aclara el tema, genera cadenas (Nemotron), lanza una búsqueda real en los tres motores (una cadena,
tope 5), procesa 2 papers seleccionados (estructuras + fichas con Nemotron Parse), exporta el CSV,
borra el proyecto y verifica que `busqueda/output/proyectos/` quedó igual. Consume ~6 llamadas a
NVIDIA, ~10 a los motores de búsqueda y 2 procesamientos de paper:

```bash
cd pruebas
../venv/bin/python testeo_general.py
```

## Antes de ejecutar

- Activar el entorno desde la raíz del proyecto: `source venv/bin/activate`.
- Las keys se leen del `.env` de la raíz (nunca se imprimen). Hacen falta `NVIDIA_API_KEY`;
  `NVIDIA_PARSE_API_KEY` para `testeo_general.py`; y `OPENALEX_API_KEY` para las
  corridas largas contra OpenAlex (sin key, el presupuesto compartido se agota con 429).
- **Consumen cuota.** Cada script hace decenas o cientos de llamadas (NVIDIA y OpenAlex). Si OpenAlex
  da 429 a mitad de una corrida de `amplitud.py`, las búsquedas caídas se repiten con `rellenar.py`.
- Ejecutar desde la carpeta del script: `cd pruebas/cadenas`. Los resultados se guardan en `resultados/`.
- Las bases de `busqueda/output/` solo se leen; ningún script las modifica (excepto
  `testeo_general.py`, que crea y borra un proyecto de prueba y verifica que la carpeta queda igual).

## `cadenas/`

| Script | Qué hace | Consumo aproximado |
|---|---|---|
| `resumen.py` | Tabla resumen de `resultados/banco_res.json` (estructura, ceros, mediana de resultados y precisión por condición y tema). El script que lo produjo (`banco.py`) se borró al vencer Azure; el JSON se conserva como referencia histórica. No llama a ninguna API. | ninguno |
| `final.py` | Prueba por el flujo real (`generar_con_info`): estructura y tildes en los 8 temas más 5 casos en español y «Ambos». `--solo-no-en` limita a español y «Ambos». Escribe `resultados/final_res.json`. | ~13 a 25 llamadas |
| `modelos.py` | Compara 9 modelos de NVIDIA en dos formatos (cadena escrita y grupos) sobre los 8 temas, solo estructura. Escribe `resultados/modelos_res.json`. | 144 llamadas a NVIDIA |
| `modelos2.py` | Igual, solo Mistral Large 4 y gpt-oss-20b, con 2 hilos. Escribe `resultados/modelos2_res.json`. | 32 llamadas lentas |
| `amplitud.py` | Banco de amplitud de la búsqueda: por cada cadena de `final_res.json` (más 2 temas en inglés generados al vuelo) prueba 6 variantes de ejecución en OpenAlex (base, sin comillas, pares de grupos, texto completo, OR de todo) y mide resultados y puntos del juez (Nemotron, 0/1/2). Escribe `resultados/amplitud_res.json`. `--temas=` limita temas. | ~200 llamadas a OpenAlex y ~200 al juez |
| `rellenar.py` | Repite las búsquedas que en `amplitud_res.json` quedaron con `hits = None` (429 de OpenAlex); espera solo a que el presupuesto se renueve. | las que falten |
| `relevo.py` | Corre las cadenas de `amplitud_res.json` por el código actual de `fetch_papers.py` (tope 25) y compara cuántos papers entrega contra lo que entregaba antes; el juez (Nemotron) puntúa el top nuevo. Escribe `resultados/relevo_res.json`. | ~40 a 80 llamadas a OpenAlex y ~40 al juez |
| `analisis_amplitud.py` | Tablas del último `amplitud_res.json`: global por variante, por tema, cadenas con 0 resultados y simulación del tope de la interfaz. No llama a ninguna API. | ninguno |
| `sonda_s2.py` | Qué trae Semantic Scholar (búsqueda bulk ordenada por citas, como el sistema) para 3 cadenas ya medidas en OpenAlex, con puntos del juez. Escribe `resultados/sonda_s2_res.json`. | ~6 llamadas a S2 y al juez |
| `sonda_s2_v2.py` | ¿El desvío del orden por citas se arregla re-rankeando local? Compara el top-10 por citas contra el top-10 re-rankeado (`rank_and_filter`) de un pool de 100, sobre 9 cadenas. Escribe `resultados/sonda_s2_v2_res.json`. Base del cambio aplicado a `fetch_semantic_scholar.py`. | ~10 llamadas a S2 y ~14 al juez |
| `estrictez.py` | Pruebas de estrictez (punto 2 de PENDIENTES.md): papers objetivo de los proyectos guardados (solo lectura) contra una escala de 6 niveles de restricción en OpenAlex; registra posición, total y (con `--verificar`) si el paper matchea la cadena aunque no esté en el top-300. Escribe `resultados/estrictez_res.json`. | ~70 llamadas a OpenAlex + ~25 verificaciones |
| `proyectos.json` | Datos de entrada: prompt, aclaraciones, idioma, número de cadenas y cadenas históricas de los 8 proyectos guardados. | — |

Ejemplos:

```bash
cd pruebas/cadenas
python resumen.py                      # ver el resumen de la última corrida sin gastar nada
python final.py --solo-no-en           # estructura y tildes en español y «Ambos»
```

## Datos y resultados guardados

`cadenas/resultados/*.json` conservan las corridas de 2026-10-29/30. `banco_res.json` está **incompleto** a
propósito: OpenAlex se agotó durante la corrida y muchas cadenas quedaron con `hits = None`. Los temas con datos
completos son harina de banano, INFOGEST y machine learning. Es la única referencia que queda de las cadenas
generadas por GPT-5.5 y del juez GPT-5.5 (los scripts `banco.py` y `azure_prueba.py` se borraron al vencer la
suscripción de Azure; los títulos y puntos que juzgó GPT-5.5 en `amplitud_res.json` y `relevo_res.json` tampoco
se pueden volver a generar). `amplitud_res.json` y `relevo_res.json` son del banco de amplitud (8 temas completos
tras el relleno).

## Pendientes que usan esta carpeta

- Punto 0 de `PENDIENTES.md` (re-rankeo de Semantic Scholar): hace falta medir con presupuesto de S2.
- Punto 2 (estrictez): hace falta un script nuevo; la metodología está en el skill `research-automator-cadenas`.
