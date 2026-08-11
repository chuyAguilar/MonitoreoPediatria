'use client';

/**
 * Página de diagnóstico de video: monta el cliente WHEP real contra cualquier
 * stream, sin depender de MQTT ni de que exista una cama.
 *
 *   http://<dashboard>/diag.html?stream=cama-09
 *   (el export estático emite el archivo plano diag.html, no diag/index.html)
 *
 * Es la herramienta del operador (y del desarrollador) cuando una tarjeta se
 * queda en "Reconectando…": aísla el video del resto del dashboard. Usa el
 * MISMO VideoWHEP/whep.ts que las tarjetas — lo que se diagnostica aquí es lo
 * que corre allá.
 */

import { useEffect, useState } from 'react';
import VideoWHEP from '@/components/VideoWHEP';
import { WEBRTC_BASE } from '@/lib/config';

export default function DiagnosticoVideo() {
	const [stream, setStream] = useState<string | null>(null);

	// window.location solo existe en el cliente; con output: 'export' no hay
	// servidor que lea la query, así que se lee en un efecto.
	useEffect(() => {
		const params = new URLSearchParams(window.location.search);
		setStream(params.get('stream') || 'cama-09');
	}, []);

	return (
		<main style={{ maxWidth: 720, margin: '2rem auto', padding: '0 1rem', fontFamily: 'system-ui' }}>
			<h1 style={{ fontSize: '1.2rem' }}>Diagnóstico de video WHEP</h1>
			<p style={{ opacity: 0.8 }}>
				Servidor WebRTC: <code>{WEBRTC_BASE}</code>
				{' · '}Stream: <code>{stream ?? '…'}</code>
				{' · '}Cambia con <code>?stream=cama-NN</code>
			</p>
			<p style={{ opacity: 0.8 }}>
				La secuencia de estados sale en la consola (F12) como{' '}
				<code>[WebRTC] {stream ?? 'stream'} → estado</code>.
			</p>
			{stream && (
				<div style={{ aspectRatio: '16 / 9', background: '#000' }}>
					<VideoWHEP camaId={stream} />
				</div>
			)}
		</main>
	);
}
