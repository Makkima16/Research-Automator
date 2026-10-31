'use client';

import { useEffect, useState } from 'react';
import { Leaf, Plus, Trash2 } from 'lucide-react';
import { useApp } from '@/context/AppContext';
import type { Etapa } from '@/lib/tipos';
import css from './Sidebar.module.css';

const ETAPA: Record<Etapa, { texto: string; color: string }> = {
  empty: { texto: 'Sin empezar', color: 'var(--color-neutral-400)' },
  queries: { texto: 'Cadenas listas', color: 'var(--color-accent-400)' },
  loading: { texto: 'Buscando…', color: 'var(--color-accent)' },
  results: { texto: 'Con resultados', color: 'var(--color-accent-2-600)' },
};

export function Sidebar() {
  const { proyectos, proyecto, seleccionarProyecto, nuevoProyecto, eliminarProyecto } = useApp();
  const [host, setHost] = useState('');
  useEffect(() => setHost(window.location.host), []);

  return (
    <aside className={css.aside}>
      <div className={css.panel}>
        <div className={css.marca}>
          <span className={css.logo}><Leaf size={17} strokeWidth={2.75} /></span>
          <div className={css.nombre}>Research<br />Automator</div>
        </div>

        <div className={css.cabecera}>
          <span className={css.titulo}>Proyectos</span>
          <button className={`btn btn-primary btn-icon ${css.nuevo}`} title="Nuevo proyecto" aria-label="Nuevo proyecto" onClick={nuevoProyecto}>
            <Plus size={15} strokeWidth={2.75} />
          </button>
        </div>

        <div className={css.lista}>
          {proyectos.length === 0 && <div className={css.vacio}>Sin proyectos todavía</div>}
          {proyectos.map((p) => {
            const activo = p.id === proyecto?.id;
            const etapa = ETAPA[p.stage];
            return (
              <div key={p.id} className={`${css.item} ${activo ? css.itemActivo : ''}`} role="button" tabIndex={0}
                onClick={() => seleccionarProyecto(p.id)}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); seleccionarProyecto(p.id); } }}>
                <span className={css.punto} style={{ background: etapa.color }} />
                <div className={css.texto}>
                  <div className={css.itemNombre} title={p.name}>{p.name}</div>
                  <div className={css.itemMeta}>{etapa.texto}</div>
                </div>
                {activo && (
                  <button className={`btn btn-icon ${css.borrar}`} title="Eliminar proyecto" aria-label={`Eliminar el proyecto ${p.name}`}
                    onClick={(e) => { e.stopPropagation(); eliminarProyecto(p.id); }}>
                    <Trash2 size={14} strokeWidth={2.75} />
                  </button>
                )}
              </div>
            );
          })}
        </div>

        <div className={css.pie}><span>local</span><span>{host}</span></div>
      </div>
    </aside>
  );
}
