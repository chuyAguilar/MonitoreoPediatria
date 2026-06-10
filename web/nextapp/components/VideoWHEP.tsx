'use client';

import { useEffect, useRef, useState } from 'react';
import { connectWhep } from '@/lib/whep';
import styles from './VideoWHEP.module.css';

interface VideoWHEPProps {
	camaId: string;
}

export default function VideoWHEP({ camaId }: VideoWHEPProps) {
	const videoRef = useRef<HTMLVideoElement>(null);
	const [connected, setConnected] = useState(false);
	const [statusLabel, setStatusLabel] = useState('Conectando cámara…');

	useEffect(() => {
		const videoEl = videoRef.current;
		if (!videoEl) return;

		const handle = connectWhep(camaId, videoEl, (isConnected, label) => {
			setConnected(isConnected);
			if (!isConnected) {
				setStatusLabel(label || 'Sin cámara');
			}
		});

		return () => {
			handle.cleanup();
		};
	}, [camaId]);

	return (
		<div className={styles.zonaVideo}>
			{!connected && (
				<div className={styles.sinCamara}>
					<span className={styles.sinCamaraIcono} aria-hidden="true">📷</span>
					<span className={styles.sinCamaraTexto}>{statusLabel}</span>
				</div>
			)}
			<video
				ref={videoRef}
				autoPlay
				muted
				playsInline
				className={styles.videoElement}
				style={{ display: connected ? 'block' : 'none' }}
			/>
		</div>
	);
}
