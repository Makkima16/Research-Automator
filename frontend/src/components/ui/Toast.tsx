'use client';

import { useApp } from '@/context/AppContext';
import css from './Toast.module.css';

export function Toast() {
  const { toast } = useApp();
  return toast ? <div className={css.toast} role="status">{toast}</div> : null;
}
