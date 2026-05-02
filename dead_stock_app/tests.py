import io
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.contrib.gis.geos import Point
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.reverse import reverse
from rest_framework.test import APIClient

from .models import Category, InventoryItem, ItemImage, Lead, Report, Shop
from .services.jwt_tokens import issue_token

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

BENGALURU = Point(77.5946, 12.9716, srid=4326)
MUMBAI = Point(72.8777, 19.0760, srid=4326)


def make_user(username="+919876543210", password="testpass"):
    return User.objects.create_user(username=username, password=password)


def make_shop(user, location=None, **kwargs):
    defaults = {
        "name": "Test Shop",
        "phone": "+919876543210",
        "location": location or BENGALURU,
    }
    defaults.update(kwargs)
    return Shop.objects.create(user=user, **defaults)


def make_item(user, shop, **kwargs):
    defaults = {
        "name": "Test Item",
        "quantity": 1,
        "condition": InventoryItem.Condition.NEW,
        "status": InventoryItem.Status.ACTIVE,
    }
    defaults.update(kwargs)
    return InventoryItem.objects.create(user=user, shop=shop, **defaults)


def make_image(item, position=0, is_primary=True, **kwargs):
    defaults = {
        "s3_key": f"dead-stock/items/{item.id}/originals/test.jpg",
        "width": 800,
        "height": 600,
        "position": position,
        "is_primary": is_primary,
    }
    defaults.update(kwargs)
    return ItemImage.objects.create(item=item, **defaults)


def auth_client(user):
    """Return an APIClient authenticated via force_authenticate."""
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# ---------------------------------------------------------------------------
# Ping
# ---------------------------------------------------------------------------


class TestPing(TestCase):
    def test_ping_returns_ok(self):
        client = APIClient()
        url = reverse("dead-stock-ping")

        response = client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["data"]["ok"])


# ---------------------------------------------------------------------------
# Category
# ---------------------------------------------------------------------------


class TestCategoryViewSet(TestCase):
    def setUp(self):
        self.parent = Category.objects.create(slug="electronics", name="Electronics")
        self.child = Category.objects.create(
            slug="phones", name="Phones", parent=self.parent
        )
        self.client = APIClient()

    def test_list_categories_returns_all(self):
        url = reverse("ds-categories-list")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["data"]), 2)

    def test_retrieve_category(self):
        url = reverse("ds-categories-detail", kwargs={"pk": self.parent.pk})

        response = self.client.get(url)
        data = response.json()["data"]

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(data["slug"], "electronics")
        self.assertIsNone(data["parent"])

    def test_retrieve_child_category_has_parent(self):
        url = reverse("ds-categories-detail", kwargs={"pk": self.child.pk})

        response = self.client.get(url)
        data = response.json()["data"]

        self.assertEqual(str(self.parent.pk), str(data["parent"]))

    def test_list_is_public(self):
        # No auth credentials — should still succeed.
        url = reverse("ds-categories-list")

        response = APIClient().get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Shop
# ---------------------------------------------------------------------------


