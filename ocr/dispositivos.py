"""Enumeración y resolución de dispositivos de captura V4L2 por identidad estable.

El índice `/dev/videoN` es una lotería de enumeración USB: en el banco
(10 ago 2026) una webcam robó `/dev/video0`, el OCR leyó la fuente equivocada
(todo `null`) y la capturadora reapareció en `/dev/video2` con un `/dev/video3`
de metadatos al lado. En un sistema clínico, apuntar por índice puede colgar
una cama de OTRA fuente (ADR-018).

Este módulo resuelve una **identidad estable** (serial, nombre, ruta `by-id`)
al **nodo de captura real**, y falla fuerte si la identidad pedida no está:
nunca cae en silencio a un `/dev/videoN` cualquiera.

Realidad del target verificada por sonda (Jetson Orin, capturadora UltraSemi
`345f:2131`):

    /dev/v4l/by-id/usb-UltraSemi_USB3_Video_35562055-video-index0 -> ../../video2
    /dev/v4l/by-id/usb-UltraSemi_USB3_Video_35562055-video-index1 -> ../../video3

- El nombre de tarjeta sysfs es IDÉNTICO en ambos nodos ("USB3 Video: USB3
  Video"): el nombre no distingue captura de metadatos, así que el nodo se
  elige por capacidades reales (`VIDIOC_QUERYCAP`), no por convención.
- `by-path` (`platform-3610000.usb-usb-0:1.3:1.0`) identifica el puerto
  físico: es el desempate para unidades idénticas (multi-cama futura).

Solo stdlib. `fcntl` (POSIX) se importa de forma perezosa: en Windows el
módulo se importa sin error y los tests trabajan con las costuras mockeadas.
"""

import os
import re
import struct
from dataclasses import dataclass
from glob import glob
from pathlib import Path

# Capacidades V4L2 (linux/videodev2.h)
V4L2_CAP_VIDEO_CAPTURE = 0x00000001
V4L2_CAP_META_CAPTURE = 0x00800000
V4L2_CAP_DEVICE_CAPS = 0x80000000

# _IOR('V', 0, struct v4l2_capability) — struct de 104 bytes
_VIDIOC_QUERYCAP = 0x80685600

_DIR_SYS = "/sys/class/video4linux"
_DIR_BY_ID = "/dev/v4l/by-id"
_DIR_BY_PATH = "/dev/v4l/by-path"

# El sufijo con que udev numera los nodos de un mismo dispositivo físico
_SUFIJO_INDEX = re.compile(r"-video-index\d+$")


# Identificadores demasiado genéricos para distinguir la capturadora de otra
# fuente: con la capturadora ausente y una webcam presente, "usb" o "camera"
# resolverían EN SILENCIO a la webcam — la clase exacta del incidente. Se
# rechazan en el arranque con un error accionable (usa el serial o el by-id).
_DEMASIADO_GENERICO = frozenset({
    "usb", "usb2", "usb3", "usb2.0", "usb3.0", "video", "camera", "webcam",
    "cam", "capture", "hdmi", "platform", "generic", "device",
})
_LARGO_MINIMO = 5


@dataclass(frozen=True)
class DispositivoCaptura:
    """Un dispositivo físico de video con todos sus nodos /dev/videoN."""

    nombre: str            # tarjeta según sysfs (puede no distinguir nodos)
    by_id: str             # identidad estable de udev (sin -video-indexN), o ""
    by_path: str           # puerto físico (sin -video-indexN), o ""
    serial: str            # best-effort: último token del by_id, o ""
    nodos: tuple           # ((ruta, capacidades), ...) en orden numérico natural
    nodos_captura: tuple   # rutas con V4L2_CAP_VIDEO_CAPTURE (>=2 = ambiguo)
    nodo_captura: str      # el ÚNICO nodo de captura, o "" (ninguno o varios)

    def coincide(self, aguja: str) -> bool:
        """Match por subcadena CAMPO POR CAMPO (nunca sobre campos concatenados:
        un haystack unido con espacios permitía matches que cruzan campos,
        como '35562055 platform', con semántica impredecible)."""
        return any(
            aguja in campo.lower()
            for campo in (self.by_id, self.by_path, self.nombre)
            if campo
        )


# --------------------------------------------------------------------------
# Costuras de lectura del sistema (mockeables en tests; solo tienen sentido
# en Linux — en otra plataforma devuelven vacío y listar_dispositivos lanza)
# --------------------------------------------------------------------------


def _hay_v4l2() -> bool:
    return os.path.isdir(_DIR_SYS)


def _nodos_video() -> list:
    return sorted(glob("/dev/video*"))


