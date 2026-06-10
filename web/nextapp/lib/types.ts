/** Tipos compartidos del contrato de datos v1.0 */

export interface Signo {
	valor: number | null;
	unidad: string;
}

export interface PNI {
	sis: number | null;
	dia: number | null;
	media: number | null;
	unidad: string;
	ts?: string;
}

export interface Signos {
	fc?: Signo;
	spo2?: Signo;
	fp?: Signo;
	fr?: Signo;
	temp?: Signo;
	pni?: PNI;
}

export interface CamaState {
	id: string;
	online: boolean;
	signos: Signos;
	origen: string;
	tsRaw: string;
	deviceId: string;
	/** timestamp Date.now() del último mensaje de vitales recibido */
	ultimoTs: number | null;
}

export type CamasMap = Record<string, CamaState>;
