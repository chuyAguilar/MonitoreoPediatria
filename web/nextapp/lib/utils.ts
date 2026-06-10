/** Funciones de formato de valores compartidas entre componentes */

export function formatVal(val: number): string {
	return Number.isInteger(val) ? String(val) : val.toFixed(1);
}

export function formatTsCorto(tsIso: string): string {
	try {
		return new Date(tsIso).toLocaleTimeString('es-MX', {
			hour: '2-digit',
			minute: '2-digit',
			second: '2-digit',
			hour12: false,
		});
	} catch {
		return tsIso;
	}
}

export function formatPniTs(tsIso: string): string {
	try {
		return `últ. medición: ${new Date(tsIso).toLocaleTimeString('es-MX', {
			hour: '2-digit',
			minute: '2-digit',
			hour12: false,
		})}`;
	} catch {
		return '';
	}
}
