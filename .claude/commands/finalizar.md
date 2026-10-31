---
description: Checklist de cierre tras un cambio en Research Automator - verificar, actualizar documentación y resumir.
---

Cerrá el cambio que acabás de hacer en Research Automator con este checklist
(seguí también las reglas de AGENTS.md):

1. **Verificar**: corre las verificaciones que correspondan al cambio
   (`python -m py_compile` de los archivos tocados; `probar_nvidia.py` si
   tocaste el procesamiento; levantar `servidor.py` y probar con curl si
   tocaste el frontend). No corras búsquedas completas (`busqueda/main.py`)
   sin confirmación: consumen presupuesto de las APIs. Reportá qué corriste y
   qué resultado dio.
2. **Documentar**: revisá si el cambio afecta `README.md`, `COMANDOS.md` o
   `PENDIENTES.md` y actualizá lo que corresponda. Solo hechos terminados:
   nada de planes, hipótesis o líneas a evaluar.
3. **Resumir**: entregá un resumen final con archivos modificados, qué hace el
   cambio, por qué, verificaciones pasadas y pendientes que quedaron.

$ARGUMENTS
