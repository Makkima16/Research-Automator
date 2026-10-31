import { AppProvider } from '@/context/AppContext';
import { Shell } from '@/components/layout/Shell';

export default function Pagina() {
  return (
    <AppProvider>
      <Shell />
    </AppProvider>
  );
}
