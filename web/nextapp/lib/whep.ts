import { ICE_SERVERS, WEBRTC_BASE, WHEP_GRACIA_DISCONNECTED_MS, WHEP_RETRY_MS } from './config';

export interface WhepHandle {
	cleanup: () => void;
}

type StateCallback = (connected: boolean, label: string) => void;

/**
 * Conecta un stream WebRTC vía protocolo WHEP (POST del SDP offer).
 *
 * Política de conexión (ADR-019):
 * - Solo video: las cámaras del diseño no llevan micrófono (ADR-010). Si un
 *   día entra audio, añadir aquí el transceiver de audio recvonly.
 * - Sin servidores ICE por defecto: entre pares de la tailnet los candidatos
 *   host bastan y el despliegue hospitalario no tiene internet (ADR-008/009).
 *   Configurable con NEXT_PUBLIC_ICE_SERVERS para escenarios futuros.
 * - `disconnected` recibe un período de GRACIA (suele ser transitorio y
 *   recuperarse solo); únicamente `failed` — o la gracia vencida — derriba y
 *   reconecta. Derribar en el primer `disconnected` fabricaba bucles de
 *   "Reconectando…" sobre conexiones que se estaban recuperando.
 * - Etiquetas que diagnostican: un 404 (nadie publica) no es lo mismo que un
 *   fallo de red/CORS ni que un ICE caído; el operador debe saber cuál es.
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
	let graciaTimer: ReturnType<typeof setTimeout> | null = null;
	let destroyed = false;
	let videoConnected = false;

	function limpiarGracia(): void {
		if (graciaTimer !== null) {
			clearTimeout(graciaTimer);
			graciaTimer = null;
		}
	}

	function derribarYReintentar(): void {
		videoConnected = false;
		onState(false, 'Reconectando…');
		scheduleRetry();
	}

	async function attempt(): Promise<void> {
		if (destroyed) return;

		limpiarGracia();
		// Cerrar PC anterior si existe
		if (pc && pc.signalingState !== 'closed') pc.close();

		try {
			pc = new RTCPeerConnection({ iceServers: ICE_SERVERS });
		} catch (err) {
			// ICE_SERVERS con forma o URLs inválidas: reintentar no lo arregla,
			// y sin etiqueta el fallo sería mudo ("Conectando cámara…" eterno).
			console.error(
				`[WebRTC] ${camaId}: RTCPeerConnection rechazó ICE_SERVERS:`,
				(err as Error).message,
			);
			onState(false, 'Configuración de video inválida (ICE_SERVERS)');
			return;
		}

		pc.ontrack = (event) => {
			// 'track' se dispara al aplicar el SDP answer (spec WebRTC), ANTES de
			// que ICE conecte: aquí solo se adjunta el stream. El estado
			// "conectado" lo declara onconnectionstatechange en 'connected'.
			if (event.streams?.[0]) {
				videoEl.srcObject = event.streams[0];
			}
		};

		pc.onconnectionstatechange = () => {
			if (!pc) return;
			const state = pc.connectionState;
			console.info(`[WebRTC] ${camaId} → ${state}`);
			if (state === 'connected') {
				limpiarGracia();
				// Reentrada: si hubo derribo por gracia y el ICE se recuperó solo,
				// cancelar el retry pendiente (destruiría esta conexión viva) y
				// volver a declarar el video conectado.
				if (retryTimer !== null) {
					clearTimeout(retryTimer);
					retryTimer = null;
				}
				if (!videoConnected && videoEl.srcObject) {
					videoConnected = true;
					onState(true, '');
				}
			} else if (state === 'failed') {
				limpiarGracia();
				derribarYReintentar();
			} else if (state === 'disconnected') {
				// Transitorio con frecuencia (UDP sobre la tailnet): esperar la
				// gracia antes de derribar; si vuelve a connected, no pasó nada.
				if (graciaTimer === null) {
					graciaTimer = setTimeout(() => {
						graciaTimer = null;
						if (!destroyed && pc && pc.connectionState !== 'connected') {
							console.info(`[WebRTC] ${camaId} → gracia vencida, reconectando`);
							derribarYReintentar();
						}
					}, WHEP_GRACIA_DISCONNECTED_MS);
				}
			}
		};

		try {
			pc.addTransceiver('video', { direction: 'recvonly' });

			const offer = await pc.createOffer();
			await pc.setLocalDescription(offer);

			// Esperar recolección de candidatos ICE (sin STUN termina enseguida)
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

			if (resp.status === 404) {
				// El servidor responde pero nadie publica ese stream todavía
				onState(false, 'Sin cámara (nadie publica)');
				scheduleRetry();
				return;
			}
			if (!resp.ok) throw new Error(`WHEP HTTP ${resp.status}`);

			const sdpAnswer = await resp.text();
			avisarSiSoloLoopback(camaId, sdpAnswer);
			await pc.setRemoteDescription({ type: 'answer', sdp: sdpAnswer });

		} catch (err) {
			if (destroyed) return;
			console.info(`[WebRTC] ${camaId}:`, (err as Error).message);
			if (pc && pc.signalingState !== 'closed') pc.close();
			// fetch/CORS/red: el servidor de video no responde — distinto de
			// "nadie publica" (404) y de un ICE caído ("Reconectando…")
			onState(false, 'Sin conexión con el servidor de video');
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
			limpiarGracia();
			if (pc && pc.signalingState !== 'closed') pc.close();
			if (videoEl.srcObject) {
				(videoEl.srcObject as MediaStream).getTracks().forEach((t) => t.stop());
				videoEl.srcObject = null;
			}
		},
	};
}

/**
 * Detecta la clase de fallo del 12-ago-2026: MediaMTX anunciando SOLO el
 * candidato loopback (127.0.0.1), inalcanzable desde cualquier otra máquina.
 * El síntoma aguas abajo es connecting→failed en bucle; esta advertencia lo
 * vuelve diagnosticable en segundos desde la consola del operador.
 */
function avisarSiSoloLoopback(camaId: string, sdpAnswer: string): void {
	const candidatos = sdpAnswer
		.split('\n')
		.filter((l) => l.startsWith('a=candidate'));
	if (candidatos.length === 0) return;
	const soloLoopback = candidatos.every(
		(l) => l.includes(' 127.0.0.1 ') || l.includes(' ::1 '),
	);
	if (soloLoopback) {
		console.warn(
			`[WebRTC] ${camaId}: el servidor de video solo anuncia candidatos ICE ` +
			`loopback (127.0.0.1) — inalcanzables desde esta máquina; la conexión ` +
			`va a fallar. Arreglo: en mediamtx.yml del servidor añadir ` +
			`webrtcAdditionalHosts con sus IPs reales (p. ej. la de Tailscale) y ` +
			`reiniciar MediaMTX.`,
		);
	}
}
