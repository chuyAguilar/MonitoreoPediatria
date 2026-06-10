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
