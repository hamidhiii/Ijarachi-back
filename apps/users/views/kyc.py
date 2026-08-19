import logging

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from ..models import Profile, PassportDocument, FaceVerification
from ..serializers import (
    PassportUploadSerializer, PassportConfirmSerializer, PassportStatusSerializer,
    FaceVerifySerializer, FaceVerificationStatusSerializer,
)
from ..services.kyc import (
    process_passport_image, process_face_verification, KYCProcessingError,
)
from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)


class PassportUploadView(APIView):
    """
    POST /api/v1/kyc/passport/upload/
    Шаг 1: клиент загружает фото паспорта/ID-карты (с камеры или файлом).
    Сервер распознаёт данные документа и лицо через OCR — клиент затем
    подтверждает/правит их через PassportConfirmView.
    """
    permission_classes = [IsAuthenticated]
    throttle_scope = 'kyc'

    def post(self, request):
        serializer = PassportUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            extracted = process_passport_image(data['front_image'])
        except KYCProcessingError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except Exception:
            logger.exception('Passport processing failed for user %s', request.user.pk)
            return Response(
                {'detail': 'Не удалось обработать документ. Попробуйте снова со снимком получше.'},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        doc, _ = PassportDocument.objects.update_or_create(
            user=request.user,
            defaults={
                'document_type': data['document_type'],
                'front_image': data['front_image'],
                'back_image': data.get('back_image'),
                'series': extracted['series'],
                'number': extracted['number'],
                'pinfl': extracted['pinfl'],
                'full_name': extracted['full_name'],
                'birth_date': extracted['birth_date'],
                'issue_date': extracted['issue_date'],
                'expiry_date': extracted['expiry_date'],
                'raw_ocr_text': extracted['raw_text'],
                'face_encoding': extracted['face_encoding'],
                'status': PassportDocument.STATUS_PENDING,
                'reject_reason': '',
                'verified_at': None,
            },
        )
        doc.face_image.save(
            f'{request.user.pk}_face.jpg', ContentFile(extracted['face_image']), save=True
        )

        request.user.profile.verification_status = Profile.VERIFICATION_PENDING
        request.user.profile.save(update_fields=['verification_status'])

        return Response({
            'detail': 'Документ обработан. Проверьте распознанные данные и подтвердите их.',
            'extracted': {
                'series': extracted['series'],
                'number': extracted['number'],
                'pinfl': extracted['pinfl'],
                'full_name': extracted['full_name'],
                'birth_date': extracted['birth_date'],
                'issue_date': extracted['issue_date'],
                'expiry_date': extracted['expiry_date'],
            },
        }, status=status.HTTP_201_CREATED)

    def get(self, request):
        try:
            doc = request.user.passport
        except PassportDocument.DoesNotExist:
            return Response({'detail': 'Документ не загружен.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(PassportStatusSerializer(doc).data)


class PassportConfirmView(APIView):
    """
    POST /api/v1/kyc/passport/confirm/
    Шаг 1 (завершение): клиент подтверждает/правит распознанные данные документа.
    После валидации формата полей документ помечается подтверждённым, и клиент
    может переходить к шагу 2 (сверка лица).
    """
    permission_classes = [IsAuthenticated]
    throttle_scope = 'kyc'

    def post(self, request):
        try:
            doc = request.user.passport
        except PassportDocument.DoesNotExist:
            return Response(
                {'detail': 'Сначала загрузите фото документа.'}, status=status.HTTP_400_BAD_REQUEST
            )

        serializer = PassportConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        for field in ('series', 'number', 'pinfl', 'full_name', 'birth_date', 'issue_date', 'expiry_date'):
            if field in data:
                setattr(doc, field, data[field])
        doc.save(update_fields=['series', 'number', 'pinfl', 'full_name', 'birth_date', 'issue_date', 'expiry_date'])

        if not doc.face_encoding:
            return Response(
                {'detail': 'Не удалось распознать лицо на документе. Загрузите документ заново.'},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        doc.mark_verified()
        return Response(PassportStatusSerializer(doc).data)


class FaceVerifyView(APIView):
    """
    POST /api/v1/kyc/face/verify/
    Шаг 2: клиент присылает 1-3 кадра со своим лицом (с камеры или файлом).
    Первый кадр сверяется с лицом на документе (face match), а совокупность
    кадров используется для проверки живости (liveness — моргание/поворот головы).
    При успехе профиль автоматически помечается верифицированным.
    """
    permission_classes = [IsAuthenticated]
    throttle_scope = 'kyc'

    def post(self, request):
        try:
            doc = request.user.passport
        except PassportDocument.DoesNotExist:
            return Response(
                {'detail': 'Сначала пройдите проверку документа.'}, status=status.HTTP_400_BAD_REQUEST
            )
        if doc.status != PassportDocument.STATUS_VERIFIED or not doc.face_encoding:
            return Response(
                {'detail': 'Документ ещё не подтверждён.'}, status=status.HTTP_400_BAD_REQUEST
            )

        serializer = FaceVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        frames = [data['frame_1']]
        if data.get('frame_2'):
            frames.append(data['frame_2'])
        if data.get('frame_3'):
            frames.append(data['frame_3'])

        face_verification, _ = FaceVerification.objects.update_or_create(
            user=request.user,
            defaults={
                'frame_1': data['frame_1'],
                'frame_2': data.get('frame_2'),
                'frame_3': data.get('frame_3'),
                'status': FaceVerification.STATUS_PENDING,
            },
        )

        try:
            result = process_face_verification(frames, doc.face_encoding)
        except KYCProcessingError as exc:
            face_verification.mark_failed(str(exc))
            return Response({'detail': str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except Exception:
            logger.exception('Face verification failed for user %s', request.user.pk)
            face_verification.mark_failed('Внутренняя ошибка при обработке селфи.')
            return Response(
                {'detail': 'Не удалось обработать селфи. Попробуйте снова.'},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        if result['match_passed'] and result['liveness_passed']:
            face_verification.mark_passed(result['match_score'], result['liveness_score'])
            request.user.profile.mark_kyc_verified()
            try:
                from apps.notifications.models import AuditLog
                AuditLog.objects.create(
                    user=request.user,
                    action='kyc.verification.success',
                    metadata={
                        'match_score': result['match_score'],
                        'liveness_score': result['liveness_score'],
                    },
                )
            except Exception:
                logger.exception('Failed to write KYC audit log for user %s', request.user.pk)
        else:
            reasons = []
            if not result['match_passed']:
                reasons.append('Лицо не совпадает с фото на документе.')
            if not result['liveness_passed']:
                reasons.append(result['liveness_reason'] or 'Проверка живости не пройдена.')
            face_verification.mark_failed(
                ' '.join(reasons),
                match_score=result['match_score'],
                liveness_score=result['liveness_score'],
                face_match_passed=result['match_passed'],
                liveness_passed=result['liveness_passed'],
            )

        return Response(
            FaceVerificationStatusSerializer(face_verification).data,
            status=status.HTTP_200_OK if face_verification.status == FaceVerification.STATUS_PASSED
            else status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    def get(self, request):
        try:
            fv = request.user.face_verification
        except FaceVerification.DoesNotExist:
            return Response({'detail': 'Проверка лица не пройдена.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(FaceVerificationStatusSerializer(fv).data)
