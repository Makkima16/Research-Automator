// Funciones puras de formato y de datos derivados de un paper o de una corrida.
import type { Ficha, Paper, Procesamiento } from './tipos';

export const MOTORES: Record<string, string> = {
  openalex: 'OpenAlex', semantic_scholar: 'Semantic Scholar', scopus: 'Scopus', scihub: 'Sci-Hub',
};
export const nombreMotor = (m: string) => MOTORES[m] || m;

// motor_busqueda trae uno o varios motores separados por "; "
export const motoresDe = (p: Paper) => String(p.motor_busqueda || '').split('; ').filter(Boolean);

export const doiCorto = (doi: string | null | undefined) =>
  String(doi || '').replace(/^https?:\/\/(dx\.)?doi\.org\//i, '');

export const doiUrl = (doi: string | null | undefined) => `https://doi.org/${encodeURI(doiCorto(doi))}`;

// Dominio de la página donde está el texto del paper (p. ej. "mdpi.com"); '' si no hay enlace
export function paginaOrigen(p: Paper): string {
  try {
    return new URL((p.pdf_url || p.oa_url) as string).hostname.replace(/^www\./, '');
  } catch {
    return '';
  }
}

// Enlace "Abrir original": DOI, o la URL de acceso abierto si no hay DOI
export function urlOriginal(p: Paper): string {
  const url = p.doi ? doiUrl(p.doi) : p.oa_url || p.openalex_id || '';
  return /^https?:\/\//.test(url) ? url : '';
}

// matched_query trae las cadenas que encontraron el paper unidas con "; ".
// Devuelve los números (1-based) de esas cadenas dentro de las del proyecto.
export function cadenasDe(p: Paper, queries: string[]): number[] {
  const encontrada = p.matched_query || '';
  return queries.flatMap((q, i) => (q && encontrada.includes(q) ? [i + 1] : []));
}

export const plural = (n: number, uno: string, varios: string) => `${n} ${n === 1 ? uno : varios}`;

export const FUENTES_LECTURA: Record<string, string> = {
  nemotron_parse: 'Nemotron Parse',
  'local+nemotron_parse': 'Lectura local + Nemotron Parse',
  local: 'Lectura local',
  europepmc: 'Europe PMC',
};

export const fuenteFicha = (f: Ficha) => FUENTES_LECTURA[f.fuente ?? ''] || f.fuente || 'PDF';

export function resumenCorrida(p: Procesamiento): string {
  const partes: string[] = [];
  const ini = p.inicio ? new Date(p.inicio) : null;
  const fin = p.fin ? new Date(p.fin) : null;
  const hora = (d: Date) => d.toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' });
  if (ini && !isNaN(ini.getTime())) {
    partes.push(ini.toLocaleDateString('es', { day: 'numeric', month: 'short', year: 'numeric' }));
    if (fin && !isNaN(fin.getTime())) {
      const seg = Math.max(0, Math.round((fin.getTime() - ini.getTime()) / 1000));
      partes.push(`${hora(ini)} → ${hora(fin)}`, seg >= 60 ? `${Math.floor(seg / 60)} min ${seg % 60} s` : `${seg} s`);
    } else partes.push(hora(ini));
  }
  if (p.total) partes.push(`${plural(p.total, 'paper', 'papers')} ${p.alcance === 'sel' ? 'de la selección' : 'del proyecto'}`);
  return partes.join(' · ');
}

// ---------- CSV de fichas (se arma en el navegador, igual que la versión anterior) ----------

const celdaCsv = (v: unknown) => `"${String(v ?? '').replace(/"/g, '""')}"`;

export function fichasACsv(fichas: Ficha[]): string {
  const columnas = ['title', 'year', 'doi', 'estado', 'cobertura', 'fuente', 'resumen', 'objetivo', 'abstract',
    'intro_penultimo', 'intro_ultimo', 'conclusion_texto', 'conclusiones', 'hallazgos_clave', 'tablas'];
  const plano = (f: Ficha): Record<string, unknown> => ({
    ...f,
    conclusiones: f.conclusiones.join(' | '),
    hallazgos_clave: f.hallazgos_clave.join(' | '),
    tablas: f.tablas.map((t) => `${t.nombre} [${t.atributos.join('; ')}]`).join(' | '),
  });
  const filas = fichas.map((f) => columnas.map((c) => celdaCsv(plano(f)[c])).join(','));
  return '\ufeff' + [columnas.join(','), ...filas].join('\n');
}

export function descargarTexto(nombre: string, contenido: string, tipo: string) {
  const url = URL.createObjectURL(new Blob([contenido], { type: tipo }));
  const a = document.createElement('a');
  a.href = url;
  a.download = nombre;
  a.click();
  URL.revokeObjectURL(url);
}
