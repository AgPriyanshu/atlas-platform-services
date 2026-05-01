import random
import uuid
from datetime import timedelta

from django.contrib.auth.models import User
from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand
from django.utils import timezone

from dead_stock_app.models import Category, InventoryItem, Shop

NUM_SHOPS = 1000
NUM_ITEMS = 50_000

# Major Indian cities with bounding boxes and sample pincodes.
CITIES = [
    {
        "name": "Delhi",
        "lat": (28.40, 28.90),
        "lng": (76.80, 77.40),
        "pincodes": ["110001", "110005", "110011", "110019", "110045", "110060", "110092"],
    },
    {
        "name": "Mumbai",
        "lat": (18.90, 19.30),
        "lng": (72.70, 73.10),
        "pincodes": ["400001", "400011", "400022", "400050", "400069", "400080", "400093"],
    },
    {
        "name": "Bengaluru",
        "lat": (12.80, 13.10),
        "lng": (77.40, 77.80),
        "pincodes": ["560001", "560010", "560025", "560034", "560045", "560068", "560078"],
    },
    {
        "name": "Chennai",
        "lat": (12.90, 13.20),
        "lng": (80.10, 80.30),
        "pincodes": ["600001", "600010", "600018", "600028", "600040", "600060", "600083"],
    },
    {
        "name": "Kolkata",
        "lat": (22.40, 22.70),
        "lng": (88.20, 88.50),
        "pincodes": ["700001", "700010", "700019", "700031", "700045", "700060", "700075"],
    },
    {
        "name": "Hyderabad",
        "lat": (17.30, 17.55),
        "lng": (78.30, 78.60),
        "pincodes": ["500001", "500008", "500016", "500027", "500034", "500050", "500072"],
    },
    {
        "name": "Ahmedabad",
        "lat": (22.90, 23.15),
        "lng": (72.50, 72.75),
        "pincodes": ["380001", "380006", "380013", "380019", "380024", "380051", "380058"],
    },
    {
        "name": "Pune",
        "lat": (18.40, 18.70),
        "lng": (73.70, 74.00),
        "pincodes": ["411001", "411004", "411014", "411021", "411033", "411041", "411057"],
    },
    {
        "name": "Jaipur",
        "lat": (26.80, 27.05),
        "lng": (75.70, 76.00),
        "pincodes": ["302001", "302006", "302012", "302017", "302020", "302026", "302033"],
    },
    {
        "name": "Lucknow",
        "lat": (26.75, 26.95),
        "lng": (80.85, 81.05),
        "pincodes": ["226001", "226005", "226010", "226016", "226021", "226024", "226028"],
    },
    {
        "name": "Surat",
        "lat": (21.10, 21.30),
        "lng": (72.75, 72.95),
        "pincodes": ["395001", "395002", "395003", "395004", "395005", "395006", "395009"],
    },
    {
        "name": "Nagpur",
        "lat": (21.05, 21.25),
        "lng": (79.00, 79.25),
        "pincodes": ["440001", "440009", "440012", "440017", "440022", "440025", "440032"],
    },
    {
        "name": "Indore",
        "lat": (22.60, 22.82),
        "lng": (75.75, 75.95),
        "pincodes": ["452001", "452003", "452006", "452009", "452011", "452014", "452016"],
    },
    {
        "name": "Bhopal",
        "lat": (23.18, 23.35),
        "lng": (77.30, 77.55),
        "pincodes": ["462001", "462003", "462011", "462016", "462021", "462023", "462026"],
    },
    {
        "name": "Visakhapatnam",
        "lat": (17.60, 17.80),
        "lng": (83.20, 83.45),
        "pincodes": ["530001", "530003", "530007", "530012", "530016", "530020", "530026"],
    },
    {
        "name": "Patna",
        "lat": (25.55, 25.70),
        "lng": (85.05, 85.25),
        "pincodes": ["800001", "800003", "800006", "800009", "800012", "800014", "800020"],
    },
    {
        "name": "Vadodara",
        "lat": (22.20, 22.40),
        "lng": (73.10, 73.30),
        "pincodes": ["390001", "390002", "390004", "390007", "390011", "390015", "390019"],
    },
    {
        "name": "Coimbatore",
        "lat": (10.95, 11.15),
        "lng": (76.90, 77.10),
        "pincodes": ["641001", "641004", "641005", "641011", "641018", "641025", "641028"],
    },
    {
        "name": "Kochi",
        "lat": (9.90, 10.10),
        "lng": (76.20, 76.40),
        "pincodes": ["682001", "682005", "682011", "682016", "682018", "682020", "682023"],
    },
    {
        "name": "Chandigarh",
        "lat": (30.68, 30.80),
        "lng": (76.72, 76.88),
        "pincodes": ["160001", "160002", "160003", "160009", "160011", "160014", "160019"],
    },
]