def _grupo_fisico(nodo: str) -> str:
    """Clave que agrupa los nodos de un mismo dispositivo físico.

    En sysfs, todos los /dev/videoN de un dispositivo UVC cuelgan de la misma
    interfaz USB: el realpath de .../videoN/device coincide. Si no se puede
    leer, cada nodo queda como su propio grupo (peor listado, nunca mezcla).
    """
    enlace = Path(_DIR_SYS) / Path(nodo).name / "device"
    try:
        return os.path.realpath(enlace)
    except OSError:
        return nodo


def _nombre_de_tarjeta(nodo: str) -> str:
    ruta = Path(_DIR_SYS) / Path(nodo).name / "name"
    try:
        return ruta.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _entradas_estables(directorio: str) -> list:
    """[(nombre_symlink, ruta_real_del_nodo)] de /dev/v4l/by-id o by-path."""
    entradas = []
    for ruta in sorted(glob(os.path.join(directorio, "*"))):
        entradas.append((os.path.basename(ruta), os.path.realpath(ruta)))
    return entradas


def _capacidades(nodo: str) -> int:
    """Capacidades reales del nodo vía VIDIOC_QUERYCAP (0 si no se puede leer).

    Usa `device_caps` (las del NODO) cuando el driver declara DEVICE_CAPS;
    `capabilities` describe el dispositivo entero y mentiría sobre el nodo.
    """
    import fcntl  # POSIX; perezoso para que el módulo importe en Windows

    try:
        fd = os.open(nodo, os.O_RDWR | os.O_NONBLOCK)
    except OSError:
        return 0
    try:
        buf = bytearray(104)
        fcntl.ioctl(fd, _VIDIOC_QUERYCAP, buf)
    except OSError:
        return 0
    finally:
        os.close(fd)
    _driver, _card, _bus, _ver, capabilities, device_caps = struct.unpack(
        "<16s32s32sIII", bytes(buf[:92])
    )
    if capabilities & V4L2_CAP_DEVICE_CAPS:
        return device_caps
    return capabilities


# --------------------------------------------------------------------------
# Enumeración y resolución
# --------------------------------------------------------------------------


def listar_dispositivos() -> list:
    """Enumera los dispositivos físicos de video con sus nodos y capacidades."""
    if not _hay_v4l2():
        raise RuntimeError(
            "La resolución por identidad requiere Linux/V4L2 (no existe "
            f"{_DIR_SYS}). En esta plataforma usa una ruta o índice explícito."
        )

    por_nodo_by_id = {real: nombre for nombre, real in _entradas_estables(_DIR_BY_ID)}
    por_nodo_by_path = {real: nombre for nombre, real in _entradas_estables(_DIR_BY_PATH)}

    grupos = {}
    for nodo in _nodos_video():
        grupos.setdefault(_grupo_fisico(nodo), []).append(nodo)

    dispositivos = []
    for _grupo, nodos in sorted(grupos.items()):
        # Orden numérico NATURAL: 'video10' va después de 'video2' (el orden
        # lexicográfico de cadenas los invertiría y elegiría mal).
        nodos = sorted(nodos, key=_clave_natural)
        caps = {n: _capacidades(n) for n in nodos}
        de_captura = tuple(n for n in nodos if caps[n] & V4L2_CAP_VIDEO_CAPTURE)
        by_id = _base_estable(nodos, por_nodo_by_id)
        by_path = _base_estable(nodos, por_nodo_by_path)
        dispositivos.append(DispositivoCaptura(
            nombre=_nombre_de_tarjeta(nodos[0]),
            by_id=by_id,
            by_path=by_path,
            serial=_serial_de(by_id),
            nodos=tuple((n, caps[n]) for n in nodos),
            nodos_captura=de_captura,
            # Solo hay "el nodo de captura" si es ÚNICO: con varios (capturadora
            # dual-HDMI) elegir uno en silencio podría leer la entrada sin señal.
            nodo_captura=de_captura[0] if len(de_captura) == 1 else "",
        ))
    return dispositivos


