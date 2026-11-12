'use client';

import { useApp } from '@/context/AppContext';

// Confirmación modal; reemplaza a window.confirm
export function Dialogo() {
  const { confirmacion } = useApp();
  if (!confirmacion) return null;
  const { titulo, cuerpo, etiqueta, resolver } = confirmacion;
  return (
    <div className="dialog-backdrop" style={{ zIndex: 40 }} onClick={() => resolver(false)}>
      <div className="dialog" role="alertdialog" aria-labelledby="dialogo-titulo" style={{ background: 'var(--color-neutral-100)' }}
        onClick={(e) => e.stopPropagation()}>
        <div className="dialog-title" id="dialogo-titulo">{titulo}</div>
        <div className="dialog-body">{cuerpo}</div>
        <div className="dialog-actions">
          <button className="btn btn-secondary" onClick={() => resolver(false)}>Cancelar</button>
          <button className="btn btn-primary" autoFocus onClick={() => resolver(true)}>{etiqueta}</button>
        </div>
      </div>
    </div>
  );
}
