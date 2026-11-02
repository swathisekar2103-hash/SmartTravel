
from flask import (
    Flask, render_template, request, jsonify,
    redirect, url_for
)
import requests
import os
import sqlite3
import re
import hashlib
import time
import threading
from dotenv import load_dotenv

# APP SETUP
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(BASE_DIR, ".env")
load_dotenv(ENV_FILE, override=True)


app = Flask(__name__)
app.secret_key = os.getenv(
    "FLASK_SECRET_KEY",
    "smart-travel-planner-local-key"
)

# Identify this app when using OpenStreetMap public services.
# Set OSM_CONTACT in your environment to a project contact email if available.
HEADERS = {
    "User-Agent": (
        "SmartTravelPlanner/1.0 "
        f"(contact: {os.getenv('OSM_CONTACT', 'configure-OSM_CONTACT')})"
    )
}
NOMINATIM_URL = "https://nominatim.openstreetmap.org"
_nominatim_lock = threading.Lock()
_last_nominatim_request = 0.0


def nominatim_get(endpoint, params):
    """Respect the public Nominatim limit of at most one request per second."""
    global _last_nominatim_request
    with _nominatim_lock:
        wait = 1.05 - (time.monotonic() - _last_nominatim_request)
        if wait > 0:
            time.sleep(wait)
        response = requests.get(
            f"{NOMINATIM_URL}/{endpoint}",
            params=params,
            headers=HEADERS,
            timeout=20,
        )
        _last_nominatim_request = time.monotonic()
    response.raise_for_status()
    return response


# Public Overpass instances. If one is busy or unavailable, try the next.
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

# DATABASE SETUP
DATABASE = os.path.join(BASE_DIR, "database", "travel.db")
os.makedirs(os.path.dirname(DATABASE), exist_ok=True)


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS packages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            package_name TEXT NOT NULL,
            destination TEXT NOT NULL,
            travel_date TEXT DEFAULT '',
            days INTEGER DEFAULT 1,
            travel_type TEXT DEFAULT '',
            budget REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS package_places (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            package_id INTEGER NOT NULL,
            place_id TEXT DEFAULT '',
            place_name TEXT NOT NULL,
            address TEXT DEFAULT '',
            image TEXT DEFAULT '',
            latitude REAL,
            longitude REAL,
            category TEXT DEFAULT '',
            FOREIGN KEY (package_id)
                REFERENCES packages(id)
                ON DELETE CASCADE,
            UNIQUE(package_id, place_name, address)
        )
    """)


    conn.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            package_id INTEGER NOT NULL,
            traveller_name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT NOT NULL,
            travellers INTEGER NOT NULL CHECK (travellers >= 1),
            price_per_person REAL NOT NULL,
            total_amount REAL NOT NULL,
            booked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (package_id) REFERENCES packages(id) ON DELETE CASCADE
        )
    """)

    # Public feedback shared across all visitors of this website.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


init_db()


# INTEREST CATEGORIES
INTEREST_CONFIG = {
    "nature": {
        "title": "🌿 Nature",
        "categories": (
            "leisure.park,leisure.park.garden,"
            "natural.forest,natural.coastal,natural.mountain"
        ),
        "keyword": "nature park",
        "image": (
            "https://images.unsplash.com/photo-1441974231531-c6227db76b6e"
            "?auto=format&fit=crop&w=1000&q=85"
        )
    },
    "food": {
        "title": "🍴 Food",
        "categories": (
            "catering.restaurant,catering.cafe,"
            "catering.fast_food,catering.food_court"
        ),
        "keyword": "restaurant food",
        "image": (
            "https://images.unsplash.com/photo-1517248135467-4c7edcad34c4"
            "?auto=format&fit=crop&w=1000&q=85"
        )
    },
    "historical": {
        "title": "🏛️ Historical",
        "categories": "tourism.sights,building.historic",
        "keyword": "historic monument",
        "image": (
            "https://images.unsplash.com/photo-1464822759023-fed622ff2c3b"
            "?auto=format&fit=crop&w=1000&q=85"
        )
    },
    "beach": {
        "title": "🏖️ Beach",
        "categories": "beach,natural.coastal,tourism.attraction",
        "keyword": "beach",
        "image": (
            "https://images.unsplash.com/photo-1507525428034-b723cf961d3e"
            "?auto=format&fit=crop&w=1000&q=85"
        )
    },
    "shopping": {
        "title": "🛍️ Shopping",
        "categories": "commercial.shopping_mall,commercial.marketplace",
        "keyword": "shopping mall",
        "image": (
            "https://images.unsplash.com/photo-1441986300917-64674bd600d8"
            "?auto=format&fit=crop&w=1000&q=85"
        )
    },
    "entertainment": {
        "title": "🎡 Entertainment",
        "categories": "entertainment,activity",
        "keyword": "entertainment",
        "image": (
            "https://images.unsplash.com/photo-1492684223066-81342ee5ff30"
            "?auto=format&fit=crop&w=1000&q=85"
        )
    },
    "adventure": {
        "title": "🧗 Adventure",
        "categories": "tourism.attraction,leisure.park",
        "keyword": "adventure hiking",
        "image": (
            "https://images.unsplash.com/photo-1551632811-561732d1e306"
            "?auto=format&fit=crop&w=1000&q=85"
        )
    },
    "photography": {
        "title": "📸 Photography",
        "categories": (
            "tourism.attraction.viewpoint,tourism.attraction,"
            "natural.coastal,natural.forest,leisure.park"
        ),
        "keyword": "scenic landscape",
        "image": (
            "https://images.unsplash.com/photo-1470770841072-f978cf4d019e"
            "?auto=format&fit=crop&w=1000&q=85"
        )
    }
}

