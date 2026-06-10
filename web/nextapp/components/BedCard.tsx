'use client';

import type { CamaState } from '@/lib/types';
import { formatVal, formatTsCorto, formatPniTs } from '@/lib/utils';
import VideoWHEP from './VideoWHEP';
import styles from './BedCard.module.css';

interface BedCardProps {
	cama: CamaState;
	onSelect: (camaId: string) => void;
}

export default function BedCard({ cama, onSelect }: BedCardProps) {
	const { id, online, signos, origen, tsRaw } = cama;

	const simpleSigns = [
		{ key: 'fc', label: 'FC', unit: 'lpm', color: 'var(--color-fc)' },
		{ key: 'spo2', label: 'SpO₂', unit: '%', color: 'var(--color-spo2)' },
		{ key: 'fr', label: 'FR', unit: 'rpm', color: 'var(--color-fr)' },
		{ key: 'temp', label: 'Temp', unit: '°C', color: 'var(--color-temp)' },
		{ key: 'fp', label: 'FP', unit: 'lpm', color: 'var(--color-fp)' },
	] as const;

	const pni = signos.pni;
	const isPniEmpty = !pni || pni.sis === null || pni.sis === undefined;
	const pniText = isPniEmpty ? '--/--' : `${pni.sis}/${pni.dia}`;
	const pniMediaText = isPniEmpty ? '' : `(${pni.media})`;
	const pniTsText = !isPniEmpty && pni.ts ? formatPniTs(pni.ts) : '';

	return (
		<article
			className={`${styles.tarjetaCama} ${!online ? styles.tarjetaCamaDesconectada : ''}`}
			id={`cama-${id}`}
			role="button"
			tabIndex={0}
			aria-label={`Detalle de cama ${id}`}
			onClick={() => onSelect(id)}
			onKeyDown={(e) => {
				if (e.key === 'Enter' || e.key === ' ') {
					onSelect(id);
				}
			}}
		>
			<div className={styles.tarjetaHeader}>
				<div className={styles.camaIdLabel}>
					<div
						className={`${styles.dotEstado} ${online ? styles.dotEstadoOnline : ''}`}
						id={`dot-${id}`}
					/>
					<span className={styles.camaNombre}>{id}</span>
				</div>
				<div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
					<span className={styles.origenBadge} id={`origen-${id}`}>
						{origen || '—'}
					</span>
					<span className={styles.tsUltimo} id={`ts-${id}`}>
						{tsRaw ? formatTsCorto(tsRaw) : 'sin datos'}
					</span>
				</div>
			</div>

			<VideoWHEP camaId={id} />

			<div className={styles.signosGrid} id={`signos-${id}`}>
				{simpleSigns.map((cfg) => {
					const signoVal = signos[cfg.key];
					const val = signoVal?.valor ?? null;
					const sinDato = val === null || val === undefined;
					const textVal = sinDato ? '--' : formatVal(val);

					return (
						<div
							key={cfg.key}
							className={styles.signoItem}
							style={{ '--signo-color': cfg.color } as React.CSSProperties}
						>
							<span className={styles.signoEtiqueta}>{cfg.label}</span>
							<span
								key={val ?? 'null'}
								className={`${styles.signoValor} ${sinDato ? styles.signoValorSinDato : ''} ${
									!sinDato ? styles.parpadeoDato : ''
								}`}
								style={{ color: cfg.color }}
							>
								{textVal}
							</span>
							<span className={styles.signoUnidad}>{cfg.unit}</span>
						</div>
					);
				})}

				{/* PNI ocupa toda la fila al final */}
				<div
					className={`${styles.signoItem} ${styles.pniItem}`}
					style={{ '--signo-color': 'var(--color-pni)' } as React.CSSProperties}
				>
					<div>
						<div className={styles.signoEtiqueta}>PNI — Presión No Invasiva</div>
						<div className={styles.pniTs} id={`pni-ts-${id}`}>
							{pniTsText}
						</div>
					</div>
					<div className={styles.pniValores}>
						<span
							key={pniText}
							className={`${styles.pniValorPrincipal} ${
								isPniEmpty ? styles.signoValorSinDato : ''
							} ${!isPniEmpty ? styles.parpadeoDato : ''}`}
						>
							{pniText}
						</span>
						<span className={styles.pniMedia} id={`pni-media-${id}`}>
							{pniMediaText}
						</span>
					</div>
					<div className={styles.signoUnidad}>mmHg</div>
				</div>
			</div>
		</article>
	);
}
