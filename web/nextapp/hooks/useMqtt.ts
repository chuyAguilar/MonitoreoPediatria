'use client';

import { useEffect, useState } from 'react';
import { MQTT_WS_URL, TIMEOUT_DATOS_MS } from '@/lib/config';
import type { CamaState, CamasMap, Signos } from '@/lib/types';

export type MqttStatus =
	| 'conectando'
	| 'conectado'
	| 'reconectando'
	| 'sin_conexion'
	| 'error';

/**
 * Hook que gestiona la conexión MQTT y el estado de todas las camas.
 *
 * - Descubre camas dinámicamente: cada cama_id nuevo en los topics crea su entrada.
 * - Watchdog por cama: si no llega vitales en TIMEOUT_DATOS_MS → marca offline.
 * - Import dinámico de mqtt: garantiza ejecución sólo en navegador (nunca en SSR).
 */
export function useMqtt() {
	const [camas, setCamas] = useState<CamasMap>({});
	const [status, setStatus] = useState<MqttStatus>('conectando');

	useEffect(() => {
		let cancelled = false;
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		let mqttClient: any = null;
		const watchdogs: Record<string, ReturnType<typeof setTimeout>> = {};

		/* ---- Watchdog: si no hay vitales en TIMEOUT_DATOS_MS → offline ---- */
		function resetWatchdog(camaId: string) {
			if (watchdogs[camaId]) clearTimeout(watchdogs[camaId]);
			watchdogs[camaId] = setTimeout(() => {
				delete watchdogs[camaId];
				setCamas((prev) => {
					const cama = prev[camaId];
					if (!cama?.online) return prev;
					return { ...prev, [camaId]: { ...cama, online: false } };
				});
			}, TIMEOUT_DATOS_MS);
		}

		/* ---- Handlers de mensajes MQTT ---- */
		function handleVitales(msg: Record<string, unknown>) {
			const camaId = msg.cama_id as string;
			if (!camaId) return;

			setCamas((prev) => ({
				...prev,
				[camaId]: {
					id: camaId,
					online: true,
					signos: (msg.signos as Signos) ?? {},
					origen: (msg.origen as string) ?? '',
					tsRaw: (msg.ts as string) ?? '',
					deviceId: (msg.device_id as string) ?? '',
					ultimoTs: Date.now(),
				} satisfies CamaState,
			}));

			resetWatchdog(camaId);
		}

		function handleEstado(msg: Record<string, unknown>) {
			const camaId = msg.cama_id as string;
			if (!camaId) return;
			const online = msg.estado === 'online';

			setCamas((prev) => {
				const existing = prev[camaId];
				if (!existing) {
					// Cama descubierta sólo por estado (sin vitales aún)
					return {
						...prev,
						[camaId]: {
							id: camaId,
							online,
							signos: {},
							origen: '',
							tsRaw: (msg.ts as string) ?? '',
							deviceId: (msg.device_id as string) ?? '',
							ultimoTs: null,
						} satisfies CamaState,
					};
				}
				return { ...prev, [camaId]: { ...existing, online } };
			});
		}

		/* ---- Conexión MQTT (import dinámico → sólo browser) ---- */
		import('mqtt').then(({ default: mqtt }) => {
			if (cancelled) return;

			mqttClient = mqtt.connect(MQTT_WS_URL, {
				clientId: `monitoreoPediatria_${Math.random().toString(16).slice(2, 8)}`,
				clean: true,
				connectTimeout: 10_000,
				reconnectPeriod: 3_000,
				keepalive: 30,
			});

			mqttClient.on('connect', () => {
				setStatus('conectado');
				mqttClient.subscribe('monitoreo/vitales/+', { qos: 1 });
				mqttClient.subscribe('monitoreo/estado/+', { qos: 1 });
			});
			mqttClient.on('reconnect', () => setStatus('reconectando'));
			mqttClient.on('offline', () => setStatus('sin_conexion'));
			mqttClient.on('error', () => setStatus('error'));

			mqttClient.on('message', (topic: string, payload: Buffer) => {
				try {
					const msg = JSON.parse(payload.toString()) as Record<string, unknown>;
					if (topic.startsWith('monitoreo/vitales/')) handleVitales(msg);
					else if (topic.startsWith('monitoreo/estado/')) handleEstado(msg);
				} catch {
					console.warn('[MQTT] JSON inválido en topic:', topic);
				}
			});
		});

		return () => {
			cancelled = true;
			mqttClient?.end(true);
			Object.values(watchdogs).forEach(clearTimeout);
		};
	}, []);

	return { camas, status };
}
