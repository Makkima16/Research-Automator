// Estado del servidor: lista de proyectos, proyecto activo, fichas y polling.
// El proyecto activo también vive en una ref para que los flujos async lean el valor vigente.
import { useCallback, useEffect, useRef, useState } from 'react';
import * as api from '@/lib/api';
import type { Ficha, Proyecto, ProyectoResumen } from '@/lib/tipos';

const CLAVE_ACTIVO = 'buscador.activo';  // misma clave que la versión anterior

type Cambio = Proyecto | null | ((actual: Proyecto | null) => Proyecto | null);

function leerActivo(): string | null {
  try { return localStorage.getItem(CLAVE_ACTIVO); } catch { return null; }  // almacenamiento bloqueado
}

function recordarActivo(id: string) {
  try { localStorage.setItem(CLAVE_ACTIVO, id); } catch { /* almacenamiento bloqueado */ }
}

export function useProyectos(alFallar: (e: unknown) => void) {
  const [proyectos, setProyectos] = useState<ProyectoResumen[]>([]);
  const [proyecto, setEstado] = useState<Proyecto | null>(null);
  const [fichas, setFichas] = useState<Ficha[]>([]);
  const [cargando, setCargando] = useState(true);
  const ref = useRef<Proyecto | null>(null);

  // Cambia el proyecto activo y refleja su nombre y etapa en la barra lateral
  const setProyecto = useCallback((cambio: Cambio) => {
    const siguiente = typeof cambio === 'function' ? cambio(ref.current) : cambio;
    ref.current = siguiente;
    setEstado(siguiente);
    if (siguiente) {
      setProyectos((lista) => lista.map((p) => (p.id === siguiente.id ? { ...p, name: siguiente.name, stage: siguiente.stage } : p)));
    }
  }, []);

  const seleccionar = useCallback(async (id: string) => {
    const p = await api.obtenerProyecto(id);
    setProyecto(p);
    recordarActivo(id);
  }, [setProyecto]);

  // Carga inicial: el último proyecto abierto, o el más reciente
  useEffect(() => {
    let vigente = true;
    (async () => {
      try {
        const lista = await api.listarProyectos();
        if (!vigente) return;
        setProyectos(lista);
        const inicial = lista.find((p) => p.id === leerActivo()) ?? lista[lista.length - 1];
        if (inicial) await seleccionar(inicial.id);
      } catch (e) {
        alFallar(e);
      } finally {
        if (vigente) setCargando(false);
      }
    })();
    return () => { vigente = false; };
  }, [seleccionar, alFallar]);

  // Las fichas se recargan al cambiar de proyecto, de etapa o al terminar una corrida
  const id = proyecto?.id;
  const etapa = proyecto?.stage;
  const procesando = proyecto?.procesamiento.activo;
  useEffect(() => {
    if (!id || etapa !== 'results') { setFichas([]); return; }
    let vigente = true;
    api.listarFichas(id).then((f) => { if (vigente) setFichas(f); }).catch(() => { if (vigente) setFichas([]); });
    return () => { vigente = false; };
  }, [id, etapa, procesando]);

  // Polling cada 1 s solo mientras hay una búsqueda o un procesamiento en curso;
  // si nada cambió no se actualiza el estado (reiniciaría las animaciones)
  const enCurso = etapa === 'loading' || Boolean(procesando);
  useEffect(() => {
    if (!id || !enCurso) return;
    const timer = setInterval(async () => {
      let nuevo: Proyecto;
      try { nuevo = await api.obtenerProyecto(id); } catch { return; }  // se reintenta en el siguiente tick
      const actual = ref.current;
      if (!actual || actual.id !== id) return;
      const cambio = nuevo.stage !== actual.stage
        || nuevo.aviso !== actual.aviso
        || JSON.stringify(nuevo.progreso) !== JSON.stringify(actual.progreso)
        || JSON.stringify(nuevo.procesamiento) !== JSON.stringify(actual.procesamiento);
      if (!cambio) return;
      // La selección solo la cambia el usuario, salvo que una búsqueda nueva la reinicie
      setProyecto(nuevo.stage === actual.stage ? { ...nuevo, seleccion: actual.seleccion } : nuevo);
    }, 1000);
    return () => clearInterval(timer);
  }, [id, enCurso, setProyecto]);

  return { proyectos, setProyectos, proyecto, proyectoRef: ref, setProyecto, fichas, cargando, seleccionar };
}
