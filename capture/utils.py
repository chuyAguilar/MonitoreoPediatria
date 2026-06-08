"""Utilidades de conversión de frames de pyorbbecsdk a imágenes OpenCV (BGR).

Adaptado de los ejemplos oficiales de Orbbec:
https://github.com/orbbec/pyorbbecsdk/blob/v2-main/examples/utils.py
"""

from typing import Optional

import cv2
import numpy as np
from pyorbbecsdk import OBFormat, VideoFrame


def _i420_to_bgr(frame: np.ndarray, width: int, height: int) -> np.ndarray:
    y = frame[0:height, :]
    u = frame[height : height + height // 4].reshape(height // 2, width // 2)
    v = frame[height + height // 4 :].reshape(height // 2, width // 2)
    yuv_image = cv2.merge([y, u, v])
    return cv2.cvtColor(yuv_image, cv2.COLOR_YUV2BGR_I420)


def _nv12_to_bgr(frame: np.ndarray, width: int, height: int) -> np.ndarray:
    y = frame[0:height, :]
    uv = frame[height : height + height // 2].reshape(height // 2, width)
    yuv_image = cv2.merge([y, uv])
    return cv2.cvtColor(yuv_image, cv2.COLOR_YUV2BGR_NV12)


def _nv21_to_bgr(frame: np.ndarray, width: int, height: int) -> np.ndarray:
    y = frame[0:height, :]
    uv = frame[height : height + height // 2].reshape(height // 2, width)
    yuv_image = cv2.merge([y, uv])
    return cv2.cvtColor(yuv_image, cv2.COLOR_YUV2BGR_NV21)


def frame_to_bgr_image(frame: VideoFrame) -> Optional[np.ndarray]:
    """Convierte un VideoFrame de color (cualquier formato) a imagen BGR de OpenCV."""
    width = frame.get_width()
    height = frame.get_height()
    color_format = frame.get_format()
    data = np.asanyarray(frame.get_data())

    if color_format == OBFormat.RGB:
        image = np.resize(data, (height, width, 3))
        return cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    if color_format == OBFormat.BGR:
        return np.resize(data, (height, width, 3))
    if color_format == OBFormat.YUYV:
        image = np.resize(data, (height, width, 2))
        return cv2.cvtColor(image, cv2.COLOR_YUV2BGR_YUYV)
    if color_format == OBFormat.MJPG:
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    if color_format == OBFormat.I420:
        return _i420_to_bgr(data, width, height)
    if color_format == OBFormat.NV12:
        return _nv12_to_bgr(data, width, height)
    if color_format == OBFormat.NV21:
        return _nv21_to_bgr(data, width, height)
    if color_format == OBFormat.UYVY:
        image = np.resize(data, (height, width, 2))
        return cv2.cvtColor(image, cv2.COLOR_YUV2BGR_UYVY)

    print(f"Formato de color no soportado: {color_format}")
    return None


def depth_frame_to_mm(depth_frame) -> np.ndarray:
    """Convierte un DepthFrame a matriz float32 de profundidad en milímetros."""
    width = depth_frame.get_width()
    height = depth_frame.get_height()
    scale = depth_frame.get_depth_scale()
    depth_data = np.frombuffer(depth_frame.get_data(), dtype=np.uint16)
    depth_data = depth_data.reshape((height, width))
    return depth_data.astype(np.float32) * scale