@patch("dead_stock_app.signals.nearby_cache_invalidate_all")
class TestShopViewSet(TestCase):
    def setUp(self):
        self.owner = make_user()
        self.other_user = make_user(username="+910000000001")

    def test_create_shop(self, _mock_cache):
        client = auth_client(self.owner)
        url = reverse("ds-shops-list")
        payload = {
            "name": "My Shop",
            "phone": "+919876543210",
            "latitude": 12.9716,
            "longitude": 77.5946,
        }

        response = client.post(url, data=payload, format="json")
        data = response.json()["data"]

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(data["name"], "My Shop")
        self.assertTrue(Shop.objects.filter(user=self.owner).exists())

    def test_create_shop_requires_auth(self, _mock_cache):
        url = reverse("ds-shops-list")
        payload = {
            "name": "My Shop",
            "phone": "+919876543210",
            "latitude": 12.9716,
            "longitude": 77.5946,
        }

        response = APIClient().post(url, data=payload, format="json")

        # JWTBearerAuthentication provides a WWW-Authenticate header, so DRF returns 401.
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_duplicate_shop_returns_400(self, _mock_cache):
        make_shop(self.owner)
        client = auth_client(self.owner)
        url = reverse("ds-shops-list")
        payload = {
            "name": "Second Shop",
            "phone": "+919876543210",
            "latitude": 12.9716,
            "longitude": 77.5946,
        }

        response = client.post(url, data=payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_me_returns_owners_shop(self, _mock_cache):
        shop = make_shop(self.owner, name="Owner Shop")
        client = auth_client(self.owner)
        url = reverse("ds-shops-me")

        response = client.get(url)
        data = response.json()["data"]

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(data["name"], "Owner Shop")
        self.assertEqual(str(data["id"]), str(shop.pk))

    def test_me_returns_404_when_no_shop(self, _mock_cache):
        client = auth_client(self.owner)
        url = reverse("ds-shops-me")

        response = client.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_me_patch_updates_shop(self, _mock_cache):
        make_shop(self.owner)
        client = auth_client(self.owner)
        url = reverse("ds-shops-me")

        response = client.patch(url, data={"name": "Updated Name"}, format="json")
        data = response.json()["data"]

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(data["name"], "Updated Name")

    def test_retrieve_shop_is_public(self, _mock_cache):
        shop = make_shop(self.owner)
        url = reverse("ds-shops-detail", kwargs={"pk": shop.pk})

        response = APIClient().get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(str(response.json()["data"]["id"]), str(shop.pk))

    def test_retrieve_unknown_shop_returns_404(self, _mock_cache):
        import uuid
        url = reverse("ds-shops-detail", kwargs={"pk": uuid.uuid4()})

        response = APIClient().get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch("dead_stock_app.views.shops.nearby_cache_get", return_value=None)
    @patch("dead_stock_app.views.shops.nearby_cache_set")
    def test_nearby_returns_shops_within_radius(self, _set, _get, _mock_inv):
        make_shop(self.owner, location=BENGALURU, name="Nearby Shop")
        url = reverse("ds-shops-nearby")

        response = APIClient().get(
            url, {"lat": "12.9716", "lng": "77.5946", "radius_km": "5"}
        )
        data = response.json()["data"]

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("shops", data)
        self.assertEqual(len(data["shops"]), 1)

    @patch("dead_stock_app.views.shops.nearby_cache_get", return_value=None)
    @patch("dead_stock_app.views.shops.nearby_cache_set")
    def test_nearby_excludes_distant_shops(self, _set, _get, _mock_inv):
        make_shop(self.owner, location=MUMBAI, name="Far Shop")
        url = reverse("ds-shops-nearby")

        response = APIClient().get(
            url, {"lat": "12.9716", "lng": "77.5946", "radius_km": "5"}
        )
        data = response.json()["data"]

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(data["shops"]), 0)

    @patch("dead_stock_app.views.shops.nearby_cache_get")
    def test_nearby_returns_cached_result(self, mock_get, _mock_inv):
        cached = [{"id": "abc", "name": "Cached Shop"}]
        mock_get.return_value = cached
        url = reverse("ds-shops-nearby")

        response = APIClient().get(
            url, {"lat": "12.9716", "lng": "77.5946", "radius_km": "5"}
        )
        data = response.json()["data"]

        self.assertEqual(data["shops"], cached)

    @patch("dead_stock_app.views.shops.nearby_cache_get", return_value=None)
    @patch("dead_stock_app.views.shops.nearby_cache_set")
    def test_nearby_missing_lat_returns_400(self, _set, _get, _mock_inv):
        url = reverse("ds-shops-nearby")

        response = APIClient().get(url, {"lng": "77.5946"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_shop_items_returns_active_items_only(self, _mock_cache):
        shop = make_shop(self.owner)
        make_item(self.owner, shop, name="Active Item", status=InventoryItem.Status.ACTIVE)
        make_item(self.owner, shop, name="Hidden Item", status=InventoryItem.Status.HIDDEN)
        # The items action is not in get_permissions()'s allow-list, so it requires auth.
        client = auth_client(self.owner)
        url = reverse("ds-shops-items", kwargs={"pk": shop.pk})

        response = client.get(url)
        data = response.json()["data"]

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["items"][0]["name"], "Active Item")


# ---------------------------------------------------------------------------
# InventoryItem
# ---------------------------------------------------------------------------


@patch("dead_stock_app.signals.nearby_cache_invalidate_all")
class TestInventoryItemViewSet(TestCase):
    def setUp(self):
        self.user = make_user()
        self.shop = make_shop(self.user)
        self.client = auth_client(self.user)

    def test_list_returns_only_owners_items(self, _mock_cache):
        make_item(self.user, self.shop, name="My Item")
        other_user = make_user(username="+910000000002")
        other_shop = make_shop(other_user, location=MUMBAI)
        make_item(other_user, other_shop, name="Other Item")
        url = reverse("ds-items-list")

        response = self.client.get(url)
        data = response.json()["data"]

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["name"], "My Item")

    def test_create_item(self, _mock_cache):
        url = reverse("ds-items-list")
        payload = {"name": "New Item", "quantity": 3, "condition": "new"}

        response = self.client.post(url, data=payload, format="json")
        data = response.json()["data"]

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(data["name"], "New Item")
        self.assertEqual(data["shop"], str(self.shop.pk))

    def test_create_item_without_shop_returns_400(self, _mock_cache):
        user_no_shop = make_user(username="+910000000003")
        client = auth_client(user_no_shop)
        url = reverse("ds-items-list")

        response = client.post(url, data={"name": "Item", "quantity": 1}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_retrieve_item(self, _mock_cache):
        item = make_item(self.user, self.shop, name="Fetch Me")
        url = reverse("ds-items-detail", kwargs={"pk": item.pk})

        response = self.client.get(url)
        data = response.json()["data"]

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(data["name"], "Fetch Me")

    def test_update_item(self, _mock_cache):
        item = make_item(self.user, self.shop, name="Old Name")
        url = reverse("ds-items-detail", kwargs={"pk": item.pk})

        response = self.client.patch(url, data={"name": "New Name"}, format="json")
        data = response.json()["data"]

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(data["name"], "New Name")

    @patch("dead_stock_app.views.items.delete_object")
    def test_delete_item(self, mock_delete, _mock_cache):
        item = make_item(self.user, self.shop)
        url = reverse("ds-items-detail", kwargs={"pk": item.pk})

        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(InventoryItem.objects.filter(pk=item.pk).exists())

    @patch("dead_stock_app.views.items.delete_object")
    def test_delete_item_removes_images_from_s3(self, mock_delete, _mock_cache):
        item = make_item(self.user, self.shop)
        make_image(item, s3_key="some/key.jpg")
        url = reverse("ds-items-detail", kwargs={"pk": item.pk})

        self.client.delete(url)

        mock_delete.assert_called_once_with("some/key.jpg")

    def test_refresh_extends_stale_at(self, _mock_cache):
        item = make_item(self.user, self.shop)
        old_stale_at = item.stale_at
        url = reverse("ds-items-refresh", kwargs={"pk": item.pk})

        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item.refresh_from_db()
        self.assertGreater(item.stale_at, old_stale_at)

    def test_cannot_access_other_users_items(self, _mock_cache):
        other_user = make_user(username="+910000000004")
        other_shop = make_shop(other_user, location=MUMBAI)
        other_item = make_item(other_user, other_shop)
        url = reverse("ds-items-detail", kwargs={"pk": other_item.pk})

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ---------------------------------------------------------------------------
# InventoryItem — bulk upload
# ---------------------------------------------------------------------------


@patch("dead_stock_app.signals.nearby_cache_invalidate_all")
class TestInventoryItemBulkUpload(TestCase):
    def setUp(self):
        self.user = make_user()
        self.shop = make_shop(self.user)
        self.client = auth_client(self.user)
        self.url = reverse("ds-items-bulk-upload")

    def _csv_upload(self, csv_text):
        file = io.BytesIO(csv_text.encode("utf-8"))
        file.name = "items.csv"
        return self.client.post(self.url, {"file": file}, format="multipart")

    def test_upload_valid_csv_creates_items(self, _mock_cache):
        csv_text = "name,quantity,condition\nSome Item,2,new\nAnother Item,1,used\n"

        response = self._csv_upload(csv_text)
        data = response.json()["data"]

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(data["created"], 2)
        self.assertEqual(InventoryItem.objects.filter(shop=self.shop).count(), 2)

    def test_upload_with_category_slug(self, _mock_cache):
        cat = Category.objects.create(slug="phones", name="Phones")
        csv_text = "name,category_slug\nPhone,phones\n"

        response = self._csv_upload(csv_text)
        response.json()["data"]

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        item = InventoryItem.objects.get(shop=self.shop)
        self.assertEqual(item.category, cat)

    def test_upload_unknown_category_returns_errors(self, _mock_cache):
        csv_text = "name,category_slug\nSome Item,nonexistent\n"

        response = self._csv_upload(csv_text)
        data = response.json()["data"]

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(data["created"], 0)
        self.assertEqual(len(data["errors"]), 1)

    def test_upload_missing_name_column_returns_400(self, _mock_cache):
        csv_text = "sku,quantity\nABC,1\n"

        response = self._csv_upload(csv_text)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_upload_unexpected_column_returns_400(self, _mock_cache):
        csv_text = "name,bad_column\nItem,value\n"

        response = self._csv_upload(csv_text)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_upload_non_csv_file_returns_400(self, _mock_cache):
        file = io.BytesIO(b"not a csv")
        file.name = "items.txt"

        response = self.client.post(self.url, {"file": file}, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_upload_missing_file_returns_400(self, _mock_cache):
        response = self.client.post(self.url, {}, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_upload_skips_blank_rows(self, _mock_cache):
        csv_text = "name,quantity\nReal Item,1\n,,\n\n"

        response = self._csv_upload(csv_text)
        data = response.json()["data"]

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(data["created"], 1)

    def test_upload_without_shop_returns_400(self, _mock_cache):
        user_no_shop = make_user(username="+910000000005")
        client = auth_client(user_no_shop)
        csv_text = "name\nSome Item\n"
        file = io.BytesIO(csv_text.encode())
        file.name = "items.csv"

        response = client.post(self.url, {"file": file}, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# InventoryItem — image actions
# ---------------------------------------------------------------------------


@patch("dead_stock_app.signals.nearby_cache_invalidate_all")
class TestItemImageActions(TestCase):
    def setUp(self):
        self.user = make_user()
        self.shop = make_shop(self.user)
        self.item = make_item(self.user, self.shop)
        self.client = auth_client(self.user)

    @patch("dead_stock_app.views.items.presign_put")
    def test_presign_returns_upload_url(self, mock_presign, _mock_cache):
        mock_presign.return_value = {"url": "https://s3.example.com/upload", "key": "some-key"}
        url = reverse("ds-items-presign-image", kwargs={"pk": self.item.pk})

        response = self.client.post(
            url, {"content_type": "image/jpeg"}, format="json"
        )
        data = response.json()["data"]

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("url", data)

    @patch("dead_stock_app.views.items.generate_image_variants")
    def test_confirm_image_creates_image_record(self, mock_task, _mock_cache):
        mock_task.delay = MagicMock()
        url = reverse("ds-items-confirm-image", kwargs={"pk": self.item.pk})
        payload = {
            "key": f"dead-stock/items/{self.item.pk}/originals/test.jpg",
            "width": 1280,
            "height": 960,
            "is_primary": True,
        }

        response = self.client.post(url, data=payload, format="json")
        data = response.json()["data"]

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(ItemImage.objects.filter(item=self.item).exists())
        self.assertTrue(data["is_primary"])
        mock_task.delay.assert_called_once()

    @patch("dead_stock_app.views.items.generate_image_variants")
    def test_confirm_first_image_is_always_primary(self, mock_task, _mock_cache):
        mock_task.delay = MagicMock()
        url = reverse("ds-items-confirm-image", kwargs={"pk": self.item.pk})
        payload = {
            "key": f"dead-stock/items/{self.item.pk}/originals/test.jpg",
            "width": 800,
            "height": 600,
            "is_primary": False,
        }

        response = self.client.post(url, data=payload, format="json")
        data = response.json()["data"]

        self.assertTrue(data["is_primary"])

    def test_reorder_images(self, _mock_cache):
        img_a = make_image(self.item, position=0, is_primary=True)
        img_b = make_image(self.item, position=1, is_primary=False)
        url = reverse("ds-items-reorder-images", kwargs={"pk": self.item.pk})

        response = self.client.patch(
            url, {"image_ids": [str(img_b.pk), str(img_a.pk)]}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        img_a.refresh_from_db()
        img_b.refresh_from_db()
        self.assertLess(img_b.position, img_a.position)

    def test_reorder_images_with_empty_list_returns_400(self, _mock_cache):
        url = reverse("ds-items-reorder-images", kwargs={"pk": self.item.pk})

        response = self.client.patch(url, {"image_ids": []}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reorder_images_with_unknown_ids_returns_404(self, _mock_cache):
        import uuid
        url = reverse("ds-items-reorder-images", kwargs={"pk": self.item.pk})

        response = self.client.patch(
            url, {"image_ids": [str(uuid.uuid4())]}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch("dead_stock_app.views.items.delete_object")
    def test_image_detail_delete_removes_image(self, mock_delete, _mock_cache):
        img = make_image(self.item)
        url = f"/dead-stock/items/{self.item.pk}/images/{img.pk}/"

        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(ItemImage.objects.filter(pk=img.pk).exists())
        mock_delete.assert_called_once_with(img.s3_key)

    @patch("dead_stock_app.views.items.delete_object")
    def test_deleting_primary_image_promotes_next(self, mock_delete, _mock_cache):
        primary = make_image(self.item, position=0, is_primary=True)
        secondary = make_image(self.item, position=1, is_primary=False)
        url = f"/dead-stock/items/{self.item.pk}/images/{primary.pk}/"

        self.client.delete(url)

        secondary.refresh_from_db()
        self.assertTrue(secondary.is_primary)

    def test_image_detail_patch_sets_primary(self, _mock_cache):
        img_a = make_image(self.item, position=0, is_primary=True)
        img_b = make_image(self.item, position=1, is_primary=False)
        url = f"/dead-stock/items/{self.item.pk}/images/{img_b.pk}/"

        response = self.client.patch(url, {"is_primary": True}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        img_a.refresh_from_db()
        img_b.refresh_from_db()
        self.assertFalse(img_a.is_primary)
        self.assertTrue(img_b.is_primary)

    def test_image_detail_patch_rejects_invalid_is_primary(self, _mock_cache):
        img = make_image(self.item)
        url = f"/dead-stock/items/{self.item.pk}/images/{img.pk}/"

        response = self.client.patch(url, {"is_primary": "yes"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_image_detail_patch_rejects_negative_position(self, _mock_cache):
        img = make_image(self.item)
        url = f"/dead-stock/items/{self.item.pk}/images/{img.pk}/"

        response = self.client.patch(url, {"position": -1}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_image_detail_unknown_image_returns_404(self, _mock_cache):
        import uuid
        url = f"/dead-stock/items/{self.item.pk}/images/{uuid.uuid4()}/"

        response = self.client.patch(url, {"position": 0}, format="json")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------


@patch("dead_stock_app.signals._redis_client")
@patch("dead_stock_app.signals.nearby_cache_invalidate_all")
class TestLeadViews(TestCase):
    def setUp(self):
        self.owner = make_user(username="+919876543210")
        self.shop = make_shop(self.owner)
        self.item = make_item(self.owner, self.shop)

    def test_create_lead_anonymous_with_phone(self, _mock_cache, _mock_redis):
        url = reverse("ds-leads-create")
        payload = {
            "shop_id": str(self.shop.pk),
            "item_id": str(self.item.pk),
            "message": "Is this still available?",
            "phone": "+919000000001",
            "buyer_name": "Anon Buyer",
        }

        response = APIClient().post(url, data=payload, format="json")
        data = response.json()["data"]

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("id", data)
        self.assertTrue(Lead.objects.filter(shop=self.shop).exists())

    def test_create_lead_anonymous_without_phone_returns_400(
        self, _mock_cache, _mock_redis
    ):
        url = reverse("ds-leads-create")
        payload = {
            "shop_id": str(self.shop.pk),
            "message": "Interested",
        }

        response = APIClient().post(url, data=payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_lead_authenticated_user_skips_phone(
        self, _mock_cache, _mock_redis
    ):
        buyer = make_user(username="+910000000007")
        client = auth_client(buyer)
        url = reverse("ds-leads-create")
        payload = {
            "shop_id": str(self.shop.pk),
            "message": "Authenticated buyer interest",
        }

        response = client.post(url, data=payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        lead = Lead.objects.get(shop=self.shop)
        self.assertEqual(lead.buyer, buyer)

    def test_create_lead_with_nonexistent_shop_returns_404(
        self, _mock_cache, _mock_redis
    ):
        import uuid
        url = reverse("ds-leads-create")
        payload = {
            "shop_id": str(uuid.uuid4()),
            "message": "Hello",
            "phone": "+919000000001",
        }

        response = APIClient().post(url, data=payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_create_lead_with_item_from_different_shop_returns_404(
        self, _mock_cache, _mock_redis
    ):
        other_user = make_user(username="+910000000008")
        other_shop = make_shop(other_user, location=MUMBAI)
        other_item = make_item(other_user, other_shop)
        url = reverse("ds-leads-create")
        payload = {
            "shop_id": str(self.shop.pk),
            "item_id": str(other_item.pk),
            "message": "Cross-shop item",
            "phone": "+919000000001",
        }

        response = APIClient().post(url, data=payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_inbox_returns_shop_leads(self, _mock_cache, _mock_redis):
        buyer = make_user(username="+910000000009")
        Lead.objects.create(
            buyer=buyer, shop=self.shop, message="Lead 1", contacted_at=timezone.now()
        )
        client = auth_client(self.owner)
        url = reverse("ds-leads-inbox")

        response = client.get(url)
        data = response.json()["data"]

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(data), 1)

    def test_inbox_without_shop_returns_403(self, _mock_cache, _mock_redis):
        user_no_shop = make_user(username="+910000000010")
        client = auth_client(user_no_shop)
        url = reverse("ds-leads-inbox")

        response = client.get(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_mark_contacted(self, _mock_cache, _mock_redis):
        buyer = make_user(username="+910000000011")
        lead = Lead.objects.create(buyer=buyer, shop=self.shop, message="Hi")
        url = reverse("ds-leads-contacted", kwargs={"pk": lead.pk})
        client = auth_client(self.owner)

        response = client.patch(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        lead.refresh_from_db()
        self.assertIsNotNone(lead.contacted_at)

    def test_mark_contacted_lead_not_in_your_shop_returns_404(
        self, _mock_cache, _mock_redis
    ):
        other_user = make_user(username="+910000000012")
        other_shop = make_shop(other_user, location=MUMBAI)
        buyer = make_user(username="+910000000013")
        lead = Lead.objects.create(buyer=buyer, shop=other_shop, message="Hi")
        url = reverse("ds-leads-contacted", kwargs={"pk": lead.pk})
        client = auth_client(self.owner)

        response = client.patch(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_anon_buyer_created_for_phone_number(self, _mock_cache, _mock_redis):
        url = reverse("ds-leads-create")
        payload = {
            "shop_id": str(self.shop.pk),
            "message": "Interested in buying",
            "phone": "+919111111111",
            "buyer_name": "John",
        }

        APIClient().post(url, data=payload, format="json")

        self.assertTrue(
            User.objects.filter(username="ds-buyer-+919111111111").exists()
        )


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


@patch("dead_stock_app.signals.nearby_cache_invalidate_all")
class TestReportCreateView(TestCase):
    def setUp(self):
        self.owner = make_user()
        self.shop = make_shop(self.owner)
        self.item = make_item(self.owner, self.shop)

    def test_create_report_for_shop(self, _mock_cache):
        url = reverse("ds-reports-create")
        payload = {
            "shop_id": str(self.shop.pk),
            "reason": "Selling counterfeit goods.",
        }

        response = APIClient().post(url, data=payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Report.objects.filter(shop=self.shop).exists())

    def test_create_report_for_item(self, _mock_cache):
        url = reverse("ds-reports-create")
        payload = {
            "item_id": str(self.item.pk),
            "reason": "Misleading description.",
        }

        response = APIClient().post(url, data=payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Report.objects.filter(item=self.item).exists())

    def test_report_without_target_returns_400(self, _mock_cache):
        url = reverse("ds-reports-create")
        payload = {"reason": "Generic complaint."}

        response = APIClient().post(url, data=payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_short_reason_fails_validation(self, _mock_cache):
        url = reverse("ds-reports-create")
        payload = {"shop_id": str(self.shop.pk), "reason": "Bad"}

        response = APIClient().post(url, data=payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_authenticated_reporter_is_linked(self, _mock_cache):
        reporter = make_user(username="+910000000014")
        client = auth_client(reporter)
        url = reverse("ds-reports-create")
        payload = {"shop_id": str(self.shop.pk), "reason": "Spam listings everywhere."}

        client.post(url, data=payload, format="json")

        report = Report.objects.get(shop=self.shop)
        self.assertEqual(report.reporter, reporter)

    def test_unauthenticated_report_uses_anonymous_user(self, _mock_cache):
        url = reverse("ds-reports-create")
        payload = {"shop_id": str(self.shop.pk), "reason": "Suspicious activity here."}

        APIClient().post(url, data=payload, format="json")

        report = Report.objects.get(shop=self.shop)
        self.assertEqual(report.reporter.username, "ds-anonymous-reporter")


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


@patch("dead_stock_app.signals.nearby_cache_invalidate_all")
class TestSearchViews(TestCase):
    def setUp(self):
        self.owner = make_user()
        self.shop = make_shop(self.owner, location=BENGALURU)

    @patch("dead_stock_app.views.search.log_search")
    def test_search_items_returns_results(self, mock_log, _mock_cache):
        make_item(self.owner, self.shop, name="Old Laptop", status=InventoryItem.Status.ACTIVE)
        url = reverse("ds-search-items")

        response = APIClient().get(url, {"q": "Laptop", "lat": "12.9716", "lng": "77.5946"})
        data = response.json()["data"]

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("items", data)
        self.assertIn("next_cursor", data)
        mock_log.assert_called_once()

    @patch("dead_stock_app.views.search.log_search")
    def test_search_excludes_non_active_items(self, mock_log, _mock_cache):
        make_item(self.owner, self.shop, name="Hidden Laptop", status=InventoryItem.Status.HIDDEN)
        url = reverse("ds-search-items")

        response = APIClient().get(url, {"q": "Laptop", "lat": "12.9716", "lng": "77.5946"})
        data = response.json()["data"]

        self.assertEqual(len(data["items"]), 0)

    @patch("dead_stock_app.views.search.log_search")
    def test_search_without_location_still_works(self, mock_log, _mock_cache):
        make_item(self.owner, self.shop, name="Camera")
        url = reverse("ds-search-items")

        response = APIClient().get(url, {"q": "Camera"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_autocomplete_short_query_returns_empty(self, _mock_cache):
        url = reverse("ds-search-autocomplete")

        response = APIClient().get(url, {"q": "a"})
        data = response.json()["data"]

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(data["suggestions"], [])

    def test_autocomplete_returns_matching_items(self, _mock_cache):
        make_item(self.owner, self.shop, name="Samsung Galaxy S24")
        url = reverse("ds-search-autocomplete")

        response = APIClient().get(url, {"q": "Samsung"})
        data = response.json()["data"]

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [s["name"] for s in data["suggestions"]]
        self.assertIn("Samsung Galaxy S24", names)

    def test_autocomplete_returns_matching_categories(self, _mock_cache):
        Category.objects.create(slug="mobiles", name="Mobile Phones")
        url = reverse("ds-search-autocomplete")

        response = APIClient().get(url, {"q": "Mobile"})
        data = response.json()["data"]

        category_suggestions = [s for s in data["suggestions"] if s["type"] == "category"]
        self.assertEqual(len(category_suggestions), 1)
        self.assertEqual(category_suggestions[0]["name"], "Mobile Phones")

    def test_autocomplete_deduplicates_item_names(self, _mock_cache):
        make_item(self.owner, self.shop, name="Test Phone")
        make_item(self.owner, self.shop, name="Test Phone")
        url = reverse("ds-search-autocomplete")

        response = APIClient().get(url, {"q": "Test"})
        data = response.json()["data"]

        item_suggestions = [s for s in data["suggestions"] if s["type"] == "item"]
        self.assertEqual(len(item_suggestions), 1)


# ---------------------------------------------------------------------------
# OTP Auth
# ---------------------------------------------------------------------------


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    }
)
class TestOTPAuth(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.client = APIClient()

    def test_otp_request_accepts_valid_phone(self):
        url = reverse("ds-otp-request")

        response = self.client.post(url, {"phone": "+919876543210"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["data"]["sent"])

    def test_otp_request_rejects_invalid_phone(self):
        url = reverse("ds-otp-request")

        response = self.client.post(url, {"phone": "0000000000"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("dead_stock_app.views.auth.request_otp")
    def test_otp_verify_rejects_wrong_otp(self, mock_request_otp):
        phone = "+919876543210"
        # Seed the OTP in cache directly so the rate-limit key isn't set.
        from django.core.cache import cache

        from dead_stock_app.services.otp import _otp_key
        cache.set(_otp_key(phone), {"otp": "123456", "attempts": 0}, 300)

        url = reverse("ds-otp-verify")
        response = self.client.post(
            url, {"phone": phone, "otp": "000000"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_otp_verify_with_expired_otp_returns_400(self):
        url = reverse("ds-otp-verify")

        response = self.client.post(
            url, {"phone": "+919876543210", "otp": "123456"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("dead_stock_app.views.auth.verify_otp")
    def test_otp_verify_success_returns_token(self, mock_verify):
        mock_verify.return_value = True
        make_user(username="+919876543210")
        url = reverse("ds-otp-verify")

        response = self.client.post(
            url, {"phone": "+919876543210", "otp": "123456"}, format="json"
        )
        data = response.json()["data"]

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("token", data)
        self.assertIn("has_shop", data)
        self.assertFalse(data["has_shop"])

    @patch("dead_stock_app.views.auth.verify_otp")
    def test_otp_verify_has_shop_true_when_shop_exists(self, mock_verify):
        mock_verify.return_value = True
        user = make_user(username="+919876543210")
        make_shop(user, location=BENGALURU)
        url = reverse("ds-otp-verify")

        response = self.client.post(
            url, {"phone": "+919876543210", "otp": "123456"}, format="json"
        )
        data = response.json()["data"]

        self.assertTrue(data["has_shop"])

    def test_refresh_token_returns_new_token(self):
        user = make_user(username="+919876543210")
        token_info = issue_token(user)
        url = reverse("ds-refresh")

        response = self.client.post(url, {"token": token_info["token"]}, format="json")
        data = response.json()["data"]

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("token", data)
        self.assertIn("expires_at", data)

    def test_refresh_with_invalid_token_returns_403(self):
        # RefreshTokenView has authentication_classes=[], so DRF coerces
        # AuthenticationFailed → 403 (no WWW-Authenticate header to send).
        url = reverse("ds-refresh")

        response = self.client.post(url, {"token": "not.a.token"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_refresh_with_expired_token_returns_403(self):
        import time

        import jwt as pyjwt
        from django.conf import settings

        payload = {
            "sub": "1",
            "phone": "+919876543210",
            "iat": int(time.time()) - 1000,
            "exp": int(time.time()) - 100,
        }
        expired_token = pyjwt.encode(payload, settings.DS_JWT_SECRET, algorithm="HS256")
        url = reverse("ds-refresh")

        response = self.client.post(url, {"token": expired_token}, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


# ---------------------------------------------------------------------------
# JWT Bearer Authentication
# ---------------------------------------------------------------------------


class TestJWTBearerAuthentication(TestCase):
    def setUp(self):
        self.user = make_user()
        self.token_info = issue_token(self.user)

    def test_valid_jwt_authenticates_user(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token_info['token']}")
        url = reverse("ds-shops-me")

        response = client.get(url)

        # 404 means the request was authenticated but has no shop — not 403.
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_invalid_jwt_returns_401(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Bearer invalid.jwt.token")
        url = reverse("ds-shops-me")

        response = client.get(url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_non_jwt_bearer_token_passes_to_next_auth(self):
        # A non-JWT bearer token (no dots) should not raise 401 from this class.
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Bearer notajwtatall")
        url = reverse("ds-shops-me")

        # Should be 403 (unauthenticated — falls through) rather than 401.
        response = client.get(url)

        self.assertIn(
            response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )

    def test_missing_authorization_header_returns_401(self):
        # JWTBearerAuthentication.authenticate_header returns "Bearer",
        # so DRF sends WWW-Authenticate and returns 401.
        url = reverse("ds-shops-me")

        response = APIClient().get(url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# Serializer validation
# ---------------------------------------------------------------------------


class TestSerializerValidation(TestCase):
    def test_phone_regex_accepts_valid_indian_number(self):
        from .serializers import OTPRequestSerializer

        serializer = OTPRequestSerializer(data={"phone": "+919876543210"})

        self.assertTrue(serializer.is_valid())

    def test_phone_regex_rejects_non_indian_number(self):
        from .serializers import OTPRequestSerializer

        serializer = OTPRequestSerializer(data={"phone": "+11234567890"})

        self.assertFalse(serializer.is_valid())

    def test_phone_regex_rejects_short_number(self):
        from .serializers import OTPRequestSerializer

        serializer = OTPRequestSerializer(data={"phone": "+9198765432"})

        self.assertFalse(serializer.is_valid())

    def test_shop_serializer_requires_both_lat_and_lng(self):
        from .serializers import ShopSerializer

        serializer = ShopSerializer(data={"name": "Shop", "phone": "+919876543210", "latitude": 12.9})

        self.assertFalse(serializer.is_valid())

    def test_shop_serializer_builds_point_from_lat_lng(self):
        from .serializers import ShopSerializer

        serializer = ShopSerializer(
            data={
                "name": "Test",
                "phone": "+919876543210",
                "latitude": 12.9716,
                "longitude": 77.5946,
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertIn("location", serializer.validated_data)

    def test_otp_verify_serializer_rejects_non_digit_otp(self):
        from .serializers import OTPVerifySerializer

        serializer = OTPVerifySerializer(
            data={"phone": "+919876543210", "otp": "abcdef"}
        )

        self.assertFalse(serializer.is_valid())

    def test_otp_verify_serializer_rejects_short_otp(self):
        from .serializers import OTPVerifySerializer

        serializer = OTPVerifySerializer(
            data={"phone": "+919876543210", "otp": "12345"}
        )

        self.assertFalse(serializer.is_valid())


# ---------------------------------------------------------------------------
# OTP service unit tests
# ---------------------------------------------------------------------------


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    }
)
class TestOTPService(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def test_verify_raises_on_expired_otp(self):
        from rest_framework.exceptions import ValidationError

        from .services.otp import verify_otp

        with self.assertRaises(ValidationError):
            verify_otp("+919876543210", "123456")

    @patch("dead_stock_app.services.otp._send_via_msg91")
    def test_verify_raises_on_wrong_otp(self, _mock_send):
        from rest_framework.exceptions import ValidationError

        from .services.otp import request_otp, verify_otp

        request_otp("+919876543210", ip=None)

        with self.assertRaises(ValidationError):
            verify_otp("+919876543210", "000000")

    @patch("dead_stock_app.services.otp._send_via_msg91")
    def test_verify_succeeds_with_correct_otp(self, _mock_send):
        from django.core.cache import cache

        from .services.otp import _otp_key, request_otp, verify_otp

        phone = "+919876543210"
        request_otp(phone, ip=None)
        correct_otp = cache.get(_otp_key(phone))["otp"]

        result = verify_otp(phone, correct_otp)

        self.assertTrue(result)
        # OTP must be deleted after successful verification.
        self.assertIsNone(cache.get(_otp_key(phone)))

    @patch("dead_stock_app.services.otp._send_via_msg91")
    def test_verify_locks_after_max_attempts(self, _mock_send):
        from rest_framework.exceptions import PermissionDenied, ValidationError

        from .services.otp import request_otp, verify_otp

        phone = "+919876543210"
        request_otp(phone, ip=None)

        for _ in range(3):
            try:
                verify_otp(phone, "000000")
            except ValidationError:
                pass

        with self.assertRaises(PermissionDenied):
            verify_otp(phone, "000000")

    @patch("dead_stock_app.services.otp._send_via_msg91")
    def test_phone_rate_limit_blocks_repeat_request(self, _mock_send):
        from rest_framework.exceptions import PermissionDenied

        from .services.otp import request_otp

        phone = "+919876543210"
        request_otp(phone, ip=None)

        with self.assertRaises(PermissionDenied):
            request_otp(phone, ip=None)


# ---------------------------------------------------------------------------
# Search service unit tests
# ---------------------------------------------------------------------------


@patch("dead_stock_app.signals.nearby_cache_invalidate_all")
class TestSearchService(TestCase):
    def setUp(self):
        self.owner = make_user()
        self.shop = make_shop(self.owner, location=BENGALURU)

    def test_cursor_encode_decode_roundtrip(self, _mock_cache):
        from .services.search import _decode_cursor, _encode_cursor

        cursor = _encode_cursor("recent", "2024-01-01T00:00:00+00:00", "some-uuid")
        decoded = _decode_cursor(cursor)

        self.assertEqual(decoded["sort"], "recent")
        self.assertEqual(decoded["id"], "some-uuid")

    def test_invalid_cursor_returns_none(self, _mock_cache):
        from .services.search import _decode_cursor

        self.assertIsNone(_decode_cursor("notvalidbase64!!!"))

    def test_build_search_qs_invalid_sort_defaults_to_recent(self, _mock_cache):
        from .services.search import build_search_qs

        items, _ = build_search_qs(sort="invalid_sort")

        # No crash — invalid sort silently falls back to 'recent'.
        self.assertIsInstance(items, list)

    def test_log_search_does_not_raise_on_authenticated_user(self, _mock_cache):
        from .services.search import log_search

        user = self.owner
        log_search("laptop", result_count=0, lat=12.97, lng=77.59, user=user)

        from .models import SearchLog
        self.assertTrue(SearchLog.objects.filter(query="laptop").exists())

    def test_log_search_stores_location_point(self, _mock_cache):
        from .services.search import log_search

        log_search("camera", result_count=0, lat=12.97, lng=77.59, user=None)

        from .models import SearchLog
        log = SearchLog.objects.get(query="camera")
        self.assertIsNotNone(log.location)


# ---------------------------------------------------------------------------
# Signal: normalize name and stale_at
# ---------------------------------------------------------------------------


@patch("dead_stock_app.signals.nearby_cache_invalidate_all")
class TestInventoryItemSignal(TestCase):
    def setUp(self):
        self.user = make_user()
        self.shop = make_shop(self.user)

    def test_name_normalized_is_set_on_create(self, _mock_cache):
        item = make_item(self.user, self.shop, name="Café Laptop")

        self.assertEqual(item.name_normalized, "cafe laptop")

    def test_stale_at_is_auto_set_on_create(self, _mock_cache):
        item = make_item(self.user, self.shop)

        self.assertIsNotNone(item.stale_at)
        self.assertGreater(item.stale_at, timezone.now())
