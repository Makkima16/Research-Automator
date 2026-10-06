"""
Punto de entrada de la búsqueda. Corre con:

    python main.py

Busca papers en tres plataformas independientes, OpenAlex, Semantic Scholar y
Scopus (ver fetch_papers.py, fetch_semantic_scholar.py y
fetch_scopus.py), y los combina: config.MAX_RESULTS_PER_QUERY papers
por cada cadena en cada plataforma, con una pausa de
config.PAUSA_ENTRE_PETICIONES_S segundos entre solicitudes. Para los
papers mejor rankeados revisa además si su PDF de acceso abierto en realidad
se puede descargar o está bloqueado, probando una copia alternativa en la
otra plataforma cuando hace falta. Los que siguen sin PDF accesible se buscan
por DOI en un cuarto motor, Sci-Hub (ver fetch_scihub.py).

Guarda todo en la base de datos output/selema.db (tablas papers y
alimentos_usda). Cada paper queda
marcado con qué plataforma(s) lo encontraron (motor_busqueda), cuál dio el
PDF que se usó (motor_pdf) y si ese PDF está bloqueado (pdf_bloqueado).

Después, el procesamiento de los papers (carpeta ../procesamiento):
    python fetch_fulltext.py         # texto completo de los papers de acceso abierto
    python extract_llm_insights.py   # el LLM extrae observaciones a la base
    python build_dataset.py          # genera output/tabla_arbol.csv
    python arbol_decision.py         # entrena el árbol de decisiones
"""

import os
import sys

import config
import database
import fetch_papers
import fetch_scihub
import fetch_scopus
import fetch_semantic_scholar
import fetch_usda
import rank_and_filter


def recolectar_papers(dois_existentes):
    """Busca en OpenAlex, Semantic Scholar y Scopus, hasta
    config.MAX_RESULTS_PER_QUERY papers por cada cadena en cada plataforma, y
    los combina por DOI. Devuelve (todos, los que no estaban ya en la base)."""
    limite = config.MAX_RESULTS_PER_QUERY
    print(f"-- Buscando hasta {limite} papers por cadena en cada plataforma --")

    print("== Paso 1a: recolectando papers desde OpenAlex ==")
    papers_openalex = fetch_papers.fetch_all(
        config.PAPER_QUERIES, config.CONTACT_EMAIL, config.MIN_PUBLICATION_YEAR, limite,
    )
    print(f"  {len(papers_openalex)} papers únicos desde OpenAlex")

    if config.USAR_SEMANTIC_SCHOLAR:
        print("== Paso 1b: recolectando papers desde Semantic Scholar ==")
        papers_semantic_scholar = fetch_semantic_scholar.fetch_all(
            config.PAPER_QUERIES, config.SEMANTIC_SCHOLAR_API_KEY, config.MIN_PUBLICATION_YEAR, limite,
        )
        print(f"  {len(papers_semantic_scholar)} papers únicos desde Semantic Scholar")
    else:
        print("== Paso 1b: Semantic Scholar desactivado (config.USAR_SEMANTIC_SCHOLAR = False) ==")
        papers_semantic_scholar = []

    if config.USAR_SCOPUS:
        print("== Paso 1c: recolectando papers desde Scopus ==")
        papers_scopus = fetch_scopus.fetch_all(
            config.PAPER_QUERIES, config.SCOPUS_API_KEY, config.MIN_PUBLICATION_YEAR, limite,
        )
        print(f"  {len(papers_scopus)} papers únicos desde Scopus")
    else:
        print("== Paso 1c: Scopus desactivado (config.USAR_SCOPUS = False) ==")
        papers_scopus = []

    papers = fetch_semantic_scholar.fusionar_por_doi(papers_openalex, papers_scopus, "Scopus")
    papers = fetch_semantic_scholar.fusionar_por_doi(papers, papers_semantic_scholar, "Semantic Scholar")
    nuevos = [p for p in papers if p.get("doi") not in dois_existentes]
    print(f"  {len(papers)} papers en total; {len(nuevos)} no estaban ya en la base")
    return papers, nuevos


def main():
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)

    dois_existentes = set()
    if os.path.exists(config.DB_PATH):
        conn_previa = database.conectar(config.DB_PATH)
        dois_existentes = database.dois_existentes(conn_previa)
        conn_previa.close()
    print(f"Ya hay {len(dois_existentes)} papers guardados.\n")

    papers, nuevos = recolectar_papers(dois_existentes)
    if not papers:
        print("\n[ERROR] Ninguna de las dos plataformas devolvió papers (revisa los avisos de arriba: "
              "suele ser OpenAlex/Semantic Scholar saturados con 429, o sin conexión). Por seguridad no "
              "se escribe nada: la base de datos queda como estaba. "
              "Espera un momento y vuelve a correr python main.py.")
        sys.exit(1)

    print(f"  {len(papers)} papers en total ({len(nuevos)} nuevos)")

    print("== Paso 2: rankeando papers ==")
    all_keywords = [w for q in config.PAPER_QUERIES for w in q.split()]
    ranked = rank_and_filter.rank_papers(papers, all_keywords)

    print(f"== Paso 2b: revisando acceso al PDF de los {config.MAX_PAPERS_VERIFICAR_PDF} mejor rankeados ==")
    revisados = fetch_semantic_scholar.revisar_acceso_pdf(
        ranked, config.SEMANTIC_SCHOLAR_API_KEY, config.MAX_PAPERS_VERIFICAR_PDF,
        usar_alterna=config.USAR_SEMANTIC_SCHOLAR,
    )
    bloqueados = sum(1 for p in revisados if p.get("pdf_bloqueado") == "si")
    print(f"  {bloqueados} de {len(revisados)} tienen el PDF bloqueado (columna pdf_bloqueado)")

    if config.USAR_SCIHUB:
        print("== Paso 2c: buscando en Sci-Hub los que quedaron sin PDF accesible ==")
        en_scihub = fetch_scihub.completar(revisados, config.SCIHUB_MIRRORS, config.MAX_PAPERS_SCIHUB)
        print(f"  {en_scihub} papers encontrados en Sci-Hub (motor_pdf = scihub)")
    else:
        print("== Paso 2c: Sci-Hub desactivado (config.USAR_SCIHUB = False) ==")

    print("== Paso 3: recolectando composición de lácteos desde USDA FoodData Central ==")
    foods = fetch_usda.fetch_all(config.USDA_QUERIES, config.USDA_API_KEY)
    if foods:
        print(f"  {len(foods)} alimentos encontrados")
    else:
        print("  No llegó ningún alimento; se conservan los que ya estaban en la base")

    print("== Paso 4: guardando en la base de datos ==")
    conn = database.conectar(config.DB_PATH)
    database.guardar_papers(conn, ranked)
    database.guardar_alimentos(conn, foods)
    borrados = database.limpiar_alimentos(conn)
    if borrados:
        print(f"  {borrados} alimentos que no son lácteos eliminados de la base")
    conn.close()
    print(f"  Base de datos actualizada en {config.DB_PATH}")

    print("\nListo. Siguiente paso (opcional): python ../procesamiento/fetch_fulltext.py")


if __name__ == "__main__":
    main()