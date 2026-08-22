"""
Собственный KYC-пайплайн (замена стороннего MyID):

  Шаг 1 — паспорт/ID-карта Узбекистана: OCR извлекает серию, номер, ПИНФЛ, ФИО и даты;
           с фото документа вырезается лицо и кодируется в вектор (face embedding).
  Шаг 2 — селфи клиента: сверяется с лицом на документе (face match) и проверяется
           на «живость» (liveness) по нескольким кадрам с камеры (моргание/движение).

Все вычисления выполняются локально через open-source библиотеки
(opencv, face_recognition/dlib, pytesseract) — без внешних платных API.
"""
import logging
import re
from datetime import datetime
from typing import Optional

import cv2
import numpy as np
from django.conf import settings

logger = logging.getLogger(__name__)

# Серия ID-карты/паспорта РУз: 2 буквы (латиница) + 7 цифр, напр. "AD1234567".
SERIES_NUMBER_RE = re.compile(r'\b([A-Z]{2})\s?[-]?\s?(\d{7})\b')
# ПИНФЛ (JSHSHIR) — 14 цифр.
PINFL_RE = re.compile(r'\b(\d{14})\b')
DATE_RE = re.compile(r'\b(\d{2})[./-](\d{2})[./-](\d{4})\b')


class KYCProcessingError(Exception):
    """Не удалось обработать документ/селфи (нечитаемое фото, лицо не найдено и т.п.)."""


def get_verification_status(user) -> dict:
    """
    Сводный статус верификации личности для GET /users/me/verification/:
    {status: none|review|approved|rejected, rejection_reason, reviewed_at}
    Собирается из PassportDocument + FaceVerification (собственный KYC-пайплайн),
    с фолбэком на устаревший ручной KYCDocument, если новый флоу не пройден.
    """
    from ..models import PassportDocument, FaceVerification, KYCDocument

    face = FaceVerification.objects.filter(user=user).first()
    if face and face.status == FaceVerification.STATUS_PASSED:
        return {'status': 'approved', 'rejection_reason': None, 'reviewed_at': face.verified_at}
    if face and face.status == FaceVerification.STATUS_FAILED:
        return {'status': 'rejected', 'rejection_reason': face.fail_reason or None, 'reviewed_at': face.submitted_at}

    passport = PassportDocument.objects.filter(user=user).first()
    if passport and passport.status == PassportDocument.STATUS_REJECTED:
        return {'status': 'rejected', 'rejection_reason': passport.reject_reason or None, 'reviewed_at': None}
    if passport:
        return {'status': 'review', 'rejection_reason': None, 'reviewed_at': None}

    kyc_doc = KYCDocument.objects.filter(user=user).first()
    if kyc_doc:
        legacy_map = {
            KYCDocument.STATUS_APPROVED: 'approved',
            KYCDocument.STATUS_REJECTED: 'rejected',
            KYCDocument.STATUS_PENDING: 'review',
        }
        return {
            'status': legacy_map.get(kyc_doc.status, 'review'),
            'rejection_reason': kyc_doc.reject_reason or None,
            'reviewed_at': kyc_doc.reviewed_at,
        }

    return {'status': 'none', 'rejection_reason': None, 'reviewed_at': None}


