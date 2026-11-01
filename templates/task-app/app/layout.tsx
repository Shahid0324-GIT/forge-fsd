import type { ReactNode } from 'react';
import './globals.css';
export const metadata = { title: 'Forge Tasks', description: 'Generated task manager' };
export default function Layout({ children }: { children: ReactNode }) {
  return <html lang="en"><body>{children}</body></html>;
}
