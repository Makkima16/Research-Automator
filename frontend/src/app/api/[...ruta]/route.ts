// Proxy hacia el backend Python (api/servidor.py). El navegador solo habla
// con Next; así no hay CORS y el backend sigue sin cambios. No usa `rewrites`
// de next.config porque las llamadas al LLM son lentas y un Route Handler no
// impone un tope de 30 s.
import type { NextRequest } from 'next/server';

export const dynamic = 'force-dynamic';

const API_URL = process.env.API_URL ?? 'http://127.0.0.1:8000';
const CABECERAS_DE_RESPUESTA = ['content-type', 'content-disposition'];

type Contexto = { params: Promise<{ ruta: string[] }> };

async function reenviar(req: NextRequest, { params }: Contexto): Promise<Response> {
  const { ruta } = await params;
  const destino = `${API_URL}/api/${ruta.join('/')}${req.nextUrl.search}`;
  const cuerpo = req.method === 'GET' || req.method === 'HEAD' ? undefined : await req.text();
  try {
    const resp = await fetch(destino, {
      method: req.method,
      headers: cuerpo ? { 'Content-Type': 'application/json' } : {},
      body: cuerpo || undefined,
      cache: 'no-store',
    });
    const cabeceras = new Headers({ 'Cache-Control': 'no-store' });
    for (const nombre of CABECERAS_DE_RESPUESTA) {
      const valor = resp.headers.get(nombre);
      if (valor) cabeceras.set(nombre, valor);
    }
    return new Response(resp.body, { status: resp.status, headers: cabeceras });
  } catch {
    return Response.json(
      { error: 'No hay conexión con el servidor (¿sigue corriendo python servidor.py?).' },
      { status: 502 },
    );
  }
}

export { reenviar as GET, reenviar as POST, reenviar as PUT, reenviar as DELETE };
