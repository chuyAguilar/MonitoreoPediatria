'use client';

import { useEffect, useState } from 'react';
import type { MqttStatus } from '@/hooks/useMqtt';
import styles from './Header.module.css';

interface HeaderProps {
	activeBedsCount: number;
	mqttStatus: MqttStatus;
}

export default function Header({ activeBedsCount, mqttStatus }: HeaderProps) {
	const [timeStr, setTimeStr] = useState<string>('');

	useEffect(() => {
		function updateClock() {
			const now = new Date();
			setTimeStr(
				now.toLocaleTimeString('es-MX', {
					hour: '2-digit',
					minute: '2-digit',
					second: '2-digit',
					hour12: false,
				})
			);
		}
		updateClock();
		const interval = setInterval(updateClock, 1000);
		return () => clearInterval(interval);
	}, []);

	const getMqttStatusText = (status: MqttStatus) => {
		switch (status) {
			case 'conectado':
				return 'MQTT conectado';
			case 'conectando':
				return 'Conectando…';
			case 'reconectando':
				return 'Reconectando…';
			case 'sin_conexion':
				return 'Sin conexión';
			case 'error':
				return 'Error MQTT';
			default:
				return status;
		}
	};

	const isConnected = mqttStatus === 'conectado';

	return (
		<header className={styles.encabezado} role="banner">
			<div className={styles.encabezadoIzq}>
				<div className={styles.logoCross} aria-hidden="true" />
				<div>
					<h1 className={styles.tituloApp}>Monitoreo Pediatría</h1>
					<p className={styles.subtituloApp}>Cuadro de control · Observación</p>
				</div>
			</div>
			<div className={styles.encabezadoDer}>
				<div className={styles.contadorCamas} aria-live="polite">
					<strong>{activeBedsCount}</strong>
					<span>camas activas</span>
				</div>
				<div className={styles.indicadorMqtt} title="Estado conexión MQTT">
					<div
						className={`${styles.mqttDot} ${isConnected ? styles.mqttDotConectado : ''}`}
						aria-hidden="true"
					/>
					<span>{getMqttStatusText(mqttStatus)}</span>
				</div>
				<div className={styles.reloj} aria-label="Hora actual">
					{timeStr || '00:00:00'}
				</div>
			</div>
		</header>
	);
}
