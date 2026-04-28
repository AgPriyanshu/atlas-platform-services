from datetime import timedelta

from django.contrib import admin, messages
from django.utils import timezone

from .models import Category, InventoryItem, ItemImage, Lead, Report, SearchLog, Shop


@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    list_display = ("name", "owner_phone", "city", "item_count", "is_verified", "created_at")
    list_filter = ("is_verified", "city")
    search_fields = ("name", "user__username", "phone")
    raw_id_fields = ("user",)
    actions = ["mark_verified", "unmark_verified", "disable_shop"]

    @admin.display(description="Owner phone")
    def owner_phone(self, obj):
        return obj.user.username if obj.user else "—"

    @admin.display(description="Items")
    def item_count(self, obj):
        return obj.items.filter(status=InventoryItem.Status.ACTIVE).count()

    @admin.action(description="Mark selected shops as verified")
    def mark_verified(self, request, queryset):
        updated = queryset.update(is_verified=True)
        self.message_user(request, f"{updated} shop(s) marked verified.", messages.SUCCESS)

    @admin.action(description="Remove verified status from selected shops")
    def unmark_verified(self, request, queryset):
        updated = queryset.update(is_verified=False)
        self.message_user(request, f"{updated} shop(s) unverified.", messages.SUCCESS)

    @admin.action(description="Disable selected shops (hide all active items)")
    def disable_shop(self, request, queryset):
        shop_ids = list(queryset.values_list("pk", flat=True))
        hidden = InventoryItem.objects.filter(
            shop_id__in=shop_ids, status=InventoryItem.Status.ACTIVE
        ).update(status=InventoryItem.Status.HIDDEN)
        self.message_user(
            request,
            f"Hidden {hidden} item(s) across {len(shop_ids)} shop(s).",
            messages.SUCCESS,
        )


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "parent")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    list_display = ("name", "shop", "quantity", "price", "status", "stale_at")
    list_filter = ("status", "condition", "category")
    search_fields = ("name", "sku", "shop__name")
    raw_id_fields = ("shop", "category", "user")
    actions = ["hide_items", "activate_items", "reset_stale_at"]

    @admin.action(description="Hide selected items")
    def hide_items(self, request, queryset):
        updated = queryset.update(status=InventoryItem.Status.HIDDEN)
        self.message_user(request, f"{updated} item(s) hidden.", messages.SUCCESS)

    @admin.action(description="Activate selected items")
    def activate_items(self, request, queryset):
        updated = queryset.update(status=InventoryItem.Status.ACTIVE)
        self.message_user(request, f"{updated} item(s) activated.", messages.SUCCESS)

    @admin.action(description="Reset stale_at to +30 days from now")
    def reset_stale_at(self, request, queryset):
        new_stale = timezone.now() + timedelta(days=30)
        updated = queryset.update(stale_at=new_stale)
        self.message_user(request, f"{updated} item(s) refreshed.", messages.SUCCESS)


@admin.register(ItemImage)
class ItemImageAdmin(admin.ModelAdmin):
    list_display = ("item", "position", "is_primary", "variants_ready", "created_at")
    raw_id_fields = ("item",)


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("shop", "buyer", "item", "contacted_at", "created_at")
    list_filter = ("contacted_at",)
    raw_id_fields = ("buyer", "shop", "item")
    search_fields = ("shop__name", "buyer__username")


@admin.register(SearchLog)
class SearchLogAdmin(admin.ModelAdmin):
    list_display = ("query", "result_count", "user", "created_at")
    search_fields = ("query",)
    raw_id_fields = ("user",)


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("status", "reason_excerpt", "item", "shop", "reporter", "created_at")
    list_filter = ("status",)
    raw_id_fields = ("item", "shop", "reporter")
    search_fields = ("reason",)
    actions = ["hide_reported_item", "hide_reported_shop", "mark_resolved", "reject_report"]

    @admin.display(description="Reason")
    def reason_excerpt(self, obj):
        return (obj.reason or "")[:60]

    @admin.action(description="Hide item(s) from reported listings")
    def hide_reported_item(self, request, queryset):
        count = 0

        for report in queryset.select_related("item"):
            if report.item and report.item.status == InventoryItem.Status.ACTIVE:
                report.item.status = InventoryItem.Status.HIDDEN
                report.item.save(update_fields=["status"])
                count += 1

        queryset.update(status=Report.Status.RESOLVED)
        self.message_user(request, f"{count} item(s) hidden and reports resolved.", messages.SUCCESS)

    @admin.action(description="Hide shop(s) from reported listings")
    def hide_reported_shop(self, request, queryset):
        shop_ids = set()

        for report in queryset.select_related("shop"):
            if report.shop:
                shop_ids.add(report.shop_id)

        hidden = InventoryItem.objects.filter(
            shop_id__in=shop_ids, status=InventoryItem.Status.ACTIVE
        ).update(status=InventoryItem.Status.HIDDEN)
        queryset.update(status=Report.Status.RESOLVED)
        self.message_user(
            request,
            f"Hidden {hidden} item(s) across {len(shop_ids)} shop(s).",
            messages.SUCCESS,
        )

    @admin.action(description="Mark selected reports as resolved")
    def mark_resolved(self, request, queryset):
        updated = queryset.update(status=Report.Status.RESOLVED)
        self.message_user(request, f"{updated} report(s) marked resolved.", messages.SUCCESS)

    @admin.action(description="Reject selected reports (no action taken)")
    def reject_report(self, request, queryset):
        updated = queryset.update(status=Report.Status.REJECTED)
        self.message_user(request, f"{updated} report(s) rejected.", messages.SUCCESS)
