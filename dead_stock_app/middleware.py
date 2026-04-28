import sentry_sdk


class DeadStockSentryMiddleware:
    """Tag Sentry transactions originating from dead-stock routes."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/dead-stock/"):
            sentry_sdk.set_tag("feature", "dead_stock")

            if request.user and request.user.is_authenticated:
                import hashlib

                phone_hash = hashlib.sha256(
                    request.user.username.encode()
                ).hexdigest()[:16]
                sentry_sdk.set_user({"id": phone_hash})

        return self.get_response(request)