LOCALITIES = [
    "Gandhi Nagar", "Nehru Colony", "Patel Nagar", "Indira Vihar", "Subhash Chowk",
    "Lal Bazaar", "Raj Marg", "Shastri Colony", "Tilak Nagar", "Ambedkar Road",
    "MG Road", "Anna Nagar", "Koramangala", "Bandra West", "Connaught Place",
    "Karol Bagh", "Lajpat Nagar", "Andheri East", "Whitefield", "Electronic City",
    "Salt Lake", "Park Street", "Banjara Hills", "Jubilee Hills", "Gachibowli",
    "Satellite", "Navrangpura", "Kothrud", "Wakad", "Aundh",
    "Vaishali Nagar", "Malviya Nagar", "Vikas Nagar", "Rajouri Garden", "Pitampura",
    "Gomti Nagar", "Hazratganj", "Ashok Nagar", "Adajan", "Pal",
    "Dharampeth", "Sadar", "Vijay Nagar", "Bhawarkuan", "Arera Colony",
    "Gajuwaka", "MVP Colony", "Kankarbagh", "Rajendra Nagar", "Alkapuri",
    "RS Puram", "Saibaba Colony", "Kaloor", "Edapally", "Vyttila",
]

STREET_SUFFIXES = ["Marg", "Road", "Nagar", "Colony", "Market", "Bazaar", "Chowk", "Lane", "Street", "Complex"]

SHOP_PREFIXES = [
    "Sharma", "Gupta", "Patel", "Singh", "Kumar", "Mehta", "Agarwal", "Joshi",
    "Rao", "Nair", "Reddy", "Iyer", "Chandra", "Verma", "Malhotra", "Bose",
    "Das", "Shah", "Khanna", "Mishra", "Tiwari", "Pandey", "Dubey", "Trivedi",
]

SHOP_SUFFIXES = [
    "Hardware", "Tools & Equipment", "Industrial Supplies", "Traders", "Enterprises",
    "Store", "Mart", "Centre", "Depot", "Wholesale", "Brothers", "General Store",
    "Electronics & Hardware", "Building Materials", "Auto Parts",
]

ITEM_NAMES = [
    # Hand tools
    "Hammer 500g", "Claw Hammer 600g", "Ball Peen Hammer", "Rubber Mallet",
    "Wrench 12 inch", "Adjustable Spanner", "Pipe Wrench", "Ring Spanner Set",
    "Screwdriver Set 6pc", "Flat Head Screwdriver", "Phillips Screwdriver",
    "Torque Screwdriver", "Pliers Set", "Nose Pliers", "Wire Cutter Pliers",
    "Vice Grip Pliers", "Hacksaw Frame", "Hacksaw Blade 12 inch",
    "Hand Saw", "Bow Saw", "Coping Saw",
    # Power tools
    "Drill Machine 550W", "Drill Machine 750W", "Angle Grinder 4 inch",
    "Angle Grinder 5 inch", "Jigsaw Machine", "Circular Saw",
    "Drill Bit Set 13pc HSS", "Masonry Bit Set", "Wood Chisel Set",
    "Reciprocating Saw", "Belt Sander", "Random Orbital Sander",
    # Measuring & marking
    "Measuring Tape 5m", "Measuring Tape 8m", "Digital Vernier Caliper",
    "Spirit Level 24 inch", "Spirit Level 48 inch", "Combination Square",
    "Chalk Line Reel", "Marking Gauge",
    # Electrical
    "LED Bulb 9W", "LED Bulb 12W", "LED Tube Light 20W", "CFL Bulb 23W",
    "Extension Cord 5m", "Extension Cord 10m", "Electrical Switch",
    "MCB 16A", "MCB 32A", "Wire 1.5mm 90m Roll", "Wire 4mm 90m Roll",
    "Electrical Tape", "Junction Box", "Conduit Pipe 20mm",
    "Ceiling Fan Regulator", "Dimmer Switch",
    # Plumbing
    "PVC Pipe 1/2 inch", "PVC Pipe 3/4 inch", "PVC Pipe 1 inch",
    "CPVC Pipe 1/2 inch", "CPVC Pipe 3/4 inch",
    "Ball Valve 1/2 inch", "Ball Valve 3/4 inch", "Gate Valve",
    "Rubber Gasket", "PTFE Thread Tape", "Pipe Union", "Pipe Elbow 90",
    "Copper Pipe 15mm", "Water Tank Float Valve",
    # Fasteners
    "Bolt M6 x 30mm (50pk)", "Bolt M8 x 40mm (50pk)", "Bolt M10 x 50mm (25pk)",
    "Nut M6 (100pk)", "Nut M8 (100pk)", "Washer M8 (100pk)",
    "Wood Screw 1 inch (100pk)", "Wood Screw 2 inch (100pk)",
    "Self Tapping Screw (100pk)", "Wall Rawl Plug (100pk)",
    "Expansion Anchor M10 (50pk)", "Stainless Steel Nail (500g)",
    # Building materials
    "Cement 50kg", "White Cement 5kg", "Putty 20kg", "Tile Adhesive 20kg",
    "Waterproofing Compound 5L", "Epoxy Grout 1kg",
    "POP Powder 25kg", "Sand Fine 40kg bag",
    "Steel Rod 8mm (6m)", "Steel Rod 10mm (6m)", "MS Flat Bar",
    # Safety
    "Safety Helmet", "Safety Goggles", "Dust Mask N95", "Safety Gloves Leather",
    "Ear Muffs", "Safety Harness", "Reflective Vest",
    # Hardware & fixtures
    "Door Hinge 4 inch (2pc)", "Drawer Handle 96mm", "Cabinet Knob",
    "Padlock 40mm", "Padlock 60mm", "Door Stopper", "Shelf Bracket 12 inch",
    "L Bracket 3 inch", "Drawer Slide 18 inch", "Piano Hinge",
    # Paints & solvents
    "Enamel Paint White 1L", "Enamel Paint White 4L",
    "Primer Red Oxide 1L", "Thinner 1L", "Turpentine 1L",
    "Spray Paint Silver 300ml", "Wood Polish 500ml",
    # Abrasives & adhesives
    "Sandpaper 80 Grit (10pk)", "Sandpaper 120 Grit (10pk)",
    "Sandpaper 220 Grit (10pk)", "Emery Cloth Roll",
    "Wood Glue 250ml", "Epoxy Adhesive 2-part", "Super Glue 10g",
    "Silicone Sealant White", "Silicone Sealant Transparent",
    # Misc
    "Cable Ties 150mm (100pk)", "Heat Shrink Tube Set",
    "Soldering Iron 25W", "Solder Wire", "Heat Gun 1500W",
    "Work Light 50W LED", "Magnetic Parts Tray",
]


