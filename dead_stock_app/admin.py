from datetime import timedelta

from django import forms
from django.contrib import admin, messages
from django.contrib.gis.geos import Point
from django.utils import timezone
from django.utils.safestring import mark_safe

from .models import Category, InventoryItem, ItemImage, Lead, Report, SearchLog, Shop

# ---------------------------------------------------------------------------
# Location picker widget — Nominatim autocomplete + MapLibre map with pin
# ---------------------------------------------------------------------------

_MAPLIBRE_CSS = "https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css"
_MAPLIBRE_JS = "https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"

# Inline OSM raster style — no API key required.
_MAP_STYLE = """{
  "version": 8,
  "sources": {
    "osm": {
      "type": "raster",
      "tiles": ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      "tileSize": 256,
      "attribution": "\\u00a9 <a href=\\"https://www.openstreetmap.org/copyright\\">OpenStreetMap</a> contributors"
    }
  },
  "layers": [{ "id": "osm", "type": "raster", "source": "osm" }]
}"""

# Default centre: India.
_DEFAULT_LNG = 78.9629
_DEFAULT_LAT = 20.5937
_DEFAULT_ZOOM = 5


class LocationPickerWidget(forms.Widget):
    """
    Renders a Nominatim address-search input with a MapLibre map and a
    centred red-pin crosshair. The map centre on submit becomes the location.
    """

    class Media:
        css = {"all": [_MAPLIBRE_CSS]}
        js = [_MAPLIBRE_JS]

    def render(self, name, value, attrs=None, renderer=None):
        lat, lng, zoom = _DEFAULT_LAT, _DEFAULT_LNG, _DEFAULT_ZOOM

        if value:
            if isinstance(value, str) and "," in value:
                try:
                    lat, lng = (float(p) for p in value.split(",", 1))
                    zoom = 15
                except ValueError:
                    pass
            elif hasattr(value, "y"):
                lat, lng, zoom = value.y, value.x, 15

        wid = (attrs or {}).get("id", f"id_{name}")

        html = f"""
<div id="{wid}-wrapper" style="max-width:700px;">
  <input type="hidden" name="{name}_lat" id="{wid}-lat" value="{lat if zoom == 15 else ''}">
  <input type="hidden" name="{name}_lng" id="{wid}-lng" value="{lng if zoom == 15 else ''}">

  <div style="position:relative;margin-bottom:8px;">
    <input type="text" id="{wid}-search"
      placeholder="Search for an address or area…"
      autocomplete="off"
      style="width:100%;padding:7px 36px 7px 10px;border:1px solid #ccc;
             border-radius:4px;font-size:13px;box-sizing:border-box;">
    <div id="{wid}-spinner"
      style="display:none;position:absolute;right:10px;top:50%;
             transform:translateY(-50%);width:16px;height:16px;">
      <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"
           style="width:16px;height:16px;animation:ds-spin 0.8s linear infinite;">
        <circle cx="12" cy="12" r="10" stroke="#ccc" stroke-width="3"/>
        <path d="M12 2a10 10 0 0 1 10 10" stroke="#555" stroke-width="3"
              stroke-linecap="round"/>
      </svg>
    </div>
    <style>@keyframes ds-spin {{ to {{ transform:translateY(-50%) rotate(360deg); }} }}</style>
    <div id="{wid}-results"
      style="display:none;position:absolute;top:100%;left:0;right:0;z-index:9999;
             background:#fff;border:1px solid #ccc;border-radius:4px;
             box-shadow:0 4px 12px rgba(0,0,0,.15);max-height:220px;overflow-y:auto;">
    </div>
  </div>

  <p style="font-size:12px;color:#666;margin:0 0 6px;">
    Search for an address, then drag the map to fine-tune the pin position.
  </p>

  <div style="position:relative;height:360px;border-radius:4px;
              overflow:hidden;border:1px solid #ccc;">
    <div id="{wid}-map" style="width:100%;height:100%;"></div>
    <div style="position:absolute;top:50%;left:50%;
                transform:translate(-50%,-100%);pointer-events:none;z-index:1;">
      <svg width="32" height="44" viewBox="0 0 32 44" fill="none">
        <path d="M16 0C7.16 0 0 7.16 0 16C0 28 16 44 16 44
                 C16 44 32 28 32 16C32 7.16 24.84 0 16 0Z" fill="#ef4444"/>
        <circle cx="16" cy="16" r="6" fill="white"/>
      </svg>
    </div>
  </div>

  <p id="{wid}-coords"
     style="font-size:12px;color:#666;margin:6px 0 0;">
    {f"Lat: {lat:.7f}, Lng: {lng:.7f}" if zoom == 15 else "No location selected yet."}
  </p>
</div>

<script>
(function () {{
  var WID   = {wid!r};
  var ILAT  = {lat};
  var ILNG  = {lng};
  var ZOOM  = {zoom};

  function boot() {{
    if (typeof maplibregl === "undefined") {{ setTimeout(boot, 80); return; }}

    var map = new maplibregl.Map({{
      container: WID + "-map",
      style: {_MAP_STYLE},
      center: [ILNG, ILAT],
      zoom: ZOOM,
    }});
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    map.on("load", function () {{ map.resize(); }});

    var reverseTimer;

    function sync() {{
      var c   = map.getCenter();
      var lat = c.lat.toFixed(7);
      var lng = c.lng.toFixed(7);
      document.getElementById(WID + "-lat").value = lat;
      document.getElementById(WID + "-lng").value = lng;
      document.getElementById(WID + "-coords").textContent =
        "Lat: " + lat + ", Lng: " + lng;

      clearTimeout(reverseTimer);
      var spinnerEl = document.getElementById(WID + "-spinner");
      var searchEl  = document.getElementById(WID + "-search");

      spinnerEl.style.display = "block";
      reverseTimer = setTimeout(function () {{
        fetch(
          "https://nominatim.openstreetmap.org/reverse?format=json&lat=" +
          lat + "&lon=" + lng,
          {{ headers: {{ "Accept-Language": "en" }} }}
        )
        .then(function (r) {{ return r.json(); }})
        .then(function (result) {{
          spinnerEl.style.display = "none";
          if (result && result.display_name) {{
            searchEl.value = result.display_name;
          }}
        }})
        .catch(function () {{ spinnerEl.style.display = "none"; }});
      }}, 600);
    }}

    map.on("moveend", sync);
    if (ZOOM === 15) sync();

    // Address search
    var searchEl  = document.getElementById(WID + "-search");
    var resultsEl = document.getElementById(WID + "-results");
    var spinnerEl = document.getElementById(WID + "-spinner");
    var timer;

    searchEl.addEventListener("input", function () {{
      clearTimeout(timer);
      var q = this.value.trim();
      if (q.length < 3) {{
        resultsEl.style.display = "none";
        spinnerEl.style.display = "none";
        return;
      }}

      spinnerEl.style.display = "block";

      timer = setTimeout(function () {{
        fetch(
          "https://nominatim.openstreetmap.org/search?format=json&limit=5&q=" +
          encodeURIComponent(q),
          {{ headers: {{ "Accept-Language": "en" }} }}
        )
        .then(function (r) {{ return r.json(); }})
        .then(function (items) {{
          spinnerEl.style.display = "none";
          resultsEl.innerHTML = "";
          if (!items.length) {{ resultsEl.style.display = "none"; return; }}

          items.forEach(function (item) {{
            var div = document.createElement("div");
            div.textContent = item.display_name;
            div.style.cssText =
              "padding:8px 12px;cursor:pointer;font-size:13px;color:#111;" +
              "border-bottom:1px solid #ddd;background:#fff;";
            div.addEventListener("mouseenter", function () {{
              this.style.background = "#e8eeff";
            }});
            div.addEventListener("mouseleave", function () {{
              this.style.background = "#fff";
            }});
            div.addEventListener("mousedown", function (e) {{
              e.preventDefault();
              map.jumpTo({{
                center: [parseFloat(item.lon), parseFloat(item.lat)],
                zoom: 15,
              }});
              searchEl.value = item.display_name;
              resultsEl.style.display = "none";
              spinnerEl.style.display = "none";
            }});
            resultsEl.appendChild(div);
          }});
          resultsEl.style.display = "block";
        }})
        .catch(function () {{
          spinnerEl.style.display = "none";
          resultsEl.style.display = "none";
        }});
      }}, 400);
    }});

    document.addEventListener("click", function (e) {{
      if (!searchEl.contains(e.target) && !resultsEl.contains(e.target)) {{
        resultsEl.style.display = "none";
      }}
    }});
  }}

  if (document.readyState === "loading") {{
    document.addEventListener("DOMContentLoaded", boot);
  }} else {{
    boot();
  }}
}})();
</script>
"""
        return mark_safe(html)

    def value_from_datadict(self, data, files, name):
        lat = data.get(f"{name}_lat", "").strip()
        lng = data.get(f"{name}_lng", "").strip()

        if lat and lng:
            return f"{lat},{lng}"

        return None


class LocationField(forms.Field):
    widget = LocationPickerWidget

    def prepare_value(self, value):
        if value and hasattr(value, "y"):
            return f"{value.y},{value.x}"
        return value

    def clean(self, value):
        if not value:
            raise forms.ValidationError("Please set a location on the map.")

        try:
            lat_str, lng_str = value.split(",", 1)
            lat, lng = float(lat_str), float(lng_str)
        except (ValueError, AttributeError):
            raise forms.ValidationError("Invalid location data.")

        return Point(lng, lat, srid=4326)


# ---------------------------------------------------------------------------
# Shop admin
# ---------------------------------------------------------------------------


class ShopAdminForm(forms.ModelForm):
    location = LocationField(label="Location")

    class Meta:
        model = Shop
        fields = ("user", "name", "address", "location", "city", "pincode", "phone",
                  "is_verified", "rating_avg")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance and self.instance.pk and self.instance.location:
            self.initial["location"] = (
                f"{self.instance.location.y},{self.instance.location.x}"
            )


@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    form = ShopAdminForm
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
