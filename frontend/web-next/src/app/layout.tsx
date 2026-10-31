import type { Metadata } from 'next';
import './organic.css';
import './globals.css';

export const metadata: Metadata = {
  title: 'Research Automator',
  description: 'Revisiones de literatura científica automatizadas.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}