def _random_address(locality: str, suffix: str, city: str) -> str:
    house_no = random.randint(1, 500)
    return f"{house_no}, {locality} {suffix}, {city}"


def _random_phone() -> str:
    prefix = random.choice(["6", "7", "8", "9"])
    return f"+91{prefix}{random.randint(100000000, 999999999)}"


class Command(BaseCommand):
    help = f"Seed {NUM_SHOPS} shops and {NUM_ITEMS:,} items across major Indian cities."

    def handle(self, *args, **options):
        self.stdout.write("Clearing old seed data…")
        old_users = User.objects.filter(username__startswith="seed-owner-")
        Shop.objects.filter(user__in=old_users).delete()
        old_users.delete()

        self.stdout.write(f"Creating {NUM_SHOPS} seed users…")
        users_to_create = [
            User(username=f"seed-owner-{i}", is_active=False, first_name="Seed")
            for i in range(NUM_SHOPS)
        ]
        User.objects.bulk_create(users_to_create, ignore_conflicts=True)
        seed_users = list(User.objects.filter(username__startswith="seed-owner-"))
        self.stdout.write(f"  {len(seed_users)} users ready.")

        categories = list(Category.objects.all())

        self.stdout.write(f"Creating {NUM_SHOPS} shops across India…")
        shops = []

        for i, user in enumerate(seed_users):
            city = random.choice(CITIES)
            lat = random.uniform(*city["lat"])
            lng = random.uniform(*city["lng"])
            locality = random.choice(LOCALITIES)
            suffix = random.choice(STREET_SUFFIXES)
            prefix = random.choice(SHOP_PREFIXES)
            shop_suffix = random.choice(SHOP_SUFFIXES)

            shops.append(
                Shop(
                    id=uuid.uuid4(),
                    user=user,
                    name=f"{prefix} {shop_suffix} - {city['name']} #{i + 1}",
                    address=_random_address(locality, suffix, city["name"]),
                    location=Point(lng, lat, srid=4326),
                    city=city["name"],
                    pincode=random.choice(city["pincodes"]),
                    phone=_random_phone(),
                    is_verified=random.random() < 0.3,
                    rating_avg=round(random.uniform(3.0, 5.0), 2),
                )
            )

        Shop.objects.bulk_create(shops, batch_size=500, ignore_conflicts=True)
        created_shops = list(Shop.objects.filter(user__in=seed_users))
        self.stdout.write(f"  {len(created_shops)} shops ready.")

        self.stdout.write(f"Creating {NUM_ITEMS:,} inventory items…")
        items = []
        now = timezone.now()

        for _ in range(NUM_ITEMS):
            shop = random.choice(created_shops)
            cat = random.choice(categories) if categories else None
            stale_offset = random.randint(1, 60)
            item_name = random.choice(ITEM_NAMES)

            items.append(
                InventoryItem(
                    id=uuid.uuid4(),
                    user=shop.user,
                    shop=shop,
                    category=cat,
                    name=item_name,
                    name_normalized=item_name.lower(),
                    quantity=random.randint(1, 500),
                    price=round(random.uniform(10, 15000), 2),
                    condition=random.choice(list(InventoryItem.Condition)),
                    status=InventoryItem.Status.ACTIVE,
                    stale_at=now + timedelta(days=stale_offset),
                )
            )

        InventoryItem.objects.bulk_create(items, batch_size=1000, ignore_conflicts=True)
        self.stdout.write(
            self.style.SUCCESS(
                f"Done. {len(created_shops)} shops and {NUM_ITEMS:,} items seeded across {len(CITIES)} Indian cities."
            )
        )
