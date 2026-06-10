'use client';

import { useEffect, useRef } from 'react';
import type { CamaState } from '@/lib/types';
import { formatVal } from '@/lib/utils';
import VideoWHEP from './VideoWHEP';
import styles from './DetailModal.module.css';

interface DetailModalProps {
	cama: CamaState;
	onClose: () => void;
}

export default function DetailModal({ cama, onClose }: DetailModalProps) {
	const overlayRef = useRef<HTMLDivElement>(null);
	const { id, online, signos, origen, deviceId, tsRaw } = cama;

	// Close on Escape key press
	useEffect(() => {
		const handleKeyDown = (e: KeyboardEvent) => {
			if (e.key === 'Escape') {
				onClose();
			}
		};
		window.addEventListener('keydown', handleKeyDown);
		return () => window.removeEventListener('keydown', handleKeyDown);
	}, [onClose]);

	// Lock body scroll while modal is active
	useEffect(() => {
		document.body.style.overflow = 'hidden';
		return () => {
			document.body.style.overflow = '';
		};
	}, []);

	const handleOverlayClick = (e: React.MouseEvent) => {
		if (e.target === overlayRef.current) {
			onClose();
		}
	};

	const simpleSigns = [
		{ key: 'fc', label: 'FC', unit: 'lpm', color: 'var(--color-fc)' },
		{ key: 'spo2', label: 'SpO₂', unit: '%', color: 'var(--color-spo2)' },
		{ key: 'fr', label: 'FR', unit: 'rpm', color: 'var(--color-fr)' },
		{ key: 'temp', label: 'Temp', unit: '°C', color: 'var(--color-temp)' },
		{ key: 'fp', label: 'FP', unit: 'lpm', color: 'var(--color-fp)' },
	] as const;

	const pni = signos.pni;
	const isPniEmpty = !pni || pni.sis === null || pni.sis === undefined;
	const pniText = isPniEmpty ? '--/--' : `${pni.sis}/${pni.dia} (${pni.media})`;

	return (
		<div
			ref={overlayRef}
			className={styles.modalOverlay}
			role="dialog"
			aria-modal="true"
			aria-labelledby="modal-cama-nombre"
			onClick={handleOverlayClick}
		>
			<div className={styles.modalContenido}>
				<div className={styles.modalHeader}>
					<div className={styles.modalTitulo}>
						<div
							className={`${styles.dotEstado} ${online ? styles.dotEstadoOnline : ''}`}
							id="modal-dot-estado"
						/>
						<span id="modal-cama-nombre">{id}</span>
					</div>
					<button
						className={styles.btnCerrarModal}
						aria-label="Cerrar detalle"
						onClick={onClose}
					>
						Cerrar ✕
					</button>
				</div>
				<div className={styles.modalCuerpo}>
					<div className={styles.modalVideoWrap}>
						<VideoWHEP camaId={id} />
					</div>
					<div className={styles.modalSignos}>
						{/* PNI */}
						<div
							className={styles.modalSignoRow}
							style={{ '--signo-color': 'var(--color-pni)' } as React.CSSProperties}
						>
							<div>
								<div className={styles.modalSignoNombre}>Presión No Invasiva</div>
								<div className={styles.signoUnidad}>mmHg · sis/dia (media)</div>
							</div>
							<span
								key={pniText}
								className={`${styles.modalSignoValor} ${
									isPniEmpty ? styles.modalSignoValorSinDato : ''
								}`}
							>
								{pniText}
							</span>
						</div>

						{/* Simple Signs */}
						{simpleSigns.map((cfg) => {
							const signoVal = signos[cfg.key];
							const val = signoVal?.valor ?? null;
							const sinDato = val === null || val === undefined;
							const textVal = sinDato ? '--' : formatVal(val);

							return (
								<div
									key={cfg.key}
									className={styles.modalSignoRow}
									style={{ '--signo-color': cfg.color } as React.CSSProperties}
								>
									<div>
										<div className={styles.modalSignoNombre}>{cfg.label}</div>
										<div className={styles.signoUnidad}>{cfg.unit}</div>
									</div>
									<span
										key={val ?? 'null'}
										className={`${styles.modalSignoValor} ${
											sinDato ? styles.modalSignoValorSinDato : ''
										}`}
										style={{ color: cfg.color }}
									>
										{textVal}
									</span>
								</div>
							);
						})}
					</div>

					<div className={styles.modalInfo}>
						{origen && (
							<span>
								<strong>Origen:</strong> {origen}
							</span>
						)}
						{deviceId && (
							<span>
								<strong>Device:</strong> {deviceId}
							</span>
						)}
						{tsRaw && (
							<span>
								<strong>Último dato:</strong> {tsRaw}
							</span>
						)}
					</div>
				</div>
			</div>
		</div>
	);
}
