'use client';

import { useState } from 'react';
import { useApp } from '@/context/AppContext';
import { ListaFichas } from './ListaFichas';
import { TarjetaEnCurso } from './TarjetaEnCurso';
import { TarjetaProcesar } from './TarjetaProcesar';
import { TarjetaResumen } from './TarjetaResumen';

// Según el estado de la corrida: elegir alcance, seguir el avance o ver el resultado con sus fichas
export function TabProcesamiento() {
  const { proyecto, fichas } = useApp();
  const [configurando, setConfigurando] = useState(false);
  if (!proyecto) return null;

  const proc = proyecto.procesamiento;
  const eligiendoAlcance = !proc.estado || configurando;

  return (
    <div style={{ maxWidth: 1040 }}>
      {proc.activo && <TarjetaEnCurso />}
      {!proc.activo && eligiendoAlcance && (
        <TarjetaProcesar puedeVolver={!!proc.estado} alVolver={() => setConfigurando(false)} alProcesar={() => setConfigurando(false)} />
      )}
      {!proc.activo && !eligiendoAlcance && <TarjetaResumen alReprocesar={() => setConfigurando(true)} />}
      {!proc.activo && fichas.length > 0 && <ListaFichas />}
    </div>
  );
}