def resolver(identificador: str) -> str:
    """Resuelve una identidad estable al nodo de captura. Lanza si no puede.

    `identificador` es una subcadena (insensible a mayúsculas) del nombre
    `by-id`, del `by-path` o del nombre de tarjeta — p. ej. el serial
    "35562055" o el modelo "UltraSemi". Las rutas (`/dev/...`) y los índices
    NO pasan por aquí: son literales y el usuario manda (ver FuenteCapturadora).

    Reglas deterministas:
    - exactamente 1 dispositivo coincide -> su nodo de captura;
    - 0 -> RuntimeError con lo disponible (nunca un fallback a /dev/video0:
      así fue como se leyó una webcam en el banco);
    - >=2 -> RuntimeError pidiendo desambiguar (serial o by-path);
    - coincide pero sin nodo con capacidad de captura -> RuntimeError.
    """
    aguja = identificador.strip().lower()
    if not aguja:
        raise RuntimeError("Identificador de capturadora vacío.")
    if len(aguja) < _LARGO_MINIMO or aguja in _DEMASIADO_GENERICO:
        raise RuntimeError(
            f"Identificador {identificador!r} demasiado genérico: con la "
            f"capturadora ausente podría coincidir EN SILENCIO con otra fuente "
            f"(una webcam), que es la clase del incidente que esta selección "
            f"evita. Usa el serial (p. ej. 35562055), un fragmento del by-id o "
            f"el by-path — ver --listar-dispositivos."
        )

    dispositivos = listar_dispositivos()
    coincidentes = [d for d in dispositivos if d.coincide(aguja)]

    if not coincidentes:
        raise RuntimeError(
            f"No hay ningún dispositivo de captura que coincida con "
            f"{identificador!r}. Detectados:\n{formatear_tabla(dispositivos)}\n"
            f"Usa --listar-dispositivos para ver identidades utilizables. "
            f"NO se cae a /dev/video0: apuntar al índice equivocado puede "
            f"leer otra fuente."
        )
    if len(coincidentes) > 1:
        raise RuntimeError(
            f"{identificador!r} es ambiguo: coincide con "
            f"{len(coincidentes)} dispositivos. Desambigua con el serial o "
            f"con el puerto físico (by-path):\n{formatear_tabla(coincidentes)}"
        )

    elegido = coincidentes[0]
    if len(elegido.nodos_captura) > 1:
        # Capturadora con VARIAS entradas de captura (dual-HDMI): elegir una en
        # silencio podría leer la entrada sin señal. Misma disciplina fail-hard.
        raise RuntimeError(
            f"{identificador!r} coincide con '{elegido.nombre}', pero ese "
            f"dispositivo tiene {len(elegido.nodos_captura)} nodos de captura "
            f"({', '.join(elegido.nodos_captura)}): no se elige uno en "
            f"silencio. Pasa la ruta explícita del nodo correcto "
            f"(--dispositivo /dev/videoN)."
        )
    if not elegido.nodo_captura:
        raise RuntimeError(
            f"{identificador!r} coincide con '{elegido.nombre}' pero ninguno "
            f"de sus nodos ({', '.join(n for n, _ in elegido.nodos)}) tiene "
            f"capacidad de captura de video (VIDIOC_QUERYCAP). ¿Dispositivo "
            f"ocupado o driver sin V4L2_CAP_VIDEO_CAPTURE?"
        )
    return elegido.nodo_captura


def formatear_tabla(dispositivos: list) -> str:
    """Tabla legible para el operador (la usa --listar-dispositivos y los errores)."""
    if not dispositivos:
        return "  (ningún dispositivo de video detectado)"
    lineas = []
    for d in dispositivos:
        nodos = ", ".join(
            f"{n}[{'captura' if c & V4L2_CAP_VIDEO_CAPTURE else 'metadatos'}]"
            for n, c in d.nodos
        )
        lineas.append(f"  - nombre : {d.nombre or '(sin nombre)'}")
        if d.serial:
            lineas.append(f"    serial : {d.serial}")
        if d.by_id:
            lineas.append(f"    by-id  : {d.by_id}")
        if d.by_path:
            lineas.append(f"    by-path: {d.by_path}")
        lineas.append(f"    nodos  : {nodos}")
        if len(d.nodos_captura) > 1:
            lineas.append(f"    captura: AMBIGUO ({', '.join(d.nodos_captura)}) "
                          f"— usa la ruta explícita")
        else:
            lineas.append(f"    captura: {d.nodo_captura or 'NINGUNO'}")
    return "\n".join(lineas)


def _clave_natural(nodo: str):
    """Ordena /dev/videoN por N numérico ('video10' después de 'video2')."""
    numero = re.search(r"(\d+)$", nodo)
    return (int(numero.group(1)) if numero else -1, nodo)


def _base_estable(nodos: list, por_nodo: dict) -> str:
    """Nombre del symlink estable (sin el sufijo -video-indexN) del dispositivo.

    Se prefiere el del nodo más bajo que tenga entrada; todos los nodos de un
    dispositivo comparten la base, así que da igual cuál aporte el nombre.
    """
    for nodo in nodos:
        nombre = por_nodo.get(nodo)
        if nombre:
            return _SUFIJO_INDEX.sub("", nombre)
    return ""


def _serial_de(by_id: str) -> str:
    """Serial best-effort: el último token del nombre by-id de udev.

    udev arma `usb-<vendor>_<modelo>_<serial>`; el serial es el último tramo
    tras '_' (p. ej. usb-UltraSemi_USB3_Video_35562055 -> 35562055). Es solo
    azúcar para mostrar: el match usa las cadenas completas.
    """
    coincidencia = re.search(r"_([A-Za-z0-9.\-]+)$", by_id)
    return coincidencia.group(1) if coincidencia else ""
