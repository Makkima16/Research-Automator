'use client';

import { useState } from 'react';
import { X } from 'lucide-react';
import css from './EntradaTerminos.module.css';

interface Props {
  valores: string[];
  cambiar: (valores: string[]) => void;
  placeholder: string;
  etiqueta: string;          // para lectores de pantalla
  maximo?: number;
}

// Campo de texto que convierte cada término en un chip al pulsar Enter o al salir
// del campo. Retroceso con el campo vacío quita el último chip.
export function EntradaTerminos({ valores, cambiar, placeholder, etiqueta, maximo }: Props) {
  const [texto, setTexto] = useState('');
  const lleno = maximo !== undefined && valores.length >= maximo;

  const agregar = () => {
    const limpio = texto.replace(/"/g, '').replace(/\s+/g, ' ').trim();
    setTexto('');
    if (!limpio || lleno || valores.some((v) => v.toLowerCase() === limpio.toLowerCase())) return;
    cambiar([...valores, limpio]);
  };

  const quitar = (i: number) => cambiar(valores.filter((_, j) => j !== i));

  return (
    <div className={css.caja}>
      {valores.map((v, i) => (
        <span className={css.chip} key={v}>
          {v}
          <button type="button" aria-label={`Quitar «${v}»`} onClick={() => quitar(i)}><X size={12} strokeWidth={3} /></button>
        </span>
      ))}
      <input className={css.entrada} value={texto} aria-label={etiqueta} disabled={lleno}
        placeholder={lleno ? `Máximo ${maximo}` : valores.length ? 'Añadir otro…' : placeholder}
        onChange={(e) => setTexto(e.target.value)}
        onBlur={agregar}
        onKeyDown={(e) => {
          if (e.key === 'Enter') { e.preventDefault(); agregar(); }
          else if (e.key === 'Backspace' && !texto && valores.length) quitar(valores.length - 1);
        }} />
    </div>
  );
}
