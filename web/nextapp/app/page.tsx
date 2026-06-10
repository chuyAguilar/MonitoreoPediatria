'use client';

import { useState } from 'react';
import { useMqtt } from '@/hooks/useMqtt';
import Header from '@/components/Header';
import BedCard from '@/components/BedCard';
import DetailModal from '@/components/DetailModal';
import styles from './page.module.css';

export default function Home() {
	const { camas, status } = useMqtt();
	const [selectedCamaId, setSelectedCamaId] = useState<string | null>(null);

	const camasArray = Object.values(camas).sort((a, b) => a.id.localeCompare(b.id));
	const activeBedsCount = camasArray.filter((c) => c.online).length;

	const selectedCama = selectedCamaId ? camas[selectedCamaId] : null;

	return (
		<div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
			<Header activeBedsCount={activeBedsCount} mqttStatus={status} />

			<main className={styles.cuadricula} role="main" aria-label="Cuadrícula de camas">
				{camasArray.length === 0 ? (
					<div className={styles.pantallaEspera}>
						<div className={styles.spinnerEspera} aria-hidden="true" />
						<p className={styles.esperaTexto}>Esperando datos del broker MQTT…</p>
					</div>
				) : (
					camasArray.map((cama) => (
						<BedCard
							key={cama.id}
							cama={cama}
							onSelect={(camaId) => setSelectedCamaId(camaId)}
						/>
					))
				)}
			</main>

			{selectedCama && (
				<DetailModal
					cama={selectedCama}
					onClose={() => setSelectedCamaId(null)}
				/>
			)}
		</div>
	);
}
