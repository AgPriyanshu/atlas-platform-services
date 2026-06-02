from django.db import models

from shared.models import BaseModel
from shared.models.base_models import BaseModelWithoutUser

from .constants import MessageRole, MessageStatus


class LLM(BaseModelWithoutUser):
    name = models.TextField(verbose_name="Name")
    model_name = models.TextField(verbose_name="Model name")
    url = models.URLField(verbose_name="URL")

    class Meta:
        verbose_name = "LLM"
        verbose_name_plural = "LLMs"


class ChatSession(BaseModel):
    name = models.TextField(verbose_name="Name")
    llm = models.ForeignKey(
        LLM,
        on_delete=models.DO_NOTHING,
        verbose_name="LLM",
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "Chat session"
        verbose_name_plural = "Chat sessions"


class Message(BaseModel):
    session = models.ForeignKey(
        ChatSession,
        on_delete=models.DO_NOTHING,
        verbose_name="Session",
    )
    content = models.TextField(verbose_name="Content")
    role = models.CharField(
        max_length=20,
        choices=MessageRole.choices,
        default=MessageRole.USER,
        verbose_name="Role",
    )
    status = models.CharField(
        max_length=20,
        choices=MessageStatus.choices,
        default=MessageStatus.COMPLETE,
        verbose_name="Status",
    )

    class Meta:
        verbose_name = "Message"
        verbose_name_plural = "Messages"
