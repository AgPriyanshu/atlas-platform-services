from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from shared.views import BaseModelViewSet

from .models import LLM, ChatSession, Message
from .serializers import ChatSessionSerializer, LLMSerializer, MessageSerializer


class ChatSessionViewSet(BaseModelViewSet):
    queryset = ChatSession.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = ChatSessionSerializer


class LLMViewSet(viewsets.ModelViewSet):
    queryset = LLM.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = LLMSerializer


class MessageViewSet(BaseModelViewSet):
    queryset = Message.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = MessageSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        session_id = self.request.query_params.get("session_id")

        if session_id:
            qs = qs.filter(session_id=session_id)

        return qs.exclude(content="").order_by("created_at")

    @action(detail=False, methods=["get"], url_path="last")
    def last_message(self, request):
        """Return the most recent message for a session — used by the frontend on reconnect."""
        session_id = request.query_params.get("session_id")

        if not session_id:
            return Response({"error": "session_id is required."}, status=400)

        message = (
            Message.objects.filter(session_id=session_id, session__user=request.user)
            .order_by("-created_at")
            .first()
        )

        if message is None:
            return Response({"error": "No messages found."}, status=404)

        return Response(MessageSerializer(message).data)
