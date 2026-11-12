'use client';

import { useState } from 'react';
import { FileText } from 'lucide-react';
import { useApp } from '@/context/AppContext';
import { plural } from '@/lib/formato';
import css from './TarjetaProcesar.module.css';

interface Props {
  puedeVolver: boolean;
  alVolver: () => void;
  alProcesar: () => void;
}

// Procesa solo los papers marcados en Resultados de búsqueda. El tope por corrida lo
// sugiere el servidor (y es el techo); el usuario puede bajarlo, por ejemplo para ir
// viendo resultados de a poco.
export function TarjetaProcesar({ puedeVolver, alVolver, alProcesar }: Props) {
  const { proyecto, procesar, setPestana } = useApp();
  const [topePedido, setTopePedido] = useState<number | null>(null);
  if (!proyecto) return null;

  const proc = proyecto.procesamiento;
  const ids = new Set(proyecto.papers.map((p) => p.id));
  const nSel = proyecto.seleccion.filter((id) => ids.has(id)).length;
  const techo = proc.tope || Infinity;          // máximo que acepta el servidor
  const tope = topePedido ?? techo;             // lo que pidió el usuario (o el máximo)
  const n = Math.min(nSel, tope);

  const cambiarTope = (texto: string) => {
    const v = parseInt(texto, 10);
    setTopePedido(Number.isNaN(v) ? null : Math.max(1, Math.min(v, techo)));
  };

  const explicacion = `Se procesarán los ${plural(n, 'paper marcado', 'papers marcados')} en Resultados de búsqueda.`
    + (nSel > tope ? ` Son ${nSel}, pero cada corrida procesa como máximo ${tope}.` : '')
    + ' Solo los de acceso abierto se leen completos; del resto se resume el abstract y la ficha queda como parcial.'
    + (proc.estado ? ' Los papers que ya tienen ficha no se vuelven a leer.' : '');

  return (
    <div className={`${css.tarjeta} fade-in`}>
      <div className={css.circuloGrande} />
      <div className={css.circuloChico} />
      <div className={css.contenido}>
        <h3>Procesar PDFs</h3>
        <p>Nemotron lee cada paper seleccionado (abstract, introducción, conclusiones y tablas) y arma una ficha
          con lo esencial y qué tan útil es para tu tema.</p>

        {nSel === 0 ? (
          <div className={css.sinSeleccion}>
            <p>Todavía no has marcado ningún paper. Elige en Resultados de búsqueda los que quieras procesar.</p>
            <button className="btn btn-secondary" onClick={() => setPestana('busqueda')}>Ir a Resultados de búsqueda</button>
          </div>
        ) : (
          <>
            <div className={css.etiqueta}>Papers seleccionados</div>
            <p className={css.cantidad}>{plural(nSel, 'paper', 'papers')}</p>

            <div className={css.etiqueta}>Máx. papers por corrida</div>
            <input className={`input ${css.tope}`} type="number" min={1} max={techo}
                   value={tope === Infinity ? '' : tope} onChange={(e) => cambiarTope(e.target.value)} />
            <p className={css.explicacion}>{explicacion}</p>
          </>
        )}

        <div className={css.acciones}>
          <button className={`btn btn-primary ${css.procesar}`} disabled={!n}
                  onClick={() => { procesar('sel', tope === techo ? undefined : tope); alProcesar(); }}>
            <FileText size={16} strokeWidth={2.75} />Procesar {plural(n, 'paper', 'papers')}
          </button>
          {puedeVolver && <button className="btn btn-ghost" onClick={alVolver}>Volver</button>}
        </div>
        <p className={css.nota} style={{ marginTop: 12 }}>Puede tardar varios minutos. El proceso sigue en el servidor si sales de la página.</p>
      </div>
    </div>
  );
}
