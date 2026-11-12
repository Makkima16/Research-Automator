# AGENTS.md — Research Automator

Guía para agentes de IA que trabajan en este repositorio. La documentación del
producto vive en `README.md`; este archivo explica cómo se trabaja acá.

## El proyecto en pocas líneas

Research Automator automatiza revisiones de literatura científica: a partir de
un tema en lenguaje natural genera cadenas booleanas (Nemotron), las ejecuta en
OpenAlex, Semantic Scholar y Scopus, rankea y deduplica resultados por DOI (formato único en `busqueda/doi.py`),
resuelve texto completo (Sci-Hub por DOI para papers de 2021 o anteriores) y
extrae fichas estructuradas con Nemotron.

Tres módulos independientes que se combinan en el frontend:

- `busqueda/` — generación de cadenas y recolección de papers. Configuración en
  `busqueda/config.py` (incluye modelo y URLs de NVIDIA; no son secretos).
- `procesamiento/` — estructura del paper (abstract, intro, conclusiones,
  tablas) y fichas. Configuración en `procesamiento/config_proc.py`.
- `api/` — `servidor.py` sirve solo la API (`/api/*`) y `almacen.py` guarda los proyectos; la
  interfaz vive aparte en `frontend/` (Next.js). Cada
  proyecto vive en sus filas de `proyectos`/`papers_proyectos` de la base
  compartida.

Persistencia: PostgreSQL (variables `NEON_*` en `.env`; psycopg3; el plan gratuito de Neon sirve). Una
sola base compartida: `papers` (pool deduplicado por `paper_id`), `proyectos` + `papers_proyectos`
(proyectos de la web, con el estado del proyecto en JSONB), `estructuras` y `fichas` (procesamiento,
payload en JSONB con índices GIN). El esquema completo está en `busqueda/database.py` y se crea solo
en la primera conexión. Los PDFs nunca se guardan en disco: se descargan a memoria. Las bases
SQLite de `busqueda/output/` son legadas de las pruebas de cadenas: el producto ya no las usa.

Documentación viva: `README.md` (arquitectura y flujo), `COMANDOS.md`
(comandos y desde dónde se ejecutan) y `PENDIENTES.md` (trabajo por hacer, con
fechas límite).
`pruebas/` reúne el contexto de las pruebas de calidad (`pruebas/CONTEXTO.md`) y los
scripts para repetirlas (`pruebas/README.md`); leerlos antes de retomar los
pendientes 1 y 2.

## Entorno

- Python 3.12. Venv en `venv/`: activar con `source venv/bin/activate` antes
  de ejecutar cualquier script del proyecto.
- Las claves van SOLO en `.env` (raíz, no versionado). Ver `.env.example`.
- Dependencias: `requirements.txt` (todo) o `busqueda/requirements.txt`
  (solo búsqueda).
- No hay suite de pruebas automatizada ni linter configurado; el
  `pyrightconfig.json` de la raíz es para Pylance/VS Code.

## Reglas de trabajo

1. **Autonomía**: para cambios normales (corregir un bug, agregar una función,
   refactors chicos) no hace falta pedir confirmación: leer, cambiar,
   verificar. Para cambios grandes (migraciones, reescribir un módulo,
   decisiones de arquitectura) proponer primero un plan corto y esperar la
   confirmación del usuario.
2. **Git**: `git push` está bloqueado por permisos y no se ejecuta nunca.
   Commits, creación de ramas, merge, rebase y pull requieren confirmación
   explícita del usuario en ese momento.
3. **Archivos intocables**: `.env` (claves) y todo `output/` (bases de datos
   generadas); ambos están bloqueados por permisos. Tampoco se edita `venv/`.
4. **No instalar dependencias ni borrar archivos sin avisar antes.**
5. **Idioma**: código, comentarios y documentación en español neutro y
   profesional.
6. Ante ambigüedad, preguntar una vez en lugar de asumir.

## Verificación después de cambiar código

Elegir según qué se tocó (no hay pruebas automatizadas):

- Sintaxis e imports: `python -m py_compile <archivo.py>` (con el venv
  activado) o importar el módulo.
- Base de datos: `python probar_postgres.py` desde la raíz — prueba mínima de
  la base PostgreSQL (conexión, esquema, JSONB, borrado en cascada); no
  consume presupuesto de ninguna API.
- Procesamiento: `cd procesamiento && python probar_nvidia.py` — prueba mínima
  de conexión con Nemotron y Nemotron Parse (consume una llamada mínima).
- Lector de PDFs: `cd procesamiento && python lectura_pdf.py <paper.pdf>` con
  un PDF local.
- API: `cd api && python servidor.py <puerto>` y probar los
  endpoints con curl.
- Búsqueda completa (`cd busqueda && python main.py`): consume presupuesto de
  las APIs y puede fallar con HTTP 429 por presupuesto compartido. No correrla
  como prueba rutinaria; solo si el usuario lo pide.

## Documentación de cambios (checklist de cierre)

Al terminar un cambio de código, sin que haya que pedirlo:

1. Correr las verificaciones que correspondan y reportar qué se corrió y con
   qué resultado.
2. Actualizar `README.md` (si cambió la arquitectura, el flujo o la
   configuración), `COMANDOS.md` (si hay comandos nuevos o diferentes) y
   `PENDIENTES.md` (si se completó o detectó un pendiente). Escribir solo
   hechos terminados, nunca planes o hipótesis en discusión.
3. Entregar un resumen final: archivos modificados, qué hace el cambio,
   verificaciones pasadas y qué quedó pendiente.

El comando `/finalizar` repite este checklist.

## Configuración de los agentes de IA (dónde vive cada cosa)

- `opencode.json` (raíz): permisos de opencode. `git push` bloqueado;
  commit, ramas, merge, rebase, pull, reset, restore, clean, `pip install`,
  `npm install` y `rm` piden confirmación; `.env` y `output/` no se editan.
- `.opencode/agent/`: subagentes de opencode (`revisor`, `db`).
- `.opencode/command/finalizar.md`: comando `/finalizar` de opencode.
- `.claude/agents/` y `.claude/commands/`: equivalentes para Claude Code.
- `.claude/settings.json`: permisos de Claude Code (misma política de git y
  de archivos).
- `~/.claude/skills/research-automator-db/` y
  `~/.claude/skills/research-automator-cadenas/`: skills del proyecto
  (autocargadas por opencode). La primera documenta el esquema SQLite legado
  (previo a la migración a PostgreSQL del 2026-10-31: para el esquema vigente,
  ver `busqueda/database.py`); la segunda, la metodología de evaluación de
  cadenas (pendientes 1 y 2 de `PENDIENTES.md`).