# GEOCODING (OpenStreetMap Nominatim)

def _address_parts(result):
    """Return a consistent address dictionary from a Nominatim result."""
    address = result.get("address") or {}
    country = clean_text(address.get("country"))
    city = (
        clean_text(address.get("city"))
        or clean_text(address.get("town"))
        or clean_text(address.get("village"))
        or clean_text(address.get("municipality"))
        or clean_text(address.get("county"))
    )
    state = (
        clean_text(address.get("state"))
        or clean_text(address.get("state_district"))
        or clean_text(address.get("region"))
    )
    return city, state, country


def _normalize_geocode_result(item):
    city, state, country = _address_parts(item)
    name = clean_text(item.get("name"))
    address = clean_text(item.get("display_name"))
    result_type = clean_text(
        item.get("addresstype") or item.get("type") or item.get("class")
    ).casefold()

    # Nominatim's display_name is usually a full address. Use the most
    # meaningful locality as the visible destination name when possible.
    if not name:
        name = city or clean_text(item.get("display_name", "").split(",")[0])

    return {
        "name": name,
        "formatted": address,
        "city": city,
        "state": state,
        "country": country,
        "lat": item.get("lat"),
        "lon": item.get("lon"),
        "result_type": result_type,
        "osm_type": item.get("osm_type"),
        "osm_id": item.get("osm_id"),
    }


def geocode_destination(place, limit=5):
    """Search a destination with OpenStreetMap Nominatim."""
    original_place = clean_text(place)
    if original_place.casefold() in {"thanjavur", "tanjore"}:
        place = "Thanjavur, Tamil Nadu, India"

    response = nominatim_get("search", {
        "q": place,
        "format": "jsonv2",
        "addressdetails": 1,
        "namedetails": 1,
        "limit": limit,
        "accept-language": "en",
    })
    return [
        _normalize_geocode_result(item)
        for item in response.json()
    ]


# LOCATION HELPERS

def clean_text(value):
    if isinstance(value, str):
        return value.strip()
    return ""


def get_city(result):
    # Normalized search/place records already expose city.
    city = clean_text(result.get("city"))
    if city:
        return city
    address = result.get("address") or {}
    country = clean_text(address.get("country"))
    for key in ("city", "town", "village", "municipality", "county", "locality"):
        value = clean_text(address.get(key))
        if value and value.casefold() != country.casefold():
            return value
    return ""


def get_state(result):
    state = clean_text(result.get("state"))
    if state:
        return state
    address = result.get("address") or {}
    return (
        clean_text(address.get("state"))
        or clean_text(address.get("state_district"))
        or clean_text(address.get("region"))
    )


def select_best_result(results, original_query):
    if not results:
        return None

    query = clean_text(original_query).casefold()
    if query in {"thanjavur", "tanjore"}:
        query = "thanjavur"

    exact_matches = [
        item for item in results
        if any(
            clean_text(value).casefold() == query
            for value in (
                item.get("name"),
                item.get("city"),
                item.get("formatted"),
            )
            if clean_text(value)
        )
    ]
    candidates = exact_matches or results

    if query == "thanjavur":
        tamil_nadu_matches = [
            item for item in candidates
            if clean_text(item.get("state")).casefold() == "tamil nadu"
            and clean_text(item.get("country")).casefold() == "india"
        ]
        if tamil_nadu_matches:
            candidates = tamil_nadu_matches

    locality_types = {
        "city", "town", "village", "municipality", "suburb",
        "district", "locality", "administrative",
    }
    for item in candidates:
        if (
            clean_text(item.get("result_type")).casefold() in locality_types
            and get_city(item)
        ):
            return item

    for item in candidates:
        if get_city(item).casefold() == query:
            return item

    return candidates[0]


