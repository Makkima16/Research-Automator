'use client';

import { useState } from 'react';
import { useApp } from '@/context/AppContext';
import { PanelPaper } from '@/components/resultados/PanelPaper';
import { TabBusqueda } from '@/components/resultados/TabBusqueda';
import { TabProcesamiento } from '@/components/resultados/TabProcesamiento';
import css from './VistaResultados.module.css';

export function VistaResultados() {
  const { proyecto, fichas, pestana, setPestana } = useApp();
  const [panelId, setPanelId] = useState<string | null>(null);
  if (!proyecto) return null;

  const proc = proyecto.procesamiento;
  const insignia = proc.activo ? <span className={css.vivo}>en curso</span>
    : proc.estado === 'error' ? <span className="tag tag-accent">error</span>
    : fichas.length ? <span className={css.contador}>{fichas.length}</span> : null;

  const cambiar = (p: 'busqueda' | 'procesamiento') => { setPanelId(null); setPestana(p); };

  return (
    <section className="fade-in">
      <div className={css.pestanas} role="tablist">
        <button role="tab" aria-selected={pestana === 'busqueda'} onClick={() => cambiar('busqueda')}
          className={`${css.pestana} ${pestana === 'busqueda' ? css.activa : ''}`}>
          Resultados de búsqueda<span className={css.contador}>{proyecto.papers.length}</span>
        </button>
        <button role="tab" aria-selected={pestana === 'procesamiento'} onClick={() => cambiar('procesamiento')}
          className={`${css.pestana} ${pestana === 'procesamiento' ? css.activa : ''}`}>
          Resultados de procesamiento{insignia}
        </button>
      </div>

      {pestana === 'busqueda'
        ? <TabBusqueda panelId={panelId} abrir={setPanelId} />
        : <TabProcesamiento />}

      <PanelPaper id={panelId} cerrar={() => setPanelId(null)} />
    </section>
  );
}
