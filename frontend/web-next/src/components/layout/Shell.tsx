'use client';

import { useApp } from '@/context/AppContext';
import { Dialogo } from '@/components/ui/Dialogo';
import { Toast } from '@/components/ui/Toast';
import { VistaBusqueda } from '@/components/vistas/VistaBusqueda';
import { VistaCadenas } from '@/components/vistas/VistaCadenas';
import { VistaPrompt } from '@/components/vistas/VistaPrompt';
import { VistaResultados } from '@/components/vistas/VistaResultados';
import { Aviso } from './Aviso';
import { Encabezado } from './Encabezado';
import { Sidebar } from './Sidebar';
import css from './Shell.module.css';

function Vista() {
  const { proyecto } = useApp();
  switch (proyecto?.stage) {
    case 'queries': return <VistaCadenas key={proyecto.id} />;
    case 'loading': return <VistaBusqueda key={proyecto.id} />;
    case 'results': return <VistaResultados key={proyecto.id} />;
    default: return <VistaPrompt key={proyecto?.id ?? 'borrador'} />;
  }
}

export function Shell() {
  const { cargando } = useApp();
  return (
    <div className={css.shell}>
      <Sidebar />
      <main className={css.main}>
        <Encabezado />
        <div className={css.contenido}>
          <Aviso />
          {!cargando && <Vista />}
        </div>
      </main>
      <Dialogo />
      <Toast />
    </div>
  );
}