def make_destination_data(result, original_query):
    city = get_city(result)
    state = get_state(result)
    country = clean_text(result.get("country"))
    result_type = clean_text(result.get("result_type")).casefold()
    name = (
        clean_text(result.get("name"))
        or city or state or country or original_query
    )

    if result_type == "country":
        city = name or country
        state = "Not applicable"

    return {
        "name": name,
        "formatted": clean_text(result.get("formatted")) or original_query,
        "city": city or name or clean_text(original_query) or "Not available",
        "state": state or "Not available",
        "country": country or "Not available",
        "latitude": result.get("lat"),
        "longitude": result.get("lon"),
    }


# NEXT PART STARTS WITH IMAGE SEARCH

# IMAGE SEARCH

def get_place_image(place_name, destination, keyword, avoid_urls=None):
    """Find a place-specific photo on Wikimedia Commons.

    No generic stock-photo fallback is used: if Commons has no suitable
    result, return an empty image so the template can show a placeholder
    instead of a misleading photo of another place.
    """
    place_name = clean_text(place_name)
    destination = clean_text(destination)
    if not place_name:
        return {"image": "", "source": ""}

    search_text = f'"{place_name}" {destination}'.strip()
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": search_text,
        "gsrnamespace": 6,
        "gsrlimit": 8,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "iiurlwidth": 1000,
    }
    commons_headers = {
        **HEADERS,
        "Accept": "application/json",
    }

    try:
        response = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            params=params,
            headers=commons_headers,
            timeout=15,
        )
        response.raise_for_status()
        pages = (response.json().get("query") or {}).get("pages") or {}
    except (requests.RequestException, ValueError) as error:
        print(f"Wikimedia Commons image search failed for {place_name!r}: {error}")
        return {"image": "", "source": ""}

    avoided = set(avoid_urls or [])
    for page in pages.values():
        info_list = page.get("imageinfo") or []
        if not info_list:
            continue
        info = info_list[0]
        image_url = info.get("thumburl") or info.get("url") or ""
        if not image_url or image_url in avoided:
            continue

        metadata = info.get("extmetadata") or {}
        artist = clean_text((metadata.get("Artist") or {}).get("value", ""))
        license_name = clean_text((metadata.get("LicenseShortName") or {}).get("value", ""))
        description_url = info.get("descriptionurl", "")
        # Keep source as a plain URL because the place-details template uses
        # it as the href for its "View Image Source" link.
        return {"image": image_url, "source": description_url}

    print(f"No place-specific Wikimedia Commons photo found for {place_name!r}.")
    return {"image": "", "source": ""}


# SEARCH PLACES NEAR DESTINATION

