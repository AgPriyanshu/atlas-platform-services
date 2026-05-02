import jwt
from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import Shop
from ..serializers import (
    OTPRequestSerializer,
    OTPVerifySerializer,
    RefreshTokenSerializer,
)
from ..services.jwt_tokens import decode_token, issue_token
from ..services.otp import request_otp, verify_otp


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


class OTPRequestView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request):
        serializer = OTPRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone = serializer.validated_data["phone"]
        request_otp(phone, ip=_client_ip(request))

        return Response({"sent": True})


class OTPVerifyView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request):
        serializer = OTPVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone = serializer.validated_data["phone"]
        otp = serializer.validated_data["otp"]

        verify_otp(phone, otp)

        user = User.objects.filter(username=phone).first()
        if not user or not Shop.objects.filter(user=user).exists():
            raise PermissionDenied(
                "No shop is registered for this number. "
                "Please sign up to create your shop first."
            )

        token = issue_token(user)

        return Response(
            {
                "token": token["token"],
                "expires_at": token["expires_at"],
                "user": {"id": user.id, "phone": user.username},
            }
        )


class RefreshTokenView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request):
        serializer = RefreshTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            payload = decode_token(serializer.validated_data["token"])
        except jwt.ExpiredSignatureError as exc:
            raise AuthenticationFailed("Token expired.") from exc
        except jwt.InvalidTokenError as exc:
            raise AuthenticationFailed("Invalid token.") from exc

        try:
            user = User.objects.get(pk=int(payload["sub"]))
        except (User.DoesNotExist, KeyError, ValueError) as exc:
            raise AuthenticationFailed("User not found.") from exc

        new_token = issue_token(user)
        return Response(
            {"token": new_token["token"], "expires_at": new_token["expires_at"]},
            status=status.HTTP_200_OK,
        )
