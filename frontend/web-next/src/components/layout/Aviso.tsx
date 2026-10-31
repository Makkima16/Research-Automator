'use client';

import { useState } from 'react';
import { X } from 'lucide-react';
import { useApp } from '@/context/AppContext';
import css from './Aviso.module.css';

// Muestra el último error de una acción o el aviso que dejó el servidor en el proyecto
export function Aviso() {
  const { error, limpiarError, proyecto } = useApp();
  const [oculto, setOculto] = useState<string | null>(null);
  const texto = error || proyecto?.aviso || null;
  if (!texto || texto === oculto) return null;

  return (
    <div className={css.aviso} role="status">
      <span className={css.punto} />
      <span className={css.texto}>{texto}</span>
      <button className={`btn btn-icon ${css.cerrar}`} aria-label="Cerrar aviso"
        onClick={() => { if (error) limpiarError(); setOculto(texto); }}>
        <X size={14} strokeWidth={2.75} />
      </button>
    </div>
  );
}