def search_places(latitude, longitude, categories, destination, keyword):
    """Find nearby named places from OpenStreetMap using Overpass API."""
    if latitude is None or longitude is None:
        return []

    keyword_lower = (keyword or "").casefold()
    if "food" in keyword_lower or "restaurant" in keyword_lower:
        tag_filters = [
            '["amenity"~"^(restaurant|cafe|fast_food|food_court)$"]'
        ]
    elif "beach" in keyword_lower:
        tag_filters = [
            '["natural"="beach"]',
            '["leisure"="beach_resort"]',
            '["tourism"="attraction"]["name"]',
        ]
    elif "historic" in keyword_lower or "monument" in keyword_lower:
        tag_filters = [
            '["historic"]',
            '["tourism"~"^(museum|attraction|artwork)$"]',
        ]
    elif "shopping" in keyword_lower:
        tag_filters = [
            '["shop"]',
            '["shop"="mall"]',
            '["amenity"="marketplace"]',
        ]
    elif "entertainment" in keyword_lower:
        tag_filters = [
            '["leisure"~"^(amusement_arcade|water_park|stadium|sports_centre|theme_park)$"]',
            '["amenity"~"^(cinema|theatre|arts_centre)$"]',
        ]
    elif "adventure" in keyword_lower or "hiking" in keyword_lower:
        tag_filters = [
            '["route"="hiking"]',
            '["sport"~"^(climbing|hiking)$"]',
            '["tourism"="attraction"]',
            '["natural"~"^(peak|cave|waterfall)$"]',
        ]
    elif "nature" in keyword_lower or "scenic" in keyword_lower:
        tag_filters = [
            '["leisure"="park"]',
            '["natural"~"^(wood|forest|water|peak|waterfall)$"]',
            '["tourism"="viewpoint"]',
        ]
    else:
        tag_filters = [
            '["tourism"~"^(attraction|museum|viewpoint)$"]',
            '["historic"]',
        ]

    # Ask Overpass once per selected interest; only named features are useful
    # for the place cards and package workflow.
    selectors = []
    for tag_filter in tag_filters:
        selectors.extend([
            f'nwr(around:20000,{float(latitude)},{float(longitude)}){tag_filter}["name"];'
        ])
    query = "[out:json][timeout:25];(" + "".join(selectors) + ");out center tags;"

    elements = []
    last_error = None

    for overpass_url in OVERPASS_URLS:
        try:
            response = requests.post(
                overpass_url,
                data={"data": query},
                headers=HEADERS,
                timeout=45,
            )
            response.raise_for_status()
            elements = response.json().get("elements", [])
            # An empty valid result is still a successful response; do not
            # overload other public instances by repeating the same query.
            break
        except (requests.RequestException, ValueError) as error:
            last_error = error
            print(f"Overpass server failed ({overpass_url}): {error}")
            continue

    # Fallback: if every Overpass instance fails (or returns no matches),
    # make one respectful Nominatim search instead of returning immediately.
    # Nominatim is rate-limited by nominatim_get(), so do not loop/retry here.
    if not elements:
        if last_error:
            print(f"Overpass unavailable; trying Nominatim fallback: {last_error}")
        else:
            print("Overpass returned no matches; trying Nominatim fallback.")

        try:
            fallback_query = f"{keyword or 'tourist attraction'} in {destination}"
            nominatim_response = nominatim_get("search", {
                "q": fallback_query,
                "format": "jsonv2",
                "addressdetails": 1,
                "limit": 10,
            })
            fallback_results = nominatim_response.json()

            for result in fallback_results:
                osm_type = clean_text(result.get("osm_type")).lower()
                osm_id = result.get("osm_id")
                lat = result.get("lat")
                lon = result.get("lon")
                name = clean_text(result.get("name"))
                if not name:
                    name = clean_text(result.get("display_name", "")).split(",")[0]
                if not (osm_type and osm_id and lat and lon and name):
                    continue

                address_data = result.get("address") or {}
                tags = {
                    "name": name,
                    "addr:city": address_data.get("city") or address_data.get("town") or address_data.get("village", ""),
                    "addr:state": address_data.get("state", ""),
                    "addr:country": address_data.get("country", ""),
                    "tourism": result.get("type") or result.get("class") or "attraction",
                }
                elements.append({
                    "type": osm_type,
                    "id": osm_id,
                    "lat": float(lat),
                    "lon": float(lon),
                    "tags": tags,
                })

            print(f"Nominatim fallback returned {len(elements)} places for {destination!r} / {keyword!r}")
        except (requests.RequestException, ValueError, TypeError) as error:
            print(f"Nominatim fallback failed: {error}")
            return []

        if not elements:
            print("No places found from Overpass or Nominatim fallback.")
            return []

    generic_names = {
        "park", "restaurant", "cafe", "shop", "mall", "playground",
        "attraction", "tourist attraction", "market",
    }
    places = []
    seen_ids = set()
    seen_names = set()
    seen_coords = set()
    seen_images = set()

    for element in elements:
        tags = element.get("tags") or {}
        name = clean_text(tags.get("name"))
        if not name or name.casefold() in generic_names:
            continue

        osm_type = clean_text(element.get("type"))
        osm_id = element.get("id")
        if not osm_type or not osm_id:
            continue
        place_id = f"{osm_type}:{osm_id}"
        if place_id in seen_ids:
            continue

        center = element.get("center") or element
        lat = center.get("lat")
        lon = center.get("lon")
        if lat is None or lon is None:
            continue

        try:
            coord_key = (round(float(lat), 4), round(float(lon), 4))
        except (TypeError, ValueError):
            continue
        normalized_name = re.sub(r"[^a-z0-9]+", " ", name.casefold()).strip()
        name_key = normalized_name
        if name_key in seen_names or coord_key in seen_coords:
            continue

        # For Thanjavur searches, avoid accidentally mixing in results from
        # similarly named places outside Tamil Nadu.
        if (destination or "").strip().casefold() in {"thanjavur", "tanjore"}:
            place_state = clean_text(tags.get("addr:state")).casefold()
            place_country = clean_text(tags.get("addr:country")).casefold()
            if place_state and place_state not in {"tamil nadu", "tn"}:
                continue
            if place_country and place_country not in {"india", "in"}:
                continue

        category = next(
            (f"{key}={value}" for key, value in tags.items()
             if key in {"tourism", "historic", "amenity", "leisure", "natural", "shop"}),
            "OpenStreetMap place",
        )
        address_parts = [
            clean_text(tags.get("addr:street")),
            clean_text(tags.get("addr:city") or tags.get("addr:town")),
            clean_text(tags.get("addr:state")),
            clean_text(tags.get("addr:country")),
        ]
        address = ", ".join(part for part in address_parts if part) or destination

        media_image = clean_text(tags.get("image"))
        image_source = ""
        if not media_image:
            image_data = get_place_image(name, destination, keyword, seen_images)
            media_image = image_data.get("image", "")
            image_source = image_data.get("source", "")

        if media_image in seen_images:
            image_data = get_place_image(
                name + str(osm_id), destination, keyword, seen_images
            )
            media_image = image_data.get("image", "")
            image_source = image_data.get("source", "")

        seen_ids.add(place_id)
        seen_names.add(name_key)
        seen_coords.add(coord_key)
        if media_image:
            seen_images.add(media_image)

        places.append({
            "name": name,
            "address": address,
            "city": clean_text(tags.get("addr:city") or tags.get("addr:town")) or destination,
            "state": clean_text(tags.get("addr:state")),
            "country": clean_text(tags.get("addr:country")),
            "latitude": lat,
            "longitude": lon,
            "place_id": place_id,
            "category": category,
            "image": media_image,
            "image_source": image_source,
        })
        if len(places) >= 10:
            break

    print(
        f"OpenStreetMap search for destination={destination!r}, "
        f"interest={keyword!r}: {len(places)} places found"
    )
    return places


