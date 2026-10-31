'use client';

import { useRef, useState } from 'react';
import { Pencil, RotateCcw } from 'lucide-react';
import { useApp } from '@/context/AppContext';
import type { Etapa } from '@/lib/tipos';
import css from './Encabezado.module.css';

const PASOS = ['Tema', 'Cadenas', 'Búsqueda', 'Resultados'];
const PASO_ACTUAL: Record<Etapa, number> = { empty: 0, queries: 1, loading: 2, results: 3 };

export function Encabezado() {
  const { proyecto, renombrar, reiniciar } = useApp();
  const [editando, setEditando] = useState(false);
  const [borrador, setBorrador] = useState('');
  const cancelado = useRef(false);

  const actual = PASO_ACTUAL[proyecto?.stage ?? 'empty'];
  const puedeReiniciar = proyecto && proyecto.stage !== 'empty' && proyecto.stage !== 'loading';

  const empezar = () => {
    if (!proyecto) return;
    cancelado.current = false;
    setBorrador(proyecto.name);
    setEditando(true);
  };

  const guardar = () => {
    if (cancelado.current) return;
    setEditando(false);
    renombrar(borrador);
  };

  return (
    <header className={css.cabecera}>
      <div className={css.izquierda}>
        {editando ? (
          <input className={`input ${css.editor}`} autoFocus value={borrador} maxLength={80} aria-label="Título del proyecto"
            onChange={(e) => setBorrador(e.target.value)} onBlur={guardar}
            onKeyDown={(e) => {
              if (e.key === 'Enter') e.currentTarget.blur();
              if (e.key === 'Escape') { cancelado.current = true; setEditando(false); }
            }} />
        ) : (
          <h1 style={{ margin: 0 }}>
            <button className={css.titulo} onClick={empezar} title="Clic para editar" disabled={!proyecto}>
              {proyecto?.name ?? 'Research Automator'}
              {proyecto && <Pencil size={16} strokeWidth={2.75} />}
            </button>
          </h1>
        )}

        <div className={css.pasos}>
          {PASOS.map((etiqueta, i) => (
            <div className={css.paso} key={etiqueta}>
              <span className={css.numero} style={{
                background: i < actual ? 'var(--color-accent-2-600)' : i === actual ? 'var(--color-accent)' : 'var(--color-neutral-300)',
                color: i <= actual ? 'var(--color-bg)' : 'var(--color-neutral-700)',
              }}>{i < actual ? '✓' : i + 1}</span>
              <span className={css.etiqueta} style={{ color: i === actual ? 'var(--color-text)' : 'var(--color-neutral-700)' }}>{etiqueta}</span>
              {i < PASOS.length - 1 && <span className={css.union} />}
            </div>
          ))}
        </div>
      </div>

      {puedeReiniciar && (
        <button className="btn btn-secondary" onClick={reiniciar}>
          <RotateCcw size={15} strokeWidth={2.75} />Reiniciar
        </button>
      )}
    </header>
  );
}
