Entorno (venv)

┌────────────────────────────────────┬────────────────────────────────────┐
│              Comando               │              Qué hace              │
├────────────────────────────────────┼────────────────────────────────────┤
│ python3 -m venv venv               │ Crea el entorno (solo la primera   │
│                                    │ vez; ya existe)                    │
├────────────────────────────────────┼────────────────────────────────────┤
│ source venv/bin/activate           │ Lo activa (hazlo en cada terminal  │
│                                    │ nueva)                             │
├────────────────────────────────────┼────────────────────────────────────┤
│ pip install -r requirements.txt    │ Instala todo: búsqueda +           │
│                                    │ procesamiento                      │
├────────────────────────────────────┼────────────────────────────────────┤
│ pip install -r                     │ Instala solo lo de la búsqueda     │
│ busqueda/requirements.txt          │                                    │
├────────────────────────────────────┼────────────────────────────────────┤
│ deactivate                         │ Sale del entorno                   │
└────────────────────────────────────┴────────────────────────────────────┘

Búsqueda

┌─────────────┬───────────────────────────────────────────────────────────┐
│   Comando   │                         Qué hace                          │
├─────────────┼───────────────────────────────────────────────────────────┤
│ cd busqueda │ Entra a la carpeta                                        │
├─────────────┼───────────────────────────────────────────────────────────┤
│ python      │ Busca papers (OpenAlex, Semantic Scholar, Scopus), los    │
│ main.py     │ rankea y guarda todo en busqueda/output/                  │
└─────────────┴───────────────────────────────────────────────────────────┘

Las búsquedas, el año mínimo y las keys se cambian en busqueda/config.py.

Procesamiento

Primero cd procesamiento.

┌───────────────────────────────────────┬─────────────────────────────────┐
│                Comando                │            Qué hace             │
├───────────────────────────────────────┼─────────────────────────────────┤
│ python extract_ficha.py --top 20      │ Ficha por paper: lee abstract,  │
│ --tema "..."                          │ penúltimo y último párrafo de   │
│                                       │ la intro, conclusiones y tablas │
│                                       │ (Nemotron Parse) y Nemotron las │
│                                       │ resume (lo que usa              │
│                                       │ la interfaz web)                │
├───────────────────────────────────────┼─────────────────────────────────┤
│ python extract_ficha.py --forzar      │ Vuelve a leer y resumir aunque  │
│                                       │ ya tengan ficha                 │
├───────────────────────────────────────┼─────────────────────────────────┤
│ python lectura_pdf.py paper.pdf       │ Estructura de un PDF local      │
│                                       │ (prueba)                        │
├───────────────────────────────────────┼─────────────────────────────────┤
│ python probar_nvidia.py               │ Prueba mínima de conexión con   │
│                                       │ Nemotron y Nemotron Parse       │
└───────────────────────────────────────┴─────────────────────────────────┘

extract_ficha.py necesita, en el .env de la raíz, NVIDIA_API_KEY (Nemotron) y
NVIDIA_PARSE_API_KEY (Nemotron Parse). El modelo y las URL van en
busqueda/config.py (no son secretos).

Frontend (interfaz web)

┌──────────────────┬──────────────────────────────────────────────────────┐
│      Comando     │                        Qué hace                       │
├──────────────────┼──────────────────────────────────────────────────────┤
│ cd frontend      │ Entra a la carpeta                                    │
├──────────────────┼──────────────────────────────────────────────────────┤
│ python servidor.py│ Abre http://127.0.0.1:8000: crea proyectos de        │
│                   │ búsqueda y, desde sus resultados, dispara "Procesar  │
│                   │ PDFs" (fichas con Nemotron Parse + Nemotron)   │
│                   │ sobre la base propia de ese proyecto                 │
├──────────────────┼──────────────────────────────────────────────────────┤
│ python servidor.py│ Lo mismo, en otro puerto                             │
│ 8080              │                                                       │
└──────────────────┴──────────────────────────────────────────────────────┘

Frontend Next.js (interfaz nueva; necesita el backend de arriba corriendo)