# NEXT PART STARTS WITH FLASK ROUTES

# HOME

@app.route("/")
def home():
    return render_template("index.html")


# ABOUT PAGE

@app.route("/about")
def about():
    return render_template("about.html")


# ==================================================
# FEEDBACK PAGE - ALL VISITORS CAN READ PUBLIC FEEDBACK
# ==================================================

@app.route("/feedback", methods=["GET", "POST"])
def feedback():
    error = None
    success = request.args.get("success", "")

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        message = request.form.get("message", "").strip()

        try:
            rating = int(request.form.get("rating", "0"))
        except (TypeError, ValueError):
            rating = 0

        if not name or not email or not message:
            error = "Please fill in all fields."
        elif len(name) > 80 or len(email) > 254 or len(message) > 2000:
            error = "Please keep your name, email and feedback within the allowed length."
        elif not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            error = "Please enter a valid email address."
        elif rating < 1 or rating > 5:
            error = "Please select a rating from 1 to 5."
        else:
            conn = get_db()
            try:
                conn.execute(
                    """
                    INSERT INTO feedback (name, email, rating, message)
                    VALUES (?, ?, ?, ?)
                    """,
                    (name, email, rating, message)
                )
                conn.commit()
            finally:
                conn.close()

            return redirect(url_for("feedback", success="Your feedback was submitted successfully."))

    conn = get_db()
    try:
        # Email is deliberately not sent to the template or shown publicly.
        feedbacks = conn.execute(
            """
            SELECT id, name, rating, message, created_at
            FROM feedback
            ORDER BY id DESC
            """
        ).fetchall()
    finally:
        conn.close()

    return render_template(
        "feedback.html",
        feedbacks=feedbacks,
        error=error,
        success=success
    )


# DESTINATIONS PAGE

@app.route("/destinations")
def destinations():
    return render_template("destinations.html")


# DESTINATION SEARCH API

@app.route("/search-destination", methods=["GET"])
def search_destination():
    place = request.args.get("q", "").strip()
    if not place:
        return jsonify({"results": [], "error": "Please enter a destination."}), 400

    try:
        results_data = geocode_destination(place, limit=5)
        results = []
        for item in results_data:
            result_type = clean_text(item.get("result_type")).casefold()
            country_name = clean_text(item.get("country")) or "Not available"
            city_name = get_city(item)
            state_name = get_state(item)
            if result_type == "country":
                city_name = clean_text(item.get("name")) or country_name
                state_name = "Not applicable"

            results.append({
                "name": clean_text(item.get("name")) or city_name or country_name or place,
                "address": clean_text(item.get("formatted")) or place,
                "city": city_name or "Not available",
                "state": state_name or "Not available",
                "country": country_name,
                "lat": item.get("lat"),
                "lon": item.get("lon"),
                "result_type": result_type,
            })
        return jsonify({"results": results})

    except requests.RequestException as error:
        print("Nominatim destination search error:", error)
        return jsonify({
            "results": [],
            "error": "Unable to connect to OpenStreetMap destination search. Please try again later.",
        }), 502


# PLACE DETAILS

