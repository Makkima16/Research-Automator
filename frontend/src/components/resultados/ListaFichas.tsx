'use client';

import { useMemo, useState } from 'react';
import { Search } from 'lucide-react';
import { useApp } from '@/context/AppContext';
import type { Ficha } from '@/lib/tipos';
import { FichaItem } from './FichaItem';
import css from './ListaFichas.module.css';

type Filtro = 'utiles' | 'alta' | 'baja' | 'nula' | 'todas';

// Las fichas ya llegan ordenadas por relevancia (alta, media, baja, nula)
const FILTROS: { clave: Filtro; etiqueta: string; pasa: (f: Ficha) => boolean }[] = [
  { clave: 'utiles', etiqueta: 'Útiles', pasa: (f) => f.relevancia === 'alta' || f.relevancia === 'media' },
  { clave: 'alta', etiqueta: 'Solo alta', pasa: (f) => f.relevancia === 'alta' },
  { clave: 'baja', etiqueta: 'Tangenciales', pasa: (f) => f.relevancia === 'baja' },
  { clave: 'nula', etiqueta: 'No relevantes', pasa: (f) => f.relevancia === 'nula' },
  { clave: 'todas', etiqueta: 'Todas', pasa: () => true },
];

const textoDe = (f: Ficha) => [
  f.title, f.en_una_frase, f.motivo_relevancia, f.aporte_al_tema, f.objetivo, f.metodo?.tipo_estudio,
  f.metodo?.poblacion, f.metodo?.contexto, f.abstract, f.intro_penultimo, f.intro_ultimo, f.conclusion_texto,
  ...f.conclusiones, ...f.hallazgos_clave, ...f.limitaciones, ...f.tablas.map((t) => t.nombre),
].join(' ').toLowerCase();

export function ListaFichas() {
  const { fichas } = useApp();
  const [q, setQ] = useState('');
  const [filtro, setFiltro] = useState<Filtro>('utiles');
  const [abiertas, setAbiertas] = useState<Set<string>>(new Set());

  const porTexto = useMemo(() => {
    const t = q.trim().toLowerCase();
    return t ? fichas.filter((f) => textoDe(f).includes(t)) : fichas;
  }, [fichas, q]);
  const visibles = porTexto.filter(FILTROS.find((f) => f.clave === filtro)!.pasa);

  const alternar = (id: string) => setAbiertas((s) => {
    const nuevo = new Set(s);
    if (!nuevo.delete(id)) nuevo.add(id);
    return nuevo;
  });

  return (
    <div>
      <div className={css.cabecera}>
        <h3>Fichas</h3>
        <div className={css.buscador}>
          <Search size={15} strokeWidth={2.75} />
          <input className="input" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Buscar en las fichas"
            placeholder="Buscar en las fichas…" />
        </div>
        <div className={`seg ${css.segmento}`}>
          {FILTROS.map(({ clave, etiqueta, pasa }) => (
            <label className="seg-opt" key={clave}>
              <input type="radio" name="filtro-fichas" checked={filtro === clave} onChange={() => setFiltro(clave)} />
              {etiqueta}<small>{porTexto.filter(pasa).length}</small>
            </label>
          ))}
        </div>
        <div className={css.espacio} />
        {visibles.length > 0 && (
          <>
            <button className="btn btn-ghost" onClick={() => setAbiertas(new Set(visibles.map((f) => f.paper_id)))}>Expandir todo</button>
            <button className="btn btn-ghost" onClick={() => setAbiertas(new Set())}>Colapsar todo</button>
          </>
        )}
      </div>

      <div className={css.lista}>
        {visibles.map((f) => <FichaItem key={f.paper_id} ficha={f} abierta={abiertas.has(f.paper_id)} alternar={() => alternar(f.paper_id)} />)}
        {visibles.length === 0 && (
          <div className={css.vacio}>
            Ninguna ficha coincide con los filtros.{' '}
            <button className="btn btn-ghost" onClick={() => { setQ(''); setFiltro('todas'); }}>Limpiar filtros</button>
          </div>
        )}
      </div>
    </div>
  );
}
