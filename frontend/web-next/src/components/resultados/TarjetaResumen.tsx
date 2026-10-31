'use client';

import { useApp } from '@/context/AppContext';
import { descargarTexto, fichasACsv, resumenCorrida } from '@/lib/formato';
import css from './TarjetaResumen.module.css';

const ESTADOS = ['ok', 'no_relevante', 'sin_abstract', 'error', 'pendiente'];
const ETIQUETA: Record<string, string> = {
  ok: 'ok', no_relevante: 'no relevante', sin_abstract: 'sin abstract', error: 'error', pendiente: 'pendiente',
};
const COLOR: Record<string, string> = {
  ok: 'var(--color-accent-2-600)', no_relevante: 'var(--color-neutral-400)', sin_abstract: 'var(--color-accent-400)',
  error: 'var(--color-accent-800)', pendiente: 'var(--color-neutral-500)',
};

export function TarjetaResumen({ alReprocesar }: { alReprocesar: () => void }) {
  const { proyecto, fichas, procesar } = useApp();
  if (!proyecto) return null;

  const p = proyecto.procesamiento;
  const fallo = p.estado === 'error';
  const completas = fichas.filter((f) => f.cobertura === 'completa').length;
  const parciales = fichas.filter((f) => f.cobertura === 'parcial').length;
  const claves = [...ESTADOS.filter((k) => p.conteos[k]), ...Object.keys(p.conteos).filter((k) => !ESTADOS.includes(k) && p.conteos[k])];

  const exportar = () => {
    const nombre = (proyecto.archivo ?? 'proyecto').replace(/\.db$/, '');
    descargarTexto(`${nombre}_fichas.csv`, fichasACsv(fichas), 'text/csv;charset=utf-8');
  };

  return (
    <div className={css.fila}>
      <div className={css.principal}>
        <div className={css.titulo}>
          <h3>{fallo ? 'Resultados parciales' : 'Procesamiento terminado'}</h3>
          {fallo && <span className="tag tag-accent">parcial</span>}
        </div>
        <div className={css.meta}>{resumenCorrida(p)}</div>
        <div className={css.cifras}>
          <div className={css.cifra}><strong>{fichas.length}{p.total ? <small style={{ fontSize: 16 }}> / {p.total}</small> : null}</strong><span>fichas</span></div>
          <div className={`${css.cifra} ${css.verde}`}><strong>{completas}</strong><span>con PDF leído</span></div>
          <div className={`${css.cifra} ${css.naranja}`}><strong>{parciales}</strong><span>solo abstract</span></div>
        </div>
        {claves.length > 0 && (
          <div className={css.chips}>
            {claves.map((k) => (
              <span className={css.chip} key={k}><i style={{ background: COLOR[k] ?? 'var(--color-neutral-400)' }} />{ETIQUETA[k] ?? k} {p.conteos[k]}</span>
            ))}
          </div>
        )}
      </div>

      <div className={css.lateral}>
        {fallo && (
          <>
            <div className={css.error}><strong>El procesamiento se detuvo.</strong><code>{p.error || 'Error desconocido'}</code></div>
            <button className="btn btn-primary" onClick={() => procesar(p.alcance ?? 'todos')}>Reintentar</button>
          </>
        )}
        <div className={css.espacio} />
        <div className={css.botones}>
          <button className="btn btn-secondary" onClick={exportar} disabled={!fichas.length}>Exportar CSV</button>
          <button className={fallo ? 'btn btn-ghost' : 'btn btn-primary'} onClick={alReprocesar}>Volver a procesar</button>
        </div>
      </div>
    </div>
  );
}