@app.route("/place/<path:place_id>")
def place_details(place_id):
    destination_name = request.args.get("destination", "")
    selected_image = request.args.get("image", "")
    image_source = request.args.get("image_source", "")

    try:
        # Place IDs are stored as "node:123", "way:123", or "relation:123".
        try:
            osm_type, osm_id = place_id.split(":", 1)
            osm_prefix = {"node": "N", "way": "W", "relation": "R"}[osm_type]
            if not osm_id.isdigit():
                raise ValueError("Invalid OpenStreetMap place ID")
        except (ValueError, KeyError):
            return render_template(
                "place_details.html",
                error="Invalid place identifier.",
                packages=[],
            )

        response = nominatim_get("lookup", {
            "osm_ids": f"{osm_prefix}{osm_id}",
            "format": "jsonv2",
            "addressdetails": 1,
            "namedetails": 1,
        })
        records = response.json()
        if not records:
            return render_template(
                "place_details.html",
                error="Place details not found in OpenStreetMap.",
                packages=[],
            )

        item = records[0]
        tags_name = clean_text((item.get("namedetails") or {}).get("name"))
        name = tags_name or clean_text(item.get("name")) or "Unknown Place"
        address = clean_text(item.get("display_name")) or destination_name or "Not available"
        city, state, country = _address_parts(item)
        category = clean_text(item.get("type") or item.get("class")) or "Tourist Place"

        image = selected_image
        if not image:
            image_data = get_place_image(name, destination_name, "scenic landscape")
            image = image_data["image"]
            image_source = image_source or image_data["source"]

        place_data = {
            "place_id": place_id,
            "name": name,
            "address": address,
            "city": city or "Not available",
            "state": state or "Not available",
            "country": country or "Not available",
            "latitude": item.get("lat"),
            "longitude": item.get("lon"),
            "category": category,
            "image": image,
            "image_source": image_source,
            "destination": destination_name or city,
        }

        conn = get_db()
        try:
            packages = conn.execute("""
                SELECT id, package_name, destination
                FROM packages
                ORDER BY created_at DESC, id DESC
            """).fetchall()
        finally:
            conn.close()

        return render_template(
            "place_details.html",
            place=place_data,
            packages=packages,
        )

    except (requests.RequestException, ValueError) as error:
        print("OpenStreetMap place details error:", error)
        return render_template(
            "place_details.html",
            error="Unable to load place details. Please try again later.",
            packages=[],
        )


# CREATE A NEW PACKAGE

@app.route("/create-package", methods=["POST"])
def create_package():
    destination = request.form.get(
        "destination", ""
    ).strip()

    package_name = request.form.get(
        "package_name", ""
    ).strip()

    travel_date = request.form.get("travel_date", "").strip()
    travel_type = request.form.get("travel_type", "").strip()

    try:
        days = max(1, int(request.form.get("days", 1)))
    except (TypeError, ValueError):
        days = 1

    try:
        budget = max(
            0, float(request.form.get("budget", 0) or 0)
        )
    except (TypeError, ValueError):
        budget = 0

    if not destination:
        return redirect(url_for(
            "my_packages",
            message="Enter a destination first."
        ))

    if not package_name:
        package_name = destination + " Trip"

    conn = get_db()

    cursor = conn.execute("""
        INSERT INTO packages (
            package_name, destination, travel_date,
            days, travel_type, budget
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        package_name, destination, travel_date,
        days, travel_type, budget
    ))

    package_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return redirect(url_for(
        "my_packages",
        message="Package created successfully.",
        selected=package_id
    ))


# NEXT PART: ADD PLACES, MY PACKAGES & PLAN TRIP

# ==================================================
# ADD PLACE TO PACKAGE
# ==================================================

@app.route("/add-to-package", methods=["POST"])
def add_to_package():
    place_id = request.form.get("place_id", "").strip()
    place_name = request.form.get("place_name", "").strip()
    address = request.form.get("address", "").strip()
    image = request.form.get("image", "").strip()
    category = request.form.get("category", "").strip()

    latitude = request.form.get("latitude", "").strip()
    longitude = request.form.get("longitude", "").strip()

    package_id_input = request.form.get("package_id", "").strip()
    destination = (
        request.form.get("new_destination", "").strip()
        or request.form.get("destination", "").strip()
        or address
        or place_name
    )
    package_name = (
        request.form.get("new_package_name", "").strip()
        or f"{destination} Trip"
    )

    try:
        days = max(1, int(request.form.get("days", 1)))
    except (ValueError, TypeError):
        days = 1

    try:
        budget = max(0, float(request.form.get("budget", 0) or 0))
    except (ValueError, TypeError):
        budget = 0

    travel_date = request.form.get("travel_date", "").strip()
    travel_type = request.form.get("travel_type", "Solo").strip()

    if not place_name:
        return redirect(url_for("my_packages", message="Place name is missing."))

    try:
        latitude = float(latitude) if latitude else None
    except ValueError:
        latitude = None

    try:
        longitude = float(longitude) if longitude else None
    except ValueError:
        longitude = None

    conn = get_db()

    try:
        package_id = None

        if package_id_input.isdigit():
            existing = conn.execute(
                "SELECT id FROM packages WHERE id = ?",
                (int(package_id_input),)
            ).fetchone()

            if existing:
                package_id = existing["id"]

        if package_id is None:
            cursor = conn.execute(
                """
                INSERT INTO packages
                (destination, package_name, travel_date, days,
                 travel_type, budget)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    destination,
                    package_name,
                    travel_date,
                    days,
                    travel_type,
                    budget
                )
            )
            package_id = cursor.lastrowid

        conn.execute(
            """
            INSERT OR IGNORE INTO package_places
            (package_id, place_id, place_name, address, image,
             latitude, longitude, category)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                package_id,
                place_id or place_name,
                place_name,
                address,
                image,
                latitude,
                longitude,
                category
            )
        )

        conn.commit()

    except sqlite3.Error as error:
        conn.rollback()
        print("Database error:", error)
        return redirect(
            url_for("my_packages", message="Could not save this place.")
        )

    finally:
        conn.close()

    return redirect(url_for("package_details", package_id=package_id))


# ==================================================
# MY PACKAGES
# ==================================================

@app.route("/my-packages")
def my_packages():
    message = request.args.get("message", "")
    selected_package = request.args.get("selected_package", "")

    conn = get_db()

    try:
        packages = conn.execute(
            """
            SELECT p.*,
                   COUNT(pp.id) AS place_count
            FROM packages p
            LEFT JOIN package_places pp
                ON p.id = pp.package_id
            GROUP BY p.id
            ORDER BY p.id DESC
            """
        ).fetchall()

    finally:
        conn.close()

    return render_template(
        "my_packages.html",
        packages=packages,
        message=message,
        selected_package=selected_package
    )


# ==================================================
# PACKAGE DETAILS
# ==================================================

@app.route("/package/<int:package_id>")
def package_details(package_id):
    conn = get_db()

    try:
        package = conn.execute(
            "SELECT * FROM packages WHERE id = ?",
            (package_id,)
        ).fetchone()

        if package is None:
            return redirect(
                url_for("my_packages", message="Package not found.")
            )

        places = conn.execute(
            """
            SELECT *
            FROM package_places
            WHERE package_id = ?
            ORDER BY id DESC
            """,
            (package_id,)
        ).fetchall()

    finally:
        conn.close()

    return render_template(
        "packages_details.html",
        package=package,
        places=places
    )


# ==================================================
# PACKAGE BOOKING
# ==================================================

@app.route("/book/<int:package_id>", methods=["GET", "POST"])
def book_package(package_id):
    conn = get_db()

    try:
        package = conn.execute(
            "SELECT * FROM packages WHERE id = ?",
            (package_id,)
        ).fetchone()

        if package is None:
            return redirect(
                url_for("my_packages", message="Package not found.")
            )

        if request.method == "POST":
            traveller_name = request.form.get("traveller_name", "").strip()
            email = request.form.get("email", "").strip()
            phone = request.form.get("phone", "").strip()

            try:
                travellers = int(request.form.get("travellers", "1"))
            except (ValueError, TypeError):
                travellers = 0

            try:
                price_per_person = float(package["budget"] or 0)
            except (ValueError, TypeError):
                price_per_person = 0.0

            if (
                not traveller_name
                or not email
                or not phone
                or travellers < 1
            ):
                return render_template(
                    "booking.html",
                    package=package,
                    error="Please fill all fields and enter at least 1 traveller."
                )

            total_amount = price_per_person * travellers

            cursor = conn.execute(
                """
                INSERT INTO bookings (
                    package_id, traveller_name, email, phone, travellers,
                    price_per_person, total_amount
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    package_id,
                    traveller_name,
                    email,
                    phone,
                    travellers,
                    price_per_person,
                    total_amount
                )
            )
            booking_id = cursor.lastrowid
            conn.commit()

            return redirect(
                url_for("booking_confirmation", booking_id=booking_id)
            )

    finally:
        conn.close()

    return render_template("booking.html", package=package, error=None)


