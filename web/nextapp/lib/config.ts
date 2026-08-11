/**
 * Configuración central del dashboard.
 * Los valores se leen de variables de entorno NEXT_PUBLIC_*;
 * si no están definidas, se usan los defaults apuntando al servidor de producción.
 */

export const SERVIDOR =
	process.env.NEXT_PUBLIC_SERVIDOR ?? '100.110.157.112';

export const MQTT_WS_URL =
	process.env.NEXT_PUBLIC_MQTT_WS_URL ?? `ws://${SERVIDOR}:9001`;

export const WEBRTC_BASE =
	process.env.NEXT_PUBLIC_WEBRTC_BASE ?? `http://${SERVIDOR}:8889`;

/** ms sin vitales antes de marcar la cama como desconectada */
export const TIMEOUT_DATOS_MS = 5_000;

/** ms entre reintentos WHEP cuando el stream aún no existe */
export const WHEP_RETRY_MS = 5_000;

/**
 * ms de gracia cuando la conexión WebRTC pasa a `disconnected` antes de
 * derribarla y reconectar: `disconnected` suele ser transitorio (UDP sobre la
 * tailnet) y se recupera solo; derribar de inmediato fabricaba bucles de
 * "Reconectando…". Solo `failed` derriba sin gracia. (ADR-019)
 */
export const WHEP_GRACIA_DISCONNECTED_MS = 4_000;

/**
 * Servidores ICE para WebRTC. Por defecto NINGUNO: entre pares de la tailnet
 * los candidatos host bastan, y el despliegue hospitalario no tiene internet
 * (ADR-008/009) — un STUN público solo añadiría espera y una dependencia
 * prohibida. Para escenarios futuros (NAT sin Tailscale) se define como JSON:
 *   NEXT_PUBLIC_ICE_SERVERS='[{"urls":"turn:...","username":"…","credential":"…"}]'
 */
export const ICE_SERVERS: RTCIceServer[] = (() => {
	try {
		const crudo: unknown = JSON.parse(process.env.NEXT_PUBLIC_ICE_SERVERS ?? '[]');
		// JSON válido pero de forma incorrecta ('{}', '"stun:x"', 'null')
		// también debe caer al fallback: llegaría intacto a RTCPeerConnection
		// y lanzaría TypeError en cada montaje.
		if (!Array.isArray(crudo)) throw new Error('no es un array');
		const validos = crudo.filter(
			(e): e is RTCIceServer => e !== null && typeof e === 'object' && 'urls' in e,
		);
		if (validos.length < crudo.length) {
			console.warn('[config] NEXT_PUBLIC_ICE_SERVERS: se ignoran entradas sin "urls".');
		}
		return validos;
	} catch {
		console.warn('[config] NEXT_PUBLIC_ICE_SERVERS no es un array JSON de RTCIceServer; se ignora.');
		return [];
	}
})();
