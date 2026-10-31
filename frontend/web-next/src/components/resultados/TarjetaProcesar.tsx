'use client';

import { useState } from 'react';
import { FileText } from 'lucide-react';
import { useApp } from '@/context/AppContext';
import { plural } from '@/lib/formato';
import type { Alcance } from '@/lib/tipos';
import css from './TarjetaProcesar.module.css';

interface Props {
  puedeVolver: boolean;
  alVolver: () => void;
  alProcesar: () => void;
}

// Elegir qué papers procesar. El tope por corrida lo sugiere el servidor (y es el
// techo); el usuario puede bajarlo, por ejemplo para ir viendo resultados de a poco.
export function TarjetaProcesar({ puedeVolver, alVolver, alProcesar }: Props) {
  const { proyecto, procesar } = useApp();
  const [eleccion, setEleccion] = useState<Alcance | null>(null);
  const [topePedido, setTopePedido] = useState<number | null>(null);
  if (!proyecto) return null;

  const proc = proyecto.procesamiento;
  const ids = new Set(proyecto.papers.map((p) => p.id));
  const nSel = proyecto.seleccion.filter((id) => ids.has(id)).length;
  const nTodos = proyecto.papers.length;
  const alcance: Alcance = (eleccion ?? (nSel ? 'sel' : 'todos')) === 'sel' && nSel ? 'sel' : 'todos';
  const techo = proc.tope || Infinity;          // máximo que acepta el servidor
  const tope = topePedido ?? techo;             // lo que pidió el usuario (o el máximo)
  const pedidos = alcance === 'sel' ? nSel : nTodos;
  const n = Math.min(pedidos, tope);

  const cambiarTope = (texto: string) => {
    const v = parseInt(texto, 10);
    setTopePedido(Number.isNaN(v) ? null : Math.max(1, Math.min(v, techo)));
  };

  const explicacion = (alcance === 'sel'
    ? `Se procesarán los ${plural(n, 'paper marcado', 'papers marcados')} en Resultados de búsqueda.`
    : `Se procesarán los ${plural(n, 'paper', 'papers')} del proyecto.`)
    + (pedidos > tope ? ` Son ${pedidos}, pero cada corrida procesa como máximo ${tope}.` : '')
    + ' Solo los de acceso abierto se leen completos; del resto se resume el abstract y la ficha queda como parcial.'
    + (proc.estado ? ' Los papers que ya tienen ficha no se vuelven a leer.' : '');

  return (
    <div className={`${css.tarjeta} fade-in`}>
      <div className={css.circuloGrande} />
      <div className={css.circuloChico} />
      <div className={css.contenido}>
        <h3>Procesar PDFs</h3>
        <p>Nemotron lee cada paper (abstract, introducción, conclusiones y tablas) y arma una ficha estructurada.</p>

        <div className={css.etiqueta}>Alcance</div>
        <div className={css.alcances}>
          <label className="radio" data-bloqueado={!nSel}>
            <input type="radio" name="alcance" checked={alcance === 'sel'} disabled={!nSel} onChange={() => setEleccion('sel')} />
            <span className="dot" />Selección ({nSel})
          </label>
          <label className="radio">
            <input type="radio" name="alcance" checked={alcance === 'todos'} onChange={() => setEleccion('todos')} />
            <span className="dot" />Todos ({nTodos})
          </label>
        </div>

        <div className={css.etiqueta}>Máx. papers por corrida</div>
        <input className={`input ${css.tope}`} type="number" min={1} max={techo}
               value={tope === Infinity ? '' : tope} onChange={(e) => cambiarTope(e.target.value)} />
        <p className={css.explicacion}>{explicacion}</p>

        <div className={css.acciones}>
          <button className={`btn btn-primary ${css.procesar}`} disabled={!n}
                  onClick={() => { procesar(alcance, tope === techo ? undefined : tope); alProcesar(); }}>
            <FileText size={16} strokeWidth={2.75} />Procesar {plural(n, 'paper', 'papers')}
          </button>
          {puedeVolver && <button className="btn btn-ghost" onClick={alVolver}>Volver</button>}
        </div>
        <p className={css.nota} style={{ marginTop: 12 }}>Puede tardar varios minutos. El proceso sigue en el servidor si sales de la página.</p>
      </div>
    </div>
  );
}