@app.route("/booking-confirmation/<int:booking_id>")
def booking_confirmation(booking_id):
    conn = get_db()

    try:
        booking = conn.execute(
            """
            SELECT bookings.*, packages.package_name, packages.destination
            FROM bookings
            JOIN packages ON bookings.package_id = packages.id
            WHERE bookings.id = ?
            """,
            (booking_id,)
        ).fetchone()
    finally:
        conn.close()

    if booking is None:
        return "Booking not found.", 404

    return render_template(
        "booking_confirmation.html",
        booking=booking
    )


# ==================================================
# REMOVE PLACE FROM PACKAGE
# ==================================================

@app.route(
    "/remove-from-package/<int:place_row_id>",
    methods=["POST"]
)
def remove_from_package(place_row_id):
    conn = get_db()

    try:
        place = conn.execute(
            """
            SELECT package_id
            FROM package_places
            WHERE id = ?
            """,
            (place_row_id,)
        ).fetchone()

        if place is None:
            return redirect(
                url_for("my_packages", message="Place not found.")
            )

        package_id = place["package_id"]

        conn.execute(
            "DELETE FROM package_places WHERE id = ?",
            (place_row_id,)
        )

        conn.commit()

    finally:
        conn.close()

    return redirect(
        url_for("package_details", package_id=package_id)
    )


# ==================================================
# DELETE COMPLETE PACKAGE
# ==================================================

@app.route(
    "/delete-package/<int:package_id>",
    methods=["POST"]
)
def delete_package(package_id):
    conn = get_db()

    try:
        conn.execute(
            "DELETE FROM package_places WHERE package_id = ?",
            (package_id,)
        )

        conn.execute(
            "DELETE FROM packages WHERE id = ?",
            (package_id,)
        )

        conn.commit()

    finally:
        conn.close()

    return redirect(
        url_for("my_packages", message="Package deleted.")
    )