def _read_rgb(django_file) -> np.ndarray:
    """Читает Django UploadedFile/ImageFieldFile в RGB numpy-массив."""
    django_file.seek(0)
    data = django_file.read()
    django_file.seek(0)
    buf = np.frombuffer(data, dtype=np.uint8)
    bgr = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if bgr is None:
        raise KYCProcessingError('Не удалось прочитать изображение.')
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def _encode_jpeg(rgb: np.ndarray) -> bytes:
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    ok, buf = cv2.imencode('.jpg', bgr, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise KYCProcessingError('Не удалось сохранить изображение.')
    return buf.tobytes()


def _largest_face_location(rgb: np.ndarray):
    import face_recognition
    locations = face_recognition.face_locations(rgb, model='hog')
    if not locations:
        return None
    # (top, right, bottom, left) — берём самое крупное лицо на кадре
    return max(locations, key=lambda loc: (loc[2] - loc[0]) * (loc[1] - loc[3]))


def extract_face(rgb: np.ndarray):
    """Находит лицо, возвращает (encoding: list[float], cropped_jpeg_bytes, location)."""
    import face_recognition

    location = _largest_face_location(rgb)
    if location is None:
        return None, None, None

    encodings = face_recognition.face_encodings(rgb, known_face_locations=[location])
    if not encodings:
        return None, None, None

    top, right, bottom, left = location
    pad_y = int((bottom - top) * 0.3)
    pad_x = int((right - left) * 0.3)
    h, w, _ = rgb.shape
    crop = rgb[max(0, top - pad_y):min(h, bottom + pad_y), max(0, left - pad_x):min(w, right + pad_x)]
    return encodings[0].tolist(), _encode_jpeg(crop), location


# ─── OCR (паспорт / ID-карта) ─────────────────────────────────────────────────

def _preprocess_for_ocr(rgb: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    gray = cv2.bilateralFilter(gray, 9, 75, 75)
    gray = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11
    )
    return gray


def _ocr_text(rgb: np.ndarray) -> str:
    import pytesseract
    processed = _preprocess_for_ocr(rgb)
    config = '--oem 3 --psm 6'
    text_uzb = pytesseract.image_to_string(processed, lang='uzb+rus+eng', config=config)
    if text_uzb.strip():
        return text_uzb
    return pytesseract.image_to_string(processed, lang='eng', config=config)


def _parse_date(day: str, month: str, year: str) -> Optional[str]:
    try:
        return datetime(int(year), int(month), int(day)).date().isoformat()
    except ValueError:
        return None


def _parse_full_name(text: str) -> str:
    candidates = []
    for line in text.splitlines():
        line = line.strip()
        # ФИО на документе обычно заглавными буквами (кириллица или латиница), 2-4 слова
        if re.fullmatch(r'[A-ZА-ЯЎҚҒҲЁ\'\- ]{6,60}', line) and 1 < len(line.split()) <= 4:
            candidates.append(line)
    return max(candidates, key=len) if candidates else ''


def parse_passport_fields(raw_text: str) -> dict:
    series = number = pinfl = ''
    m = SERIES_NUMBER_RE.search(raw_text.upper())
    if m:
        series, number = m.group(1), m.group(2)

    pm = PINFL_RE.search(raw_text)
    if pm:
        pinfl = pm.group(1)

    dates = [
        _parse_date(*match.groups())
        for match in DATE_RE.finditer(raw_text)
    ]
    dates = [d for d in dates if d]

    return {
        'series': series,
        'number': number,
        'pinfl': pinfl,
        'full_name': _parse_full_name(raw_text),
        # Эвристика: на документе обычно печатаются дата рождения, выдачи и окончания
        # в этом порядке; итоговые значения клиент всегда подтверждает/правит вручную.
        'birth_date': dates[0] if len(dates) > 0 else None,
        'issue_date': dates[1] if len(dates) > 1 else None,
        'expiry_date': dates[2] if len(dates) > 2 else None,
        'raw_text': raw_text,
    }


def process_passport_image(front_image_file) -> dict:
    """OCR + извлечение лица с фото документа. Поднимает KYCProcessingError если лицо не найдено."""
    rgb = _read_rgb(front_image_file)

    try:
        raw_text = _ocr_text(rgb)
    except Exception:
        logger.exception('Passport OCR failed')
        raw_text = ''

    fields = parse_passport_fields(raw_text)

    encoding, face_jpeg, _ = extract_face(rgb)
    if encoding is None:
        raise KYCProcessingError(
            'На фото документа не найдено лицо. Сделайте более чёткий снимок при хорошем освещении.'
        )

    fields['face_encoding'] = encoding
    fields['face_image'] = face_jpeg
    return fields


# ─── Face match + liveness (селфи) ────────────────────────────────────────────

def _eye_aspect_ratio(eye_points) -> float:
    eye = np.array(eye_points)
    a = np.linalg.norm(eye[1] - eye[5])
    b = np.linalg.norm(eye[2] - eye[4])
    c = np.linalg.norm(eye[0] - eye[3])
    if c == 0:
        return 0.0
    return (a + b) / (2.0 * c)


def _frame_ear(rgb: np.ndarray) -> Optional[float]:
    import face_recognition
    landmarks_list = face_recognition.face_landmarks(rgb)
    if not landmarks_list:
        return None
    landmarks = landmarks_list[0]
    if 'left_eye' not in landmarks or 'right_eye' not in landmarks:
        return None
    left = _eye_aspect_ratio(landmarks['left_eye'])
    right = _eye_aspect_ratio(landmarks['right_eye'])
    return (left + right) / 2.0


def check_liveness(frames: list) -> tuple:
    """
    Эвристическая проверка живости по нескольким кадрам с камеры:
      - на каждом кадре должно быть ровно одно лицо;
      - между кадрами должно быть заметное изменение (моргание — падение EAR,
        либо смещение положения лица), что отличает живого человека от статичного фото.
    Возвращает (passed: bool, score: float 0..1, reason: str).
    """
    if len(frames) < 2:
        return False, 0.0, 'Нужно минимум 2 кадра (например, обычный взгляд и моргание/поворот головы).'

    ears = []
    centers = []
    for rgb in frames:
        import face_recognition
        locations = face_recognition.face_locations(rgb, model='hog')
        if len(locations) != 1:
            return False, 0.0, 'На одном из кадров не найдено ровно одно лицо.'
        top, right, bottom, left = locations[0]
        centers.append(((left + right) / 2.0, (top + bottom) / 2.0))
        ears.append(_frame_ear(rgb))

    ear_values = [e for e in ears if e is not None]
    ear_delta = (max(ear_values) - min(ear_values)) if len(ear_values) >= 2 else 0.0

    face_widths = []
    for rgb in frames:
        import face_recognition
        loc = face_recognition.face_locations(rgb, model='hog')[0]
        face_widths.append(loc[1] - loc[3])
    avg_width = sum(face_widths) / len(face_widths) if face_widths else 1
    center_shift = max(
        np.linalg.norm(np.array(centers[i]) - np.array(centers[0]))
        for i in range(1, len(centers))
    ) if len(centers) > 1 else 0.0
    normalized_shift = center_shift / avg_width if avg_width else 0.0

    blink_detected = ear_delta >= settings.KYC_LIVENESS_EAR_DELTA
    movement_detected = normalized_shift >= settings.KYC_LIVENESS_MOVEMENT_RATIO

    score = min(1.0, max(ear_delta / max(settings.KYC_LIVENESS_EAR_DELTA, 1e-6),
                          normalized_shift / max(settings.KYC_LIVENESS_MOVEMENT_RATIO, 1e-6)) * 0.5)

    if blink_detected or movement_detected:
        return True, round(min(score, 1.0) or 0.6, 3), ''
    return False, round(score, 3), (
        'Не удалось подтвердить живость: моргните или слегка поверните голову между кадрами.'
    )


def match_face(doc_encoding: list, selfie_encoding: list) -> tuple:
    """Возвращает (passed: bool, score: float 0..1) на основе face_recognition.face_distance."""
    import face_recognition
    distance = face_recognition.face_distance(
        [np.array(doc_encoding)], np.array(selfie_encoding)
    )[0]
    score = max(0.0, 1.0 - float(distance))
    passed = float(distance) <= settings.KYC_FACE_MATCH_DISTANCE
    return passed, round(score, 3)


def process_face_verification(frame_files: list, doc_encoding: list) -> dict:
    """
    Полный шаг 2: liveness по кадрам + сверка первого кадра с лицом из документа.
    frame_files — список Django UploadedFile (1-3 шт., первый обязателен).
    """
    frames_rgb = [_read_rgb(f) for f in frame_files]

    primary_encoding, _, _ = extract_face(frames_rgb[0])
    if primary_encoding is None:
        raise KYCProcessingError('На селфи не найдено лицо. Сделайте снимок при хорошем освещении.')

    match_passed, match_score = match_face(doc_encoding, primary_encoding)

    if len(frames_rgb) >= 2:
        liveness_passed, liveness_score, liveness_reason = check_liveness(frames_rgb)
    else:
        liveness_passed, liveness_score, liveness_reason = (
            False, 0.0, 'Добавьте второй кадр (моргните или поверните голову) для проверки живости.'
        )

    return {
        'match_passed': match_passed,
        'match_score': match_score,
        'liveness_passed': liveness_passed,
        'liveness_score': liveness_score,
        'liveness_reason': liveness_reason,
    }
