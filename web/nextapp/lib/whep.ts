import { WEBRTC_BASE, WHEP_RETRY_MS } from './config';

export interface WhepHandle {
	cleanup: () => void;
}

type StateCallback = (connected: boolean, label: string) => void;

/**
 * Conecta un stream WebRTC via protocolo WHEP (POST del SDP offer).
 *
 * Comportamiento:
 * - Si el servidor devuelve 404 (stream aún no publicado), reintenta cada WHEP_RETRY_MS.
 * - Si connectionState pasa a failed/disconnected, reconecta automáticamente.
 * - Cuando el video conecta, llama onState(true, '').
 * - Mientras no hay video, llama onState(false, label).
 *
 * Uso:
 *   const handle = connectWhep(camaId, videoEl, onState);
 *   // En cleanup del useEffect:
 *   return () => handle.cleanup();
 */
export function connectWhep(
	camaId: string,
	videoEl: HTMLVideoElement,
	onState: StateCallback,
): WhepHandle {
	let pc: RTCPeerConnection | null = null;
	let retryTimer: ReturnType<typeof setTimeout> | null = null;
	let destroyed = false;
	let videoConnected = false;

	async function attempt(): Promise<void> {
		if (destroyed) return;

		// Cerrar PC anterior si existe
		if (pc && pc.signalingState !== 'closed') pc.close();

		pc = new RTCPeerConnection({
			iceServers: [{ urls: 'stun:stun.l.google.com:19302' }],
		});

		pc.ontrack = (event) => {
			if (event.streams?.[0]) {
				videoEl.srcObject = event.streams[0];
				videoConnected = true;
				onState(true, '');
			}
		};

		pc.onconnectionstatechange = () => {
			if (!pc) return;
			const state = pc.connectionState;
			console.info(`[WebRTC] ${camaId} → ${state}`);
			if (state === 'failed' || state === 'disconnected') {
				videoConnected = false;
				onState(false, 'Reconectando…');
				scheduleRetry();
			}
		};

		pc.addTransceiver('video', { direction: 'recvonly' });
		pc.addTransceiver('audio', { direction: 'recvonly' });

		try {
			const offer = await pc.createOffer();
			await pc.setLocalDescription(offer);

			// Esperar recolección de candidatos ICE (máx 3 s)
			await new Promise<void>((resolve) => {
				if (!pc || pc.iceGatheringState === 'complete') {
					resolve();
					return;
				}
				const check = () => {
					if (!pc || pc.iceGatheringState === 'complete') {
						pc?.removeEventListener('icegatheringstatechange', check);
						resolve();
					}
				};
				pc.addEventListener('icegatheringstatechange', check);
				setTimeout(resolve, 3_000);
			});

			if (destroyed || !pc?.localDescription) return;

			const resp = await fetch(`${WEBRTC_BASE}/${camaId}/whep`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/sdp' },
				body: pc.localDescription.sdp,
			});

			if (!resp.ok) throw new Error(`WHEP HTTP ${resp.status}`);

			const sdpAnswer = await resp.text();
			await pc.setRemoteDescription({ type: 'answer', sdp: sdpAnswer });

		} catch (err) {
			if (destroyed) return;
			console.info(`[WebRTC] ${camaId}:`, (err as Error).message);
			if (pc && pc.signalingState !== 'closed') pc.close();
			onState(false, 'Sin cámara');
			scheduleRetry();
		}
	}

	function scheduleRetry(): void {
		if (destroyed || videoConnected) return;
		if (retryTimer !== null) clearTimeout(retryTimer);
		retryTimer = setTimeout(() => {
			retryTimer = null;
			if (!destroyed && !videoConnected) void attempt();
		}, WHEP_RETRY_MS);
	}

	// Primer intento inmediato
	void attempt();

	return {
		cleanup() {
			destroyed = true;
			if (retryTimer !== null) clearTimeout(retryTimer);
			if (pc && pc.signalingState !== 'closed') pc.close();
			if (videoEl.srcObject) {
				(videoEl.srcObject as MediaStream).getTracks().forEach((t) => t.stop());
				videoEl.srcObject = null;
			}
		},
	};
}