# ==================================================
# PLAN TRIP
# ==================================================

@app.route("/plan-trip", methods=["GET", "POST"])
def plan_trip():
    if request.method == "GET":
        return render_template("plan_trip.html")

    destination = request.form.get("destination", "").strip()
    travel_date = request.form.get("travel_date", "").strip()
    travel_type = request.form.get("travel_type", "Solo").strip()

    try:
        days = max(1, int(request.form.get("days", 1)))
    except (ValueError, TypeError):
        days = 1

    try:
        budget = max(0, float(request.form.get("budget", 0) or 0))
    except (ValueError, TypeError):
        budget = 0

    interests = request.form.getlist("interests")
    recommendations = []
    interest_results = {}

    if not destination:
        return render_template(
            "plan_trip.html",
            error="Please enter a destination.",
            destination=destination,
            destination_name=destination,
            recommendations=recommendations,
            interest_results=interest_results,
            selected_interests=interests,
            travel_date=travel_date, days=days,
            travel_type=travel_type, budget=budget
        )

    destination_data = None
    try:
        geo_results = geocode_destination(destination)
        if not geo_results:
            return render_template(
                "plan_trip.html",
                error=f"Destination '{destination}' was not found. Try a city name such as Goa or Chennai.",
                destination=destination,
                destination_name=destination,
                recommendations=recommendations,
                interest_results=interest_results,
                selected_interests=interests,
                travel_date=travel_date, days=days,
                travel_type=travel_type, budget=budget
            )

        best_result = select_best_result(geo_results, destination)
        if not best_result:
            return render_template(
                "plan_trip.html",
                error="Could not identify this destination. Please try another name.",
                destination=destination,
                destination_name=destination,
                recommendations=recommendations,
                interest_results=interest_results,
                selected_interests=interests,
                travel_date=travel_date, days=days,
                travel_type=travel_type, budget=budget
            )

        destination_data = make_destination_data(best_result, destination)

        latitude = destination_data.get("latitude")
        longitude = destination_data.get("longitude")
        if latitude is None or longitude is None:
            raise ValueError("The destination search did not return coordinates. Try a city or town name.")

        for interest in interests:
            config = INTEREST_CONFIG.get(interest)
            if not config:
                continue

            try:
                places = search_places(
                    latitude,
                    longitude,
                    config["categories"],
                    destination,
                    config["keyword"]
                )

                for place in places:
                    place["interest"] = interest
                    place["interest_title"] = config["title"]

                # Keep the results available by interest key.
                interest_results[interest] = places

                # plan_trip.html expects each recommendation to contain
                # a section title and a list of places.
                recommendations.append({
                    "title": config["title"],
                    "places": places
                })

            except (requests.RequestException, ValueError) as error:
                print(f"Search error for {interest}: {error}")
                interest_results[interest] = []
                recommendations.append({
                    "title": config["title"],
                    "places": []
                })

        if interests and not any(section.get("places") for section in recommendations):
            print("No places returned. Check OpenStreetMap service availability and selected interests.")

        return render_template(
            "plan_trip.html",
            destination=destination_data,
            destination_data=destination_data,
            destination_info=destination_data,
            destination_name=(destination_data.get("name", destination) if destination_data else destination),
            recommendations=recommendations,
            interest_results=interest_results,
            selected_interests=interests,
            travel_date=travel_date,
            days=days,
            travel_type=travel_type,
            budget=budget,
            error=("No places were returned for the selected interests. Try another interest or destination." if interests and not any(section.get("places") for section in recommendations) else None)
        )

    except requests.RequestException as error:
        print("OpenStreetMap connection error:", error)
        return render_template(
            "plan_trip.html",
            error="Could not connect to OpenStreetMap services. Check your internet connection and try again.",
            destination=destination,
            destination_data=destination_data,
            destination_info=destination_data,
            destination_name=(destination_data.get("name", destination) if destination_data else destination),
            recommendations=recommendations,
            interest_results=interest_results,
            selected_interests=interests,
            travel_date=travel_date, days=days,
            travel_type=travel_type, budget=budget
        )
    except (ValueError, KeyError, TypeError) as error:
        print("Trip planning error:", error)
        return render_template(
            "plan_trip.html",
            error=str(error),
            destination=destination,
            destination_data=destination_data,
            destination_info=destination_data,
            destination_name=(destination_data.get("name", destination) if destination_data else destination),
            recommendations=recommendations,
            interest_results=interest_results,
            selected_interests=interests,
            travel_date=travel_date, days=days,
            travel_type=travel_type, budget=budget
        )


# ==================================================
# RUN APPLICATION
# ==================================================

if __name__ == "__main__":
    app.run(debug=True)
