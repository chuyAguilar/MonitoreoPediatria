"""Persistencia del histórico de vitales: MQTT → SQLite (ADR-021).

Servicio de ingesta que corre EN el servidor: se suscribe a Mosquitto local y
persiste TODO mensaje de vitales y de estado, cada tick (decisión de
Dr. Milton: histórico crudo completo). Independiente del OCR, del dashboard y
del video; única dependencia pip: paho-mqtt. La base de datos contiene DATOS
DE PACIENTES: jamás al repo (.gitignore) y, en el servidor, fuera del working
tree de git. Ver ADR-021 y docs/ito2/REPRODUCIR_DESDE_CERO.md §1.4.
"""