Se ejecuta desde frontend/web-next. La API se toma de la variable API_URL
(por defecto http://127.0.0.1:8000; ver frontend/web-next/.env.example).

┌──────────────────────┬──────────────────────────────────────────────────┐
│       Comando        │                    Qué hace                       │
├──────────────────────┼──────────────────────────────────────────────────┤
│ cd frontend/web-next │ Entra al módulo Next.js                           │
├──────────────────────┼──────────────────────────────────────────────────┤
│ npm install          │ Instala sus dependencias (solo la primera vez)    │
├──────────────────────┼──────────────────────────────────────────────────┤
│ npm run dev          │ Modo desarrollo en http://localhost:3000          │
├──────────────────────┼──────────────────────────────────────────────────┤
│ npm run build        │ Compila y revisa tipos                            │
├──────────────────────┼──────────────────────────────────────────────────┤
│ npm run start        │ Sirve la versión compilada en el puerto 3000      │
├──────────────────────┼──────────────────────────────────────────────────┤
│ npm run typecheck    │ Solo revisa los tipos (tsc --noEmit)              │
├──────────────────────┼──────────────────────────────────────────────────┤
│ API_URL=http://127.0.0.1:8080 npm run dev                                │
│                      │ Si el backend corre en otro puerto                │
└──────────────────────┴──────────────────────────────────────────────────┘

Secuencia completa (línea de comandos, sin el frontend)

source venv/bin/activate
cd busqueda && python main.py
cd ../procesamiento
python extract_ficha.py --top 20 --tema "..."

Pruebas de calidad (cadenas, fichas y lectura de PDFs)

Primero cd pruebas/cadenas. Consumen cuota de NVIDIA y OpenAlex; ver
pruebas/README.md y pruebas/CONTEXTO.md.

┌───────────────────────────────────────┬─────────────────────────────────┐
│                Comando                │            Qué hace             │
├───────────────────────────────────────┼─────────────────────────────────┤
│ python resumen.py                     │ Tabla resumen de banco_res.json │
│                                       │ (banco.py se borró al vencer    │
│                                       │ Azure; el JSON se conserva).    │
│                                       │ No llama a ninguna API          │
├───────────────────────────────────────┼─────────────────────────────────┤
│ python final.py [--solo-no-en]        │ Estructura y tildes de las      │
│                                       │ cadenas por el flujo real       │
├───────────────────────────────────────┼─────────────────────────────────┤
│ python modelos.py | modelos2.py       │ Compara modelos de NVIDIA       │
├───────────────────────────────────────┼─────────────────────────────────┤
│ python amplitud.py [--temas=..]       │ Banco de amplitud: 6 variantes  │
│                                       │ de ejecución de cada cadena en  │
│                                       │ OpenAlex, con hits y juez 0/1/2 │
├───────────────────────────────────────┼─────────────────────────────────┤
│ python rellenar.py                    │ Repite las búsquedas que en     │
│                                       │ amplitud_res.json quedaron con  │
│                                       │ 429 (espera la renovación del   │
│                                       │ presupuesto de OpenAlex)        │
├───────────────────────────────────────┼─────────────────────────────────┤
│ python relevo.py [--juez=nvidia]      │ Corre las cadenas de amplitud   │
│                                       │ por el código actual y compara  │
│                                       │ cuántos papers entrega          │
├───────────────────────────────────────┼─────────────────────────────────┤
│ python analisis_amplitud.py [--tope=N]│ Tablas del último              │
│                                       │ amplitud_res.json (no llama a   │
│                                       │ ninguna API)                    │
├───────────────────────────────────────┼─────────────────────────────────┤
│ python sonda_s2.py                    │ Qué trae Semantic Scholar (bulk │
│                                       │ por citas) para cadenas ya      │
│                                       │ medidas en OpenAlex             │
├───────────────────────────────────────┼─────────────────────────────────┤
│ python sonda_s2_v2.py                 │ Top por citas vs top re-ran-    │
│                                       │ keado local (base del cambio    │
│                                       │ aplicado a S2)                  │
├───────────────────────────────────────┼─────────────────────────────────┤
│ python estrictez.py [--verificar]     │ Escala de 6 niveles de          │
│                                       │ restricción contra papers       │
│                                       │ conocidos (punto 2)             │
├───────────────────────────────────────┼─────────────────────────────────┤
│ python ../testeo_general.py           │ Flujo completo contra un        │
│ (desde pruebas/, no cadenas/)         │ backend real: proyecto → cadenas│
│                                       │ → búsqueda → fichas → CSV →     │
│                                       │ borrar (deja output/ igual)     │
└───────────────────────────────────────┴─────────────────────────────────┘
