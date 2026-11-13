# Comandos

Todas las rutas son relativas a la raíz del proyecto (`automatización/`). Cada sección indica desde qué carpeta se ejecuta el comando.

Última actualización: 2026-11-13

## Índice

1. [Arranque rápido (la interfaz web)](#1-arranque-rápido-la-interfaz-web)
2. [Preparación inicial (solo la primera vez)](#2-preparación-inicial-solo-la-primera-vez)
3. [Base de datos (PostgreSQL)](#3-base-de-datos-postgresql)
4. [Backend y frontend](#4-backend-y-frontend)
5. [Línea de comandos: búsqueda y procesamiento](#5-línea-de-comandos-búsqueda-y-procesamiento)
6. [Pruebas de calidad](#6-pruebas-de-calidad)

---

## 1. Arranque rápido (la interfaz web)

Es lo que se usa en el día a día. Requiere el entorno ya preparado (sección 2) y las variables `NEON_*` en `.env`.

**Terminal 1: backend (API en el puerto 8000)**

```bash
source venv/bin/activate
cd api
python servidor.py
```

**Terminal 2: interfaz Next.js (puerto 3000)**

```bash
cd frontend
npm run dev
```

Se abre `http://localhost:3000`. El backend en `http://127.0.0.1:8000` es solo la API.

---

## 2. Preparación inicial (solo la primera vez)

Desde la raíz:

| Comando | Qué hace |
|---|---|
| `python3 -m venv venv` | Crea el entorno virtual (ya existe en esta máquina) |
| `source venv/bin/activate` | Lo activa. Hay que repetirlo en cada terminal nueva |
| `pip install -r requirements.txt` | Instala todo: búsqueda + procesamiento + frontend |
| `pip install -r busqueda/requirements.txt` | Instala solo lo de la búsqueda |
| `cp .env.example .env` | Crea el `.env`; luego se completan las keys (ver más abajo) |
| `deactivate` | Sale del entorno virtual |

Desde `frontend/`:

| Comando | Qué hace |
|---|---|
| `npm install` | Instala las dependencias de la interfaz Next.js (ya instaladas en esta máquina) |

### Variables del `.env`

| Variable | Obligatoria | Para qué |
|---|---|---|
| `NEON_HOST`, `NEON_DATABASE`, `NEON_USER`, `NEON_PASSWORD`, `NEON_SSL_MODE` | Sí | Conexión a PostgreSQL, un dato por variable (ver sección 3) |
| `NVIDIA_API_KEY` | Para cadenas y fichas | Nemotron |
| `NVIDIA_PARSE_API_KEY` | Para fichas con tablas | Nemotron Parse |
| `SEMANTIC_SCHOLAR_API_KEY`, `SCOPUS_API_KEY` | Opcionales | Motores de búsqueda |
| `OPENALEX_API_KEY` | Opcional | Cuota propia en OpenAlex (evita el 429) |

El modelo, las URL, las búsquedas de ejemplo y el año mínimo se cambian en `busqueda/config.py`.

---

## 3. Base de datos (PostgreSQL)

Los datos de conexión van en el `.env`, cada uno en su variable (`NEON_HOST`, `NEON_DATABASE`, `NEON_USER`, `NEON_PASSWORD`, `NEON_SSL_MODE`; ver `.env.example`); `busqueda/config.py` arma la URL. Así se cambia solo un dato (p. ej. la base de otra rama). El esquema se crea solo en la primera conexión. [Neon](https://neon.tech) tiene un plan gratuito: se crea el proyecto y se copia cada dato de su *connection string*. El nombre de la base distingue mayúsculas.

| Comando | Desde | Qué hace |
|---|---|---|
| `python probar_postgres.py` | raíz, venv activo | Conecta, crea el esquema, escribe y consulta un paper de prueba (JSONB) y lo borra. No consume ninguna API |
| `python normalizar_dois.py` | `busqueda/` | Simula la migración de DOI: lista los `paper_id` fuera del formato de `doi.py` y cuáles se fusionarían por estar duplicados. No escribe |
| `python normalizar_dois.py --aplicar` | `busqueda/` | Aplica esa migración en una transacción (renombra, fusiona duplicados y mueve sus proyectos, estructuras y fichas). Reiniciar la API después |
| `psql "postgresql://USUARIO:CLAVE@HOST/BASE?sslmode=require"` | cualquiera | Explora la base a mano. Tablas: `papers`, `proyectos`, `papers_proyectos`, `estructuras`, `fichas` |

---

## 4. Backend y frontend

### Backend (`api/servidor.py`)

Desde `api/`, con el venv activo:

| Comando | Qué hace |
|---|---|
| `python servidor.py` | Solo la API (`/api/*`) en `http://127.0.0.1:8000`; la interfaz es `frontend/`. Crea proyectos de búsqueda y, desde sus resultados, dispara «Procesar PDFs» (fichas con Nemotron Parse + Nemotron) |
| `python servidor.py 8080` | Lo mismo en otro puerto |

Rutas de la API (prefijo `/api`; cualquier otra ruta responde 404). Se prueban con `curl http://127.0.0.1:8000/api/proyectos`:

| Método y ruta | Qué hace |
|---|---|
| `GET /proyectos` · `POST /proyectos` | Lista los proyectos · crea uno vacío |
| `GET /proyectos/{id}` · `PUT` · `DELETE` | Lee, actualiza o borra un proyecto (`PUT` acepta `terminos_clave`: lista de términos obligatorios, hasta 5) |
| `POST /proyectos/{id}/aclarar` | Nemotron aclara el tema |
| `POST /proyectos/{id}/cadenas` | Genera las cadenas de búsqueda (con los `terminos_clave` del proyecto en todas; devuelve `obligatorios` con sus alternativas) |
| `POST /proyectos/{id}/buscar` · `/cancelar` | Lanza o cancela la búsqueda de papers |
| `POST /proyectos/{id}/procesar` · `/cancelar-procesar` | Lanza o cancela «Procesar PDFs» sobre los papers seleccionados (acepta `tope`; sin selección responde 400) |
| `GET /proyectos/{id}/fichas` | Fichas y estructuras ya generadas, ordenadas por relevancia (alta → nula) |
| `GET /proyectos/{id}/papers.csv` | Exporta los papers (`?seleccion=1` solo los marcados) |

### Interfaz Next.js (`frontend/`)

Necesita el backend corriendo. La API se toma de la variable `API_URL` (por defecto `http://127.0.0.1:8000`; ver `frontend/.env.example`).

Desde `frontend/`:

| Comando | Qué hace |
|---|---|
| `npm run dev` | Modo desarrollo en `http://localhost:3000` |
| `npm run build` | Compila y revisa los tipos |
| `npm run start` | Sirve la versión compilada en el puerto 3000 |
| `npm run typecheck` | Solo revisa los tipos (`tsc --noEmit`) |
| `API_URL=http://127.0.0.1:8080 npm run dev` | Igual que `dev`, pero con el backend en otro puerto |

---

## 5. Línea de comandos: búsqueda y procesamiento

Alternativa a la interfaz web. Guarda los papers en la base sin proyecto asociado. Con el venv activo.

### Búsqueda

Desde `busqueda/`:

| Comando | Qué hace |
|---|---|
| `python main.py` | Busca papers en OpenAlex, Semantic Scholar y Scopus, los rankea y los guarda en PostgreSQL. Consume cuota de las APIs y puede dar HTTP 429 |

### Procesamiento

Desde `procesamiento/`. Necesita `NVIDIA_API_KEY` y `NVIDIA_PARSE_API_KEY` en el `.env`.

| Comando | Qué hace |
|---|---|
| `python extract_ficha.py --top 20 --tema "..."` | Ficha por paper: lee abstract, penúltimo y último párrafo de la introducción, conclusiones y tablas (Nemotron Parse) y Nemotron las resume |
| `python extract_ficha.py --forzar` | Vuelve a leer y resumir aunque ya tengan ficha |
| `python lectura_pdf.py paper.pdf` | Muestra la estructura de un PDF local (prueba) |
| `python probar_nvidia.py` | Prueba mínima de conexión con Nemotron y Nemotron Parse |

### Secuencia completa sin interfaz

```bash
source venv/bin/activate
cd busqueda && python main.py
cd ../procesamiento
python extract_ficha.py --top 20 --tema "..."
```

---

## 6. Pruebas de calidad

No hay suite automatizada. Estos scripts evalúan cadenas, fichas y lectura de PDFs. Ver `pruebas/README.md` y `pruebas/CONTEXTO.md`.

### Verificaciones rápidas después de cambiar código

| Comando | Desde | Qué verifica |
|---|---|---|
| `python -m py_compile <archivo.py>` | raíz, venv activo | Sintaxis de un archivo |
| `python probar_postgres.py` | raíz | La base de datos (sin consumir APIs) |
| `python probar_nvidia.py` | `procesamiento/` | Conexión con Nemotron y Nemotron Parse |
| `python testeo_general.py` | `pruebas/` | Flujo completo contra un backend real en el puerto 8099: proyecto → cadenas → búsqueda → fichas → borrar. Consume cuota de APIs |
| `python validar_fichas.py` | `pruebas/fichas/` | Valida las fichas de los papers seleccionados de cada proyecto guardado: estructura, cifras respaldadas por el texto, acuerdo de relevancia con un juez Nemotron ciego a la ficha y fidelidad. Escribe `resultados/validar_<archivo>.json`. Consume NVIDIA |
| `python validar_fichas.py --muestra 10 --control 5` | `pruebas/fichas/` | Igual, para proyectos sin selección: 10 primeros del ranking + 5 del final como control |
| `python validar_fichas.py --sin-procesar` | `pruebas/fichas/` | Valida solo las fichas ya generadas (no lee PDFs; solo llama al juez) |

### Pruebas de cadenas

Desde `pruebas/cadenas/`. Las marcadas con (API) consumen cuota de NVIDIA u OpenAlex.

| Comando | Qué hace |
|---|---|
| `python resumen.py` | Tabla resumen de `banco_res.json` (`banco.py` se borró al vencer Azure; el JSON se conserva). Sin API |
| `python analisis_amplitud.py [--tope=N]` | Tablas del último `amplitud_res.json`. Sin API |
| `python amplitud.py [--temas=..]` (API) | Banco de amplitud: 6 variantes de ejecución de cada cadena en OpenAlex, con hits y juez 0/1/2 |
| `python rellenar.py` (API) | Repite las búsquedas que quedaron con 429 en `amplitud_res.json` (esperar la renovación del presupuesto de OpenAlex) |
| `python relevo.py [--juez=nvidia]` (API) | Corre las cadenas de amplitud por el código actual y compara cuántos papers entrega |
| `python final.py [--solo-no-en]` (API) | Estructura y tildes de las cadenas por el flujo real |
| `python modelos.py` / `python modelos2.py` (API) | Compara modelos de NVIDIA |
| `python sonda_s2.py` (API) | Qué trae Semantic Scholar (bulk por citas) para cadenas ya medidas en OpenAlex |
| `python sonda_s2_v2.py` (API) | Top por citas contra top re-rankeado local (base del cambio aplicado a Semantic Scholar) |
| `python estrictez.py [--verificar]` (API) | Escala de 6 niveles de restricción contra papers conocidos en OpenAlex (pendiente 2). Lee los papers objetivo de PostgreSQL en solo lectura |
| `python estrictez_motores.py [--papers 6]` (`pruebas/cadenas/`, venv activo) | Misma escala de 6 niveles en Scopus y Semantic Scholar: mide si el paper conocido aparece entre los primeros 100 resultados. Consume cuota de ambos motores; Semantic Scholar suele dar 429 |
