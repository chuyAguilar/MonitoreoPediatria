import type { Metadata } from 'next';
import { Inter, JetBrains_Mono } from 'next/font/google';
import './globals.css';

const inter = Inter({
	subsets: ['latin'],
	variable: '--font-inter',
	display: 'swap',
});

const jetbrainsMono = JetBrains_Mono({
	subsets: ['latin'],
	variable: '--font-mono',
	display: 'swap',
});

export const metadata: Metadata = {
	title: 'Monitoreo Pediatría — Cuadro Central',
	description: 'Tablero de monitoreo pediátrico en tiempo real: signos vitales y video en vivo por cama.',
};

export default function RootLayout({
	children,
}: Readonly<{
	children: React.ReactNode;
}>) {
	return (
		<html lang="es" className={`${inter.variable} ${jetbrainsMono.variable}`}>
			<body style={{ fontFamily: 'var(--font-inter), sans-serif' }}>
				{children}
			</body>
		</html>
	);
}
