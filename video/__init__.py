"""Runner de video por cama: transmite una cámara a MediaMTX por RTSP.

Independiente del OCR (`ocr.publicar` es el runner de los datos; este es el del
video). Comparte con él la disciplina de identidad estable de dispositivos
(ADR-018) reusando `ocr.dispositivos` SOLO por importación — este paquete no
edita nada de `ocr/` y no necesita ninguna dependencia pip (solo el binario
`ffmpeg`). Ver ADR-020 y docs/ito2/REPRODUCIR_DESDE_CERO.md.
"""
