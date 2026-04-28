import random
import uuid
from datetime import timedelta

from django.contrib.auth.models import User
from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand
from django.utils import timezone

from dead_stock_app.models import Category, InventoryItem, Shop

DELHI_LAT = (28.4, 28.9)
DELHI_LNG = (76.8, 77.4)

ITEM_NAMES = [
    "Hammer", "Wrench", "Screwdriver", "Drill bit set", "Pliers",
    "Measuring tape", "Spirit level", "PVC pipe 1 inch", "Angle grinder",
    "Paint brush set", "Ceiling fan", "LED bulb 9W", "Extension cord 5m",
    "Electrical switch", "Wire 4mm", "Cement bag", "Sand bag", "Brick",
    "Steel rod 8mm", "Tile adhesive", "Waterproof paint", "Door hinge",
    "Padlock", "Drawer handle", "Shelf bracket", "Rubber gasket",
    "Ball valve 3/4 inch", "Copper pipe", "Soldering iron", "Heat gun",
    "Sandpaper 120 grit", "Wood glue", "Epoxy resin", "Safety gloves",
    "Safety goggles", "Dust mask", "Cable ties 100pk", "Wall anchor",
    "Bolt M8", "Nut M8",
]


class Command(BaseCommand):
    help = "Seed 1 000 shops and 50 000 items in Delhi NCR for load testing."

    def handle(self, *args, **options):
        self.stdout.write("Clearing old seed data…")
        Shop.objects.filter(name__startswith="Seed Shop ").delete()
        seed_user, _ = User.objects.get_or_create(
            username="seed-owner",
            defaults={"is_active": False, "first_name": "Seed"},
        )

        categories = list(Category.objects.all())
        self.stdout.write("Creating 1 000 shops…")

        shops = []

        for i in range(1000):
            lat = random.uniform(*DELHI_LAT)
            lng = random.uniform(*DELHI_LNG)
            shops.append(
                Shop(
                    id=uuid.uuid4(),
                    user=seed_user,
                    name=f"Seed Shop {i + 1}",
                    location=Point(lng, lat, srid=4326),
                    phone=f"+9198{random.randint(10000000, 99999999)}",
                )
            )

        Shop.objects.bulk_create(shops, ignore_conflicts=True)
        created_shops = list(Shop.objects.filter(name__startswith="Seed Shop "))
        self.stdout.write(f"  {len(created_shops)} shops ready.")

        self.stdout.write("Creating 50 000 items…")
        items = []
        now = timezone.now()

        for i in range(50000):
            shop = random.choice(created_shops)
            cat = random.choice(categories) if categories else None
            stale_offset = random.randint(1, 45)
            items.append(
                InventoryItem(
                    id=uuid.uuid4(),
                    user=seed_user,
                    shop=shop,
                    category=cat,
                    name=random.choice(ITEM_NAMES),
                    name_normalized=random.choice(ITEM_NAMES).lower(),
                    quantity=random.randint(1, 500),
                    price=round(random.uniform(10, 5000), 2),
                    condition=random.choice(
                        [InventoryItem.Condition.NEW, InventoryItem.Condition.USED]
                    ),
                    status=InventoryItem.Status.ACTIVE,
                    stale_at=now + timedelta(days=stale_offset),
                )
            )

        InventoryItem.objects.bulk_create(items, batch_size=1000, ignore_conflicts=True)
        self.stdout.write(self.style.SUCCESS("Done. 50 000 items seeded."))
