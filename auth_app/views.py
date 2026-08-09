from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action
from rest_framework.exceptions import APIException
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from .serializers import AuthSerializer


class AuthViewSet(ViewSet):
    queryset = User.objects.all()
    permission_classes = [AllowAny]

    @action(detail=False, methods=["POST"], url_name="login")
    def login(self, request):
        request_body = request.data.copy()
        serializer = AuthSerializer(data=request_body)
        serializer.is_valid(raise_exception=True)

        user = authenticate(
            username=serializer.validated_data.get("username"),
            password=serializer.validated_data.get("password"),
        )

        if user:
            user_token = Token.objects.get_or_create(user=user)
            data = {"token": user_token[0].key}

            return Response(
                {
                    "message": "User login successful",
                    "data": data,
                }
            )
        else:
            return Response(
                {"message": "Invalid credentials"},
                status=status.HTTP_403_FORBIDDEN,
            )

    @action(
        detail=False,
        methods=["POST"],
        url_name="register",
    )
    def register(self, request):
        request_body = request.data.copy()
        serializer = AuthSerializer(data=request_body)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        user_details = {
            "username": validated_data["username"],
            "password": validated_data["password"],
        }

        # Check if user already exists.
        if User.objects.filter(username=user_details["username"]):
            raise APIException("User already exists")
        else:
            if is_staff := validated_data["is_staff"]:
                user_details["is_staff"] = is_staff

            User.objects.create_user(**user_details)

        return Response({"message": "User registered successfully"})
