import tkinter as tk
import math
import requests
import threading
import time
import csv
import io


# ============================================================
# AIRSPACE RADAR — SOFTWARE COMPLETE
# Flight Intelligence + Track History + Metadata + Clean MAP + Operations
# ============================================================

# ============================================================
# 1. CONFIGURATION
# ============================================================

# USER-DEFINED RADAR ORIGIN
# Change HOME_LAT and HOME_LON to place the radar anywhere you want.
# The radar center is NOT tied to Bengaluru.
HOME_LAT = 13.1986
HOME_LON = 77.7066

HOME_NAME = "RADAR ORIGIN"
HOME_IATA = "HOME"
HOME_ICAO = "HOME"

RADAR_RANGE_KM = 50

# ============================================================
# PHASE 5.5 — MAP WEATHER / AIR QUALITY / TURBULENCE
# ============================================================

WEATHER_ENABLED = True

AIR_QUALITY_UPDATE_INTERVAL = 600
WEATHER_UPDATE_INTERVAL = 900

WEATHER_GRID_SPACING_KM = 10
WEATHER_MAX_POINTS = 121

OPEN_METEO_AIR_QUALITY_URL = (
    "https://air-quality-api.open-meteo.com/v1/air-quality"
)

OPEN_METEO_WEATHER_URL = (
    "https://api.open-meteo.com/v1/forecast"
)

# Turbulence is shown as MODEL-DERIVED POTENTIAL, not measured
# turbulence. It is inferred from vertical wind-speed shear.
TURBULENCE_ENABLED = True


AIRCRAFT_UPDATE_INTERVAL = 30
AIRPORT_REFRESH_INTERVAL = 3600
ANIMATION_INTERVAL = 40

# Entry/exit visual animation
ENTRY_ANIMATION_MS = 900
EXIT_RETENTION_SECONDS = 4

# Try ADSB.lol first. OpenSky remains an optional fallback.
ADSBLOL_URL = "https://api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/{dist}"
STATES_URL = "https://opensky-network.org/api/states/all"
USE_OPENSKY_FALLBACK = False

AIRPORTS_URL = (
    "https://davidmegginson.github.io/"
    "ourairports-data/airports.csv"
)

RUNWAYS_URL = (
    "https://davidmegginson.github.io/"
    "ourairports-data/runways.csv"
)

METADATA_UPDATE_INTERVAL = 90
METADATA_URL = (
    "https://opensky-network.org/api/"
    "metadata/aircraft/icao24/"
)

http = requests.Session()
http.headers.update(
    {
        "User-Agent":
            "AirspaceRadar/2.0 (personal desktop radar display)"
    }
)


# ============================================================
# 2. WINDOW
# ============================================================

WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 800

RADAR_WIDTH = 930
SIDE_WIDTH = 350


# ============================================================
# 3. THEME
# ============================================================

# Permanent professional radar theme. DAY/NIGHT switching is removed.
THEME = {
    "BG": "#080b0d",
    "PANEL": "#101518",
    "PANEL_2": "#141c20",
    "TEXT": "#e7f1f3",
    "TEXT_DIM": "#829398",
    "GREEN": "#39ff88",
    "GREEN_DIM": "#0b6b3c",
    "GRID": "#163b2a",
    "YELLOW": "#ffd84d",
    "RED": "#ff4d5a",
    "BLUE": "#44aaff",
    "BLUE_DIM": "#236080",
    "MAP_GRID": "#12282d",
    "MAP_LAND": "#0b1114",
    "RUNWAY": "#347e99",
    "SCOPE_BG": "#080b0d",
}

BG = THEME["BG"]
PANEL = THEME["PANEL"]
PANEL_2 = THEME["PANEL_2"]
TEXT = THEME["TEXT"]
TEXT_DIM = THEME["TEXT_DIM"]
GREEN = THEME["GREEN"]
GREEN_DIM = THEME["GREEN_DIM"]
GRID = THEME["GRID"]
YELLOW = THEME["YELLOW"]
RED = THEME["RED"]
BLUE = THEME["BLUE"]
BLUE_DIM = THEME["BLUE_DIM"]
MAP_GRID = THEME["MAP_GRID"]
MAP_LAND = THEME["MAP_LAND"]
RUNWAY = THEME["RUNWAY"]
SCOPE_BG = THEME["SCOPE_BG"]


# ============================================================
# 4. GLOBAL DATA
# ============================================================

aircraft_data = {}
aircraft_metadata = {}
airport_data = []
runway_data = []

# ============================================================
# PHASE 5.5 — WEATHER STATE
# ============================================================

weather_cells = []
weather_updated_time = 0.0
weather_range_km = 0.0

weather_home_air_quality = {
    "aqi": None,
    "pm2_5": None,
    "pm10": None,
}

weather_max_turbulence = {
    "level": "UNKNOWN",
    "score": 0.0,
    "latitude": None,
    "longitude": None,
}

weather_max_air_quality = {
    "aqi": None,
    "latitude": None,
    "longitude": None,
}

weather_lock = threading.Lock()

# ============================================================
# PHASE 5 — FLIGHT INTELLIGENCE STATE
# ============================================================

aircraft_history = {}

HISTORY_MAX_POINTS = 20

# ============================================================
# PHASE 5.6 / 5.7 — SOFTWARE COMPLETION
# ============================================================

TRACK_DISPLAY_MODE = "SELECTED"   # OFF / SELECTED / ALL
BEHAVIOR_FILTER = "ALL"            # ALL / ARRIVAL / DEPARTURE / OVERFLIGHT / HOLDING
SIZE_FILTER = "ALL"                # ALL / small / medium / large / very_large
ALERTS_ENABLED = True
AIRCRAFT_WEATHER_ENABLED = True


# ============================================================
# PHASE 5.4 — ARRIVAL / DEPARTURE INTELLIGENCE
# ============================================================

def heading_matches(aircraft_heading, target_heading, tolerance=35.0):
    if aircraft_heading is None or target_heading is None:
        return False

    difference = abs(aircraft_heading - target_heading)
    if difference > 180:
        difference = 360 - difference

    return difference <= tolerance


def find_nearest_airport(latitude, longitude):
    if latitude is None or longitude is None:
        return None, None

    with airport_lock:
        airports = list(airport_data)

    nearest = None
    nearest_distance = float("inf")

    for airport in airports:
        airport_lat = airport.get("latitude")
        airport_lon = airport.get("longitude")

        if airport_lat is None or airport_lon is None:
            continue

        distance = calculate_distance(
            latitude,
            longitude,
            airport_lat,
            airport_lon,
        )

        if distance < nearest_distance:
            nearest = airport
            nearest_distance = distance

    return nearest, nearest_distance if nearest is not None else None


def aircraft_aligned_with_runway(plane, airport):
    heading = plane.get("heading")
    if heading is None or airport is None:
        return False, None

    runways = airport_runways_for_ident(
        airport["ident"]
    )

    best_runway = None
    best_difference = float("inf")

    for runway in runways:
        runway_heading = runway_bearing(runway)
        reverse_heading = (runway_heading + 180) % 360

        difference = min(
            calculate_heading_change(
                heading, runway_heading
            ),
            calculate_heading_change(
                heading, reverse_heading
            ),
        )

        if difference < best_difference:
            best_difference = difference
            best_runway = runway

    if (
        best_runway is None
        or best_difference > RUNWAY_ALIGNMENT_TOLERANCE
    ):
        return False, None

    return True, best_runway


def classify_airport_behavior(plane):
    latitude = plane.get("latitude")
    longitude = plane.get("longitude")

    nearest_airport, airport_distance = find_nearest_airport(
        latitude,
        longitude,
    )

    if nearest_airport is None or airport_distance is None:
        return "UNKNOWN", None, None, None

    altitude = plane.get("altitude")
    speed = plane.get("speed")
    heading = plane.get("heading")

    altitude_ft = (
        altitude * 3.28084
        if altitude is not None
        else None
    )

    speed_kt = (
        speed * 1.94384
        if speed is not None
        else None
    )

    toward_airport = calculate_bearing(
        latitude,
        longitude,
        nearest_airport["latitude"],
        nearest_airport["longitude"],
    )

    heading_toward = heading_matches(
        heading,
        toward_airport,
        APPROACH_HEADING_TOLERANCE,
    )

    aligned, runway = aircraft_aligned_with_runway(
        plane,
        nearest_airport,
    )

    flight_status = plane.get(
        "flight_status",
        "TRACKING",
    )

    if (
        airport_distance <= AIRPORT_PROXIMITY_KM
        and flight_status in {"APPROACHING", "DESCENDING"}
        and heading_toward
        and (
            altitude_ft is None
            or altitude_ft <= ARRIVAL_MAX_ALTITUDE_FT
        )
    ):
        return (
            "ARRIVAL / APPROACH",
            nearest_airport,
            runway if aligned else None,
            airport_distance,
        )

    if (
        airport_distance <= AIRPORT_PROXIMITY_KM
        and flight_status in {"CLIMBING", "MOVING AWAY"}
        and (
            altitude_ft is None
            or altitude_ft >= DEPARTURE_MIN_ALTITUDE_FT
        )
        and (
            speed_kt is None
            or speed_kt >= DEPARTURE_MIN_SPEED_KT
        )
    ):
        return (
            "DEPARTURE",
            nearest_airport,
            runway if aligned else None,
            airport_distance,
        )

    if (
        airport_distance > AIRPORT_PROXIMITY_KM
        and (
            speed_kt is None
            or speed_kt >= OVERFLIGHT_MIN_SPEED_KT
        )
        and flight_status in {"MOVING AWAY", "CRUISING / LEVEL"}
    ):
        return (
            "OVERFLIGHT",
            nearest_airport,
            None,
            airport_distance,
        )

    return (
        "AIRSPACE TRANSIT",
        nearest_airport,
        None,
        airport_distance,
    )


# ============================================================
# PHASE 5.2 — VISUAL TRACK HISTORY
# ============================================================

TRACK_HISTORY_ENABLED = True
TRACK_ONLY_SELECTED = True
TRACK_DRAW_POINTS = 12
TRACK_MAX_SCREEN_JUMP = 120

# ============================================================
# PHASE 5.4 — ARRIVAL / DEPARTURE INTELLIGENCE
# ============================================================

AIRPORT_PROXIMITY_KM = 12.0
APPROACH_HEADING_TOLERANCE = 35.0
RUNWAY_ALIGNMENT_TOLERANCE = 25.0
ARRIVAL_MAX_ALTITUDE_FT = 12000
DEPARTURE_MIN_ALTITUDE_FT = 1500
DEPARTURE_MIN_SPEED_KT = 100
OVERFLIGHT_MIN_SPEED_KT = 120

# These thresholds are intentionally conservative because the
# ADS-B feed updates periodically rather than continuously.
APPROACHING_DISTANCE_CHANGE_KM = 0.25
VERTICAL_RATE_THRESHOLD_FPM = 300
HOLDING_TURN_THRESHOLD = 35
HOLDING_MAX_DISTANCE_SPAN_KM = 8


selected_aircraft = None
selected_airport = None
selected_runway = None

hovered_aircraft = None
hovered_airport = None
hovered_runway = None

# Aircraft that just entered/left the radar screen
entry_animation = {}
recently_removed = {}

data_lock = threading.Lock()
metadata_lock = threading.Lock()
airport_lock = threading.Lock()

api_status = "CONNECTING..."
connection_ok = False
retry_after_seconds = 0

VIEW_MODE = "RADAR"
sweep_angle = 0

last_update_time = 0.0
last_airport_update = 0.0


# ============================================================
# 5. AIRCRAFT SIZE CLASSIFICATION
# ============================================================

VERY_LARGE = {
    "A380", "A388", "B748", "B747"
}

LARGE = {
    "A350", "A359", "A35K",
    "B777", "B77W", "B77L",
    "B787", "B789", "B788",
    "A330", "A332", "A333", "A339",
    "A340", "A343", "A346"
}

MEDIUM = {
    "A318", "A319", "A320", "A321",
    "B737", "B738", "B739",
    "B38M", "B39M",
    "E190", "E195"
}

SMALL = {
    "AT43", "AT45", "AT46",
    "DH8A", "DH8B", "DH8C", "DH8D",
    "CRJ1", "CRJ2", "CRJ7", "CRJ9",
    "ERJ1", "ERJ2",
    "C172", "C208"
}


def get_aircraft_size(typecode):
    if not typecode:
        return "medium"

    typecode = typecode.upper().strip()

    if typecode in VERY_LARGE:
        return "very_large"

    if typecode in LARGE:
        return "large"

    if typecode in MEDIUM:
        return "medium"

    if typecode in SMALL:
        return "small"

    if typecode.startswith(("A38", "B74")):
        return "very_large"

    if typecode.startswith(("A35", "B77", "B78", "A33", "A34")):
        return "large"

    if typecode.startswith(("A32", "B73", "E19")):
        return "medium"

    if typecode.startswith(("CRJ", "DH8")):
        return "small"

    return "medium"


def get_marker_scale(icao):
    with metadata_lock:
        metadata = aircraft_metadata.get(icao, {})

    size = metadata.get("size", "medium")

    if size == "very_large":
        return 1.8
    if size == "large":
        return 1.45
    if size == "small":
        return 0.70

    return 1.0


# ============================================================
# PHASE 5.5 — WEATHER HELPERS
# ============================================================

def weather_grid_points():
    """Build a square grid around the user-defined radar origin."""

    radius = max(
        10,
        float(RADAR_RANGE_KM),
    )

    spacing = max(
        5,
        float(WEATHER_GRID_SPACING_KM),
    )

    points = []

    y = -radius

    while y <= radius:
        x = -radius

        while x <= radius:
            distance = math.hypot(x, y)

            if distance <= radius:
                latitude = HOME_LAT + y / 111.32

                longitude_scale = 111.32 * max(
                    0.15,
                    math.cos(
                        math.radians(HOME_LAT)
                    ),
                )

                longitude = (
                    HOME_LON
                    + x / longitude_scale
                )

                points.append(
                    {
                        "latitude": latitude,
                        "longitude": longitude,
                        "x_km": x,
                        "y_km": y,
                        "distance": distance,
                    }
                )

            x += spacing

        y += spacing

    return points[:WEATHER_MAX_POINTS]


def extract_multilocation_response(data, index):
    """Return one location response from Open-Meteo's list/dict output."""

    if isinstance(data, list):
        if 0 <= index < len(data):
            return data[index]
        return {}

    if isinstance(data, dict):
        # Single-location response.
        return data

    return {}


def aqi_severity(aqi):
    if aqi is None:
        return 0
    if aqi <= 50:
        return 0
    if aqi <= 100:
        return 1
    if aqi <= 150:
        return 2
    if aqi <= 200:
        return 3
    if aqi <= 300:
        return 4
    return 5


def aqi_color(aqi):
    """Dark map fill for air-quality intensity."""

    severity = aqi_severity(aqi)

    colors = {
        0: "#09291b",
        1: "#4a4712",
        2: "#57300f",
        3: "#542020",
        4: "#421529",
        5: "#24040b",
    }

    return colors.get(
        severity,
        "#11181b",
    )


def turbulence_level(score):
    if score is None:
        return "UNKNOWN"
    if score < 10:
        return "LOW"
    if score < 20:
        return "MODERATE"
    if score < 35:
        return "HIGH"
    return "SEVERE"


def turbulence_color(level):
    colors = {
        "LOW": "#1c9b57",
        "MODERATE": "#d0a316",
        "HIGH": "#e56f13",
        "SEVERE": "#a40012",
        "UNKNOWN": "#56646a",
    }
    return colors.get(
        level,
        "#56646a",
    )


def estimate_turbulence_potential(
    wind_850,
    wind_700,
    wind_500,
):
    """
    Estimate turbulence potential from vertical wind-speed shear.

    This is a model-derived visualization indicator only. It is not
    a direct observation of turbulence and should not be treated as
    an operational aviation turbulence product.
    """

    values = []

    for value in (
        wind_850,
        wind_700,
        wind_500,
    ):
        if isinstance(value, (int, float)):
            values.append(float(value))

    if len(values) < 2:
        return "UNKNOWN", 0.0

    shear = max(values) - min(values)

    return (
        turbulence_level(shear),
        shear,
    )


def fetch_air_quality_grid(points):
    if not points:
        return []

    latitudes = ",".join(
        f"{point['latitude']:.4f}"
        for point in points
    )

    longitudes = ",".join(
        f"{point['longitude']:.4f}"
        for point in points
    )

    params = {
        "latitude": latitudes,
        "longitude": longitudes,
        "current": "pm2_5,pm10,us_aqi",
        "timezone": "UTC",
    }

    try:
        response = http.get(
            OPEN_METEO_AIR_QUALITY_URL,
            params=params,
            timeout=20,
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        print(
            "Air-quality request failed:",
            exc,
        )
        return []


def fetch_weather_grid(points):
    if not points:
        return []

    latitudes = ",".join(
        f"{point['latitude']:.4f}"
        for point in points
    )

    longitudes = ",".join(
        f"{point['longitude']:.4f}"
        for point in points
    )

    params = {
        "latitude": latitudes,
        "longitude": longitudes,
        "hourly": (
            "wind_speed_850hPa,"
            "wind_speed_700hPa,"
            "wind_speed_500hPa,"
            "cloud_cover,"
            "precipitation,"
            "weather_code"
        ),
        "forecast_hours": 1,
        "timezone": "UTC",
    }

    try:
        response = http.get(
            OPEN_METEO_WEATHER_URL,
            params=params,
            timeout=25,
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        print(
            "Weather request failed:",
            exc,
        )
        return []


def refresh_weather_data():
    global weather_cells
    global weather_updated_time
    global weather_range_km
    global weather_home_air_quality
    global weather_max_turbulence
    global weather_max_air_quality

    if not WEATHER_ENABLED:
        return

    points = weather_grid_points()

    aq_data = fetch_air_quality_grid(points)
    wx_data = fetch_weather_grid(points)

    if not aq_data and not wx_data:
        return

    cells = []

    highest_turbulence = {
        "level": "UNKNOWN",
        "score": 0.0,
        "latitude": None,
        "longitude": None,
    }

    highest_aqi = {
        "aqi": None,
        "latitude": None,
        "longitude": None,
    }

    home_aq = {
        "aqi": None,
        "pm2_5": None,
        "pm10": None,
    }

    # Find the grid point closest to the configured origin.
    home_index = 0
    if points:
        home_index = min(
            range(len(points)),
            key=lambda i: points[i]["distance"],
        )

    for index, point in enumerate(points):
        aq_location = extract_multilocation_response(
            aq_data,
            index,
        )

        wx_location = extract_multilocation_response(
            wx_data,
            index,
        )

        current_aq = aq_location.get(
            "current",
            {},
        )

        hourly = wx_location.get(
            "hourly",
            {},
        )

        aqi = current_aq.get(
            "us_aqi"
        )

        pm25 = current_aq.get(
            "pm2_5"
        )

        pm10 = current_aq.get(
            "pm10"
        )

        def first_value(name):
            values = hourly.get(name, [])
            if values:
                return values[0]
            return None

        wind_850 = first_value(
            "wind_speed_850hPa"
        )

        wind_700 = first_value(
            "wind_speed_700hPa"
        )

        wind_500 = first_value(
            "wind_speed_500hPa"
        )

        cloud_cover = first_value(
            "cloud_cover"
        )

        precipitation = first_value(
            "precipitation"
        )

        weather_code = first_value(
            "weather_code"
        )

        turb_level, turb_score = (
            estimate_turbulence_potential(
                wind_850,
                wind_700,
                wind_500,
            )
        )

        if (
            isinstance(aqi, (int, float))
            and (
                highest_aqi["aqi"] is None
                or aqi > highest_aqi["aqi"]
            )
        ):
            highest_aqi = {
                "aqi": float(aqi),
                "latitude": point["latitude"],
                "longitude": point["longitude"],
            }

        if turb_score > highest_turbulence["score"]:
            highest_turbulence = {
                "level": turb_level,
                "score": float(turb_score),
                "latitude": point["latitude"],
                "longitude": point["longitude"],
            }

        if index == home_index:
            home_aq = {
                "aqi": aqi,
                "pm2_5": pm25,
                "pm10": pm10,
            }

        cells.append(
            {
                **point,
                "aqi": aqi,
                "pm2_5": pm25,
                "pm10": pm10,
                "turbulence_level": turb_level,
                "turbulence_score": turb_score,
                "cloud_cover": cloud_cover,
                "precipitation": precipitation,
                "weather_code": weather_code,
            }
        )

    with weather_lock:
        weather_cells = cells
        weather_updated_time = time.time()
        weather_range_km = float(RADAR_RANGE_KM)
        weather_home_air_quality = home_aq
        weather_max_turbulence = highest_turbulence
        weather_max_air_quality = highest_aqi


def weather_loop():
    while True:
        try:
            refresh_weather_data()
        except Exception as exc:
            print(
                "Weather loop error:",
                exc,
            )

        time.sleep(
            max(
                60,
                min(
                    AIR_QUALITY_UPDATE_INTERVAL,
                    WEATHER_UPDATE_INTERVAL,
                ),
            )
        )


# ============================================================
# PHASE 5.6 / 5.7 — AIRCRAFT WEATHER + OPERATIONS HELPERS
# ============================================================

def get_aircraft_weather(latitude, longitude):
    """Attach nearest available weather information to an aircraft."""
    result = {
        "aqi": None,
        "pm2_5": None,
        "pm10": None,
        "turbulence_level": "UNKNOWN",
        "turbulence_score": 0.0,
        "distance_km": None,
    }

    if not AIRCRAFT_WEATHER_ENABLED or latitude is None or longitude is None:
        return result

    with weather_lock:
        cells = list(weather_cells)

    if not cells:
        return result

    nearest = None
    nearest_distance = float("inf")

    for cell in cells:
        cell_lat = cell.get("latitude")
        cell_lon = cell.get("longitude")
        if cell_lat is None or cell_lon is None:
            continue

        distance = calculate_distance(
            latitude,
            longitude,
            cell_lat,
            cell_lon,
        )

        if distance < nearest_distance:
            nearest = cell
            nearest_distance = distance

    if nearest is None:
        return result

    result.update(
        {
            "aqi": nearest.get("aqi"),
            "pm2_5": nearest.get("pm2_5"),
            "pm10": nearest.get("pm10"),
            "turbulence_level": nearest.get("turbulence_level", "UNKNOWN"),
            "turbulence_score": nearest.get("turbulence_score", 0.0),
            "distance_km": nearest_distance,
        }
    )
    return result


def should_draw_track(icao):
    if TRACK_DISPLAY_MODE == "OFF":
        return False
    if TRACK_DISPLAY_MODE == "ALL":
        return True
    return icao == selected_aircraft or icao == hovered_aircraft


def aircraft_passes_operation_filters(plane):
    behavior_filter = BEHAVIOR_FILTER

    if behavior_filter != "ALL":
        behavior = plane.get("airport_behavior", "UNKNOWN")
        status = plane.get("flight_status", "")

        if behavior_filter == "ARRIVAL" and "ARRIVAL" not in behavior:
            return False
        if behavior_filter == "DEPARTURE" and behavior != "DEPARTURE":
            return False
        if behavior_filter == "OVERFLIGHT" and behavior != "OVERFLIGHT":
            return False
        if behavior_filter == "HOLDING" and "HOLDING" not in status:
            return False

    if SIZE_FILTER != "ALL":
        icao = plane.get("icao")
        with metadata_lock:
            metadata = aircraft_metadata.get(icao, {})
        if metadata.get("size", "medium") != SIZE_FILTER:
            return False

    return True


def aircraft_alert_status(plane):
    if not ALERTS_ENABLED:
        return ""

    weather = plane.get("weather", {})
    if weather.get("turbulence_level") == "SEVERE":
        return "WEATHER ALERT"

    behavior = plane.get("airport_behavior", "")
    if "ARRIVAL" in behavior:
        return "ARRIVAL ALERT"
    if behavior == "DEPARTURE":
        return "DEPARTURE ALERT"

    if "HOLDING" in plane.get("flight_status", ""):
        return "HOLDING ALERT"

    return ""


# ============================================================
# 6. GEO CALCULATIONS
# ============================================================

def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371.0

    lat1 = math.radians(lat1)
    lat2 = math.radians(lat2)

    dlat = lat2 - lat1
    dlon = math.radians(lon2 - lon1)

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(dlon / 2) ** 2
    )

    c = 2 * math.atan2(
        math.sqrt(a),
        math.sqrt(max(0.0, 1 - a))
    )

    return R * c


def calculate_bearing(lat1, lon1, lat2, lon2):
    lat1 = math.radians(lat1)
    lat2 = math.radians(lat2)

    dlon = math.radians(lon2 - lon1)

    x = math.sin(dlon) * math.cos(lat2)

    y = (
        math.cos(lat1)
        * math.sin(lat2)
        - math.sin(lat1)
        * math.cos(lat2)
        * math.cos(dlon)
    )

    bearing = math.degrees(math.atan2(x, y))

    return (bearing + 360) % 360


def cardinal_direction(degrees):
    directions = [
        "N", "NNE", "NE", "ENE",
        "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW",
        "W", "WNW", "NW", "NNW",
    ]
    index = int((degrees + 11.25) / 22.5) % 16
    return directions[index]


def format_hms(seconds):
    if seconds is None or seconds < 0:
        return "—"

    seconds = int(seconds)

    if seconds < 60:
        return f"{seconds:02d}s"

    minutes, sec = divmod(seconds, 60)

    if minutes < 60:
        return f"{minutes:02d}m {sec:02d}s"

    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}h {minutes:02d}m"


def update_aircraft_history(icao, plane):
    """Store a bounded sequence of recent observations."""
    point = {
        "time": time.time(),
        "latitude": plane.get("latitude"),
        "longitude": plane.get("longitude"),
        "distance": plane.get("distance"),
        "bearing": plane.get("bearing"),
        "heading": plane.get("heading"),
        "altitude": plane.get("altitude"),
        "speed": plane.get("speed"),
    }

    history = aircraft_history.setdefault(icao, [])
    history.append(point)

    if len(history) > HISTORY_MAX_POINTS:
        del history[:-HISTORY_MAX_POINTS]

    return history


def calculate_distance_trend(icao):
    history = aircraft_history.get(icao, [])

    if len(history) < 2:
        return "UNKNOWN", 0.0

    old = history[-2].get("distance")
    new = history[-1].get("distance")

    if old is None or new is None:
        return "UNKNOWN", 0.0

    # Positive means the aircraft is getting closer.
    change = old - new

    if change > APPROACHING_DISTANCE_CHANGE_KM:
        return "APPROACHING", change

    if change < -APPROACHING_DISTANCE_CHANGE_KM:
        return "MOVING AWAY", change

    return "STABLE", change


def calculate_vertical_trend(icao):
    history = aircraft_history.get(icao, [])

    if len(history) < 2:
        return "UNKNOWN"

    old = history[-2]
    new = history[-1]

    old_alt = old.get("altitude")
    new_alt = new.get("altitude")
    old_time = old.get("time")
    new_time = new.get("time")

    if None in (old_alt, new_alt, old_time, new_time):
        return "UNKNOWN"

    elapsed = new_time - old_time
    if elapsed <= 0:
        return "UNKNOWN"

    # Source altitude is metres; convert the change to feet/minute.
    altitude_change_ft = (new_alt - old_alt) * 3.28084
    vertical_rate_fpm = altitude_change_ft / (elapsed / 60.0)

    if vertical_rate_fpm > VERTICAL_RATE_THRESHOLD_FPM:
        return "CLIMBING"

    if vertical_rate_fpm < -VERTICAL_RATE_THRESHOLD_FPM:
        return "DESCENDING"

    return "LEVEL"


def calculate_heading_change(h1, h2):
    if h1 is None or h2 is None:
        return 0.0

    difference = abs(h2 - h1)
    if difference > 180:
        difference = 360 - difference

    return difference


def detect_holding(icao):
    """Best-effort detection of repeated turning near one area.

    This is a visual intelligence estimate, not an ATC holding
    clearance determination.
    """
    history = aircraft_history.get(icao, [])

    if len(history) < 5:
        return False

    recent = history[-6:]

    headings = [
        point.get("heading")
        for point in recent
        if point.get("heading") is not None
    ]

    if len(headings) < 4:
        return False

    total_turn = 0.0
    for i in range(1, len(headings)):
        total_turn += calculate_heading_change(
            headings[i - 1],
            headings[i],
        )

    distances = [
        point.get("distance")
        for point in recent
        if point.get("distance") is not None
    ]

    if len(distances) < 4:
        return False

    distance_span = max(distances) - min(distances)

    return (
        total_turn >= HOLDING_TURN_THRESHOLD * 3
        and distance_span <= HOLDING_MAX_DISTANCE_SPAN_KM
    )


def determine_flight_status(icao, plane):
    distance_status, _ = calculate_distance_trend(icao)
    vertical_status = calculate_vertical_trend(icao)

    if detect_holding(icao):
        return "HOLDING / CIRCLING"

    if distance_status == "APPROACHING":
        return "APPROACHING"

    if distance_status == "MOVING AWAY":
        return "MOVING AWAY"

    if vertical_status == "CLIMBING":
        return "CLIMBING"

    if vertical_status == "DESCENDING":
        return "DESCENDING"

    if vertical_status == "LEVEL":
        return "CRUISING / LEVEL"

    return "TRACKING"


# ============================================================
# 7. RADAR / MAP GEOMETRY
# ============================================================

CENTER_X = RADAR_WIDTH / 2
CENTER_Y = 349
RADAR_RADIUS = 310


def radar_position(distance, bearing):
    r = (
        min(distance, RADAR_RANGE_KM)
        / max(RADAR_RANGE_KM, 0.1)
    ) * RADAR_RADIUS

    angle = math.radians(bearing)

    x = CENTER_X + r * math.sin(angle)
    y = CENTER_Y - r * math.cos(angle)

    return x, y


def map_position(latitude, longitude):
    km_per_lat = 111.0

    km_per_lon = (
        111.0 * math.cos(math.radians(HOME_LAT))
    )

    x_km = (longitude - HOME_LON) * km_per_lon
    y_km = (latitude - HOME_LAT) * km_per_lat

    scale = RADAR_RADIUS / max(RADAR_RANGE_KM, 0.1)

    x = CENTER_X + x_km * scale
    y = CENTER_Y - y_km * scale

    return x, y


def get_api_bounds():
    lat_delta = RADAR_RANGE_KM / 111.0

    lon_delta = RADAR_RANGE_KM / (
        111.0 * math.cos(math.radians(HOME_LAT))
    )

    return {
        "lamin": HOME_LAT - lat_delta,
        "lamax": HOME_LAT + lat_delta,
        "lomin": HOME_LON - lon_delta,
        "lomax": HOME_LON + lon_delta,
    }


# ============================================================
# 8. AIRPORT DATABASE
# ============================================================

def load_airport_database():
    global airport_data
    global runway_data
    global last_airport_update

    try:
        print("Downloading airport database...")

        airport_response = http.get(
            AIRPORTS_URL,
            timeout=30
        )
        airport_response.raise_for_status()

        runway_response = http.get(
            RUNWAYS_URL,
            timeout=30
        )
        runway_response.raise_for_status()

        airports = []

        reader = csv.DictReader(
            io.StringIO(airport_response.text)
        )

        for row in reader:
            try:
                latitude = float(row["latitude_deg"])
                longitude = float(row["longitude_deg"])
            except Exception:
                continue

            airport_type = row.get("type", "")

            allowed_types = {
                "large_airport",
                "medium_airport",
                "small_airport",
                "heliport",
                "seaplane_base",
            }

            if airport_type not in allowed_types:
                continue

            if row.get("closed", "0") == "1":
                continue

            distance = calculate_distance(
                HOME_LAT,
                HOME_LON,
                latitude,
                longitude,
            )

            if distance > 250:
                continue

            bearing = calculate_bearing(
                HOME_LAT,
                HOME_LON,
                latitude,
                longitude,
            )

            ident = row.get("ident", "")

            airports.append(
                {
                    "ident": ident,
                    "name": row.get(
                        "name",
                        "Unknown Airport",
                    ),
                    "type": airport_type,
                    "latitude": latitude,
                    "longitude": longitude,
                    "iata": row.get(
                        "iata_code",
                        "",
                    ),
                    "icao": row.get(
                        "gps_code",
                        "",
                    ),
                    "elevation": row.get(
                        "elevation_ft",
                        "",
                    ),
                    "municipality": row.get(
                        "municipality",
                        "",
                    ),
                    "country": row.get(
                        "iso_country",
                        "",
                    ),
                    "distance": distance,
                    "bearing": bearing,
                    "is_home": (
                        ident.upper() == HOME_ICAO
                        or row.get("gps_code", "").upper()
                        == HOME_ICAO
                        or row.get("iata_code", "").upper()
                        == HOME_IATA
                    ),
                }
            )

        # Ensure BLR is always represented, even if the public CSV changes.
        if not any(a["is_home"] for a in airports):
            airports.append(
                {
                    "ident": HOME_ICAO,
                    "name": HOME_NAME,
                    "type": "large_airport",
                    "latitude": HOME_LAT,
                    "longitude": HOME_LON,
                    "iata": HOME_IATA,
                    "icao": HOME_ICAO,
                    "elevation": "3000",
                    "municipality": "Bengaluru",
                    "country": "IN",
                    "distance": 0.0,
                    "bearing": 0.0,
                    "is_home": True,
                }
            )

        runways = []

        reader = csv.DictReader(
            io.StringIO(runway_response.text)
        )

        for row in reader:
            airport_ident = row.get(
                "airport_ident",
                "",
            )

            if not airport_ident:
                continue

            try:
                le_lat = float(row["le_latitude_deg"])
                le_lon = float(row["le_longitude_deg"])
                he_lat = float(row["he_latitude_deg"])
                he_lon = float(row["he_longitude_deg"])
            except Exception:
                continue

            distance = calculate_distance(
                HOME_LAT,
                HOME_LON,
                le_lat,
                le_lon,
            )

            if distance > 250:
                continue

            runways.append(
                {
                    "airport_ident": airport_ident,
                    "le_lat": le_lat,
                    "le_lon": le_lon,
                    "he_lat": he_lat,
                    "he_lon": he_lon,
                    "length_ft": row.get(
                        "length_ft",
                        "",
                    ),
                    "width_ft": row.get(
                        "width_ft",
                        "",
                    ),
                    "surface": row.get(
                        "surface",
                        "",
                    ),
                    "le_ident": row.get(
                        "le_ident",
                        "",
                    ),
                    "he_ident": row.get(
                        "he_ident",
                        "",
                    ),
                }
            )

        with airport_lock:
            airport_data = airports
            runway_data = runways
            last_airport_update = time.time()

        print(
            f"Loaded {len(airports)} airports "
            f"and {len(runways)} runways."
        )

    except Exception as exc:
        print("Airport database error:", exc)


def airport_database_loop():
    while True:
        load_airport_database()
        time.sleep(AIRPORT_REFRESH_INTERVAL)


# ============================================================
# 9. AIRCRAFT DATA
# ============================================================

def fetch_aircraft_metadata(icao):
    """Fetch optional aircraft metadata from the OpenSky metadata endpoint."""
    try:
        response = http.get(
            METADATA_URL + icao,
            timeout=8,
        )

        if response.status_code == 429:
            return None

        if response.status_code != 200:
            return None

        data = response.json()
        typecode = data.get("typecode")

        return {
            "typecode": typecode,
            "model": data.get("model"),
            "manufacturer": data.get("manufacturername"),
            "registration": data.get("registration"),
            "operator_icao": data.get("operatoricao"),
            "operator_iata": data.get("operatoriata"),
            "owner": data.get("owner"),
            "serial_number": data.get("serialnumber"),
            "built": data.get("built"),
            "engines": data.get("engines"),
            "size": get_aircraft_size(typecode),
            "metadata_updated": time.time(),
        }

    except Exception:
        return None


def metadata_loop():
    """Enrich currently visible aircraft without hammering the metadata API."""
    while True:
        time.sleep(METADATA_UPDATE_INTERVAL)

        with data_lock:
            visible_ids = list(aircraft_data.keys())

        # Keep requests deliberately limited because OpenSky metadata
        # can be rate limited. Only refresh aircraft whose metadata
        # is missing or older than the cache interval.
        for icao in visible_ids[:8]:
            now = time.time()

            with metadata_lock:
                existing = dict(
                    aircraft_metadata.get(icao, {})
                )

            updated_at = existing.get(
                "metadata_updated",
                0,
            )

            if (
                now - updated_at
                < METADATA_UPDATE_INTERVAL
            ):
                continue

            metadata = fetch_aircraft_metadata(icao)

            if metadata is None:
                continue

            # Preserve live-feed values when the metadata endpoint
            # does not provide a replacement.
            merged = existing.copy()

            for key, value in metadata.items():
                if value not in (None, ""):
                    merged[key] = value

            with metadata_lock:
                aircraft_metadata[icao] = merged

            with data_lock:
                if icao in aircraft_data:
                    plane = aircraft_data[icao]

                    if merged.get("registration"):
                        plane["registration"] = merged[
                            "registration"
                        ]

            time.sleep(0.4)


def get_aircraft_adsblol():
    global api_status
    global connection_ok
    global last_update_time
    global retry_after_seconds

    try:
        distance_nm = max(
            1,
            math.ceil(
                RADAR_RANGE_KM * 0.539956803
            ),
        )

        url = ADSBLOL_URL.format(
            lat=HOME_LAT,
            lon=HOME_LON,
            dist=distance_nm,
        )

        response = http.get(
            url,
            timeout=15,
        )

        if response.status_code == 429:
            retry_after = response.headers.get(
                "Retry-After"
            )

            try:
                retry_seconds = (
                    int(retry_after)
                    if retry_after
                    else 60
                )
            except Exception:
                retry_seconds = 60

            retry_after_seconds = max(
                30,
                min(retry_seconds, 300),
            )

            api_status = (
                "RATE LIMITED • ADSB.LOL"
            )
            connection_ok = True

            print(
                "ADSB.lol rate limit reached. "
                f"Next attempt in {retry_after_seconds}s."
            )
            return None

        response.raise_for_status()

        data = response.json()

        states = data.get("ac")

        if states is None:
            states = data.get(
                "aircraft",
                [],
            )

        if states is None:
            states = []

        new_aircraft = {}

        for plane in states:
            if not plane:
                continue

            icao = (
                plane.get("hex")
                or plane.get("icao")
                or ""
            )

            if not icao:
                continue

            icao = str(icao).strip().lower()

            latitude = plane.get("lat")
            longitude = plane.get("lon")

            if latitude is None or longitude is None:
                continue

            try:
                latitude = float(latitude)
                longitude = float(longitude)
            except Exception:
                continue

            callsign = (
                plane.get("flight")
                or plane.get("callsign")
                or plane.get("r")
                or "UNKNOWN"
            )

            callsign = str(callsign).strip() or "UNKNOWN"

            raw_altitude = plane.get("alt_baro")

            if isinstance(
                raw_altitude,
                (int, float),
            ):
                altitude = (
                    float(raw_altitude)
                    / 3.28084
                )
            else:
                raw_geom = plane.get(
                    "alt_geom"
                )

                if isinstance(
                    raw_geom,
                    (int, float),
                ):
                    altitude = (
                        float(raw_geom)
                        / 3.28084
                    )
                else:
                    altitude = None

            raw_speed = plane.get("gs")

            if isinstance(
                raw_speed,
                (int, float),
            ):
                speed = (
                    float(raw_speed)
                    * 0.514444
                )
            else:
                speed = None

            raw_heading = (
                plane.get("track")
                if plane.get("track") is not None
                else plane.get("nav_heading")
            )

            try:
                heading = (
                    float(raw_heading)
                    if raw_heading is not None
                    else None
                )
            except Exception:
                heading = None

            distance = calculate_distance(
                HOME_LAT,
                HOME_LON,
                latitude,
                longitude,
            )

            if distance > RADAR_RANGE_KM:
                continue

            bearing = calculate_bearing(
                HOME_LAT,
                HOME_LON,
                latitude,
                longitude,
            )

            x, y = radar_position(
                distance,
                bearing,
            )

            typecode = (
                plane.get("t")
                or plane.get("type")
                or ""
            )

            typecode = str(
                typecode
            ).upper().strip()

            registration = (
                plane.get("r")
                or ""
            )

            with metadata_lock:
                existing_metadata = aircraft_metadata.get(
                    icao,
                    {},
                ).copy()

                if typecode:
                    existing_metadata["typecode"] = typecode
                    existing_metadata["size"] = get_aircraft_size(
                        typecode
                    )

                if registration:
                    existing_metadata["registration"] = registration

                aircraft_metadata[icao] = existing_metadata

            new_aircraft[icao] = {
                "icao": icao,
                "callsign": callsign,
                "registration": registration,
                "latitude": latitude,
                "longitude": longitude,
                "distance": distance,
                "bearing": bearing,
                "heading": heading,
                "altitude": altitude,
                "speed": speed,
                "target_x": x,
                "target_y": y,
                "last_seen": time.time(),
            }

        api_status = "LIVE • ADSB.LOL"
        connection_ok = True
        retry_after_seconds = 0
        last_update_time = time.time()

        return new_aircraft

    except requests.exceptions.Timeout:
        api_status = "TIMEOUT • KEEPING LAST DATA"
        connection_ok = False
        return None

    except requests.exceptions.ConnectionError:
        api_status = (
            "CONNECTION ERROR • KEEPING LAST DATA"
        )
        connection_ok = False
        return None

    except requests.exceptions.RequestException as exc:
        api_status = (
            "ADSB.LOL ERROR • KEEPING LAST DATA"
        )
        connection_ok = False
        print("ADSB.lol request error:", exc)
        return None

    except Exception as exc:
        api_status = (
            "ADSB.LOL ERROR • KEEPING LAST DATA"
        )
        connection_ok = False
        print("ADSB.lol error:", exc)
        return None


def get_aircraft_opensky():
    global api_status
    global connection_ok
    global last_update_time
    global retry_after_seconds

    try:
        params = get_api_bounds()

        response = http.get(
            STATES_URL,
            params=params,
            timeout=15,
        )

        if response.status_code == 429:
            retry_after = response.headers.get(
                "Retry-After"
            )

            try:
                retry_seconds = (
                    int(retry_after)
                    if retry_after
                    else 60
                )
            except Exception:
                retry_seconds = 60

            retry_after_seconds = max(
                60,
                min(retry_seconds, 600),
            )

            api_status = "RATE LIMITED • OPENSKY"
            connection_ok = True
            return None

        response.raise_for_status()

        data = response.json()
        states = data.get("states") or []

        new_aircraft = {}

        for plane in states:
            if not plane:
                continue

            icao = plane[0]
            longitude = plane[5]
            latitude = plane[6]

            if (
                not icao
                or latitude is None
                or longitude is None
            ):
                continue

            callsign = (
                plane[1].strip()
                if plane[1]
                else "UNKNOWN"
            )

            distance = calculate_distance(
                HOME_LAT,
                HOME_LON,
                latitude,
                longitude,
            )

            if distance > RADAR_RANGE_KM:
                continue

            bearing = calculate_bearing(
                HOME_LAT,
                HOME_LON,
                latitude,
                longitude,
            )

            x, y = radar_position(
                distance,
                bearing,
            )

            new_aircraft[icao] = {
                "icao": icao,
                "callsign": callsign,
                "registration": "",
                "latitude": latitude,
                "longitude": longitude,
                "distance": distance,
                "bearing": bearing,
                "heading": plane[10],
                "altitude": plane[7],
                "speed": plane[9],
                "target_x": x,
                "target_y": y,
                "last_seen": time.time(),
            }

        api_status = "LIVE • OPENSKY"
        connection_ok = True
        retry_after_seconds = 0
        last_update_time = time.time()

        return new_aircraft

    except Exception as exc:
        api_status = (
            "OPENSKY ERROR • KEEPING LAST DATA"
        )
        connection_ok = False
        print("OpenSky fallback error:", exc)
        return None


def get_aircraft():
    result = get_aircraft_adsblol()

    if result is not None:
        return result

    if USE_OPENSKY_FALLBACK:
        return get_aircraft_opensky()

    return None


def api_loop():
    global aircraft_data

    consecutive_rate_limits = 0

    while True:
        new_data = get_aircraft()

        if new_data is not None:
            consecutive_rate_limits = 0

            with data_lock:
                previous_ids = set(
                    aircraft_data.keys()
                )
                current_ids = set(
                    new_data.keys()
                )

                # Entering aircraft
                for icao in current_ids - previous_ids:
                    entry_animation[icao] = {
                        "started": time.time(),
                        "duration":
                            ENTRY_ANIMATION_MS / 1000.0,
                    }

                # Exiting aircraft
                for icao in previous_ids - current_ids:
                    recently_removed[icao] = {
                        "plane":
                            aircraft_data[icao].copy(),
                        "expires":
                            time.time()
                            + EXIT_RETENTION_SECONDS,
                    }

                # Update live aircraft + build intelligence history.
                for icao, plane in new_data.items():
                    if icao not in aircraft_data:
                        plane["x"] = plane["target_x"]
                        plane["y"] = plane["target_y"]
                    else:
                        plane["x"] = aircraft_data[icao]["x"]
                        plane["y"] = aircraft_data[icao]["y"]

                    update_aircraft_history(icao, plane)

                    plane["distance_status"], plane[
                        "distance_change"
                    ] = calculate_distance_trend(icao)

                    plane["vertical_status"] = (
                        calculate_vertical_trend(icao)
                    )

                    plane["flight_status"] = (
                        determine_flight_status(icao, plane)
                    )

                    (
                        plane["airport_behavior"],
                        nearest_airport,
                        aligned_runway,
                        nearest_airport_distance,
                    ) = classify_airport_behavior(plane)

                    if nearest_airport is not None:
                        plane["nearest_airport_ident"] = (
                            nearest_airport.get("ident", "UNKNOWN")
                        )
                        plane["nearest_airport_name"] = (
                            nearest_airport.get("name", "UNKNOWN")
                        )
                    else:
                        plane["nearest_airport_ident"] = "UNKNOWN"
                        plane["nearest_airport_name"] = "UNKNOWN"

                    plane["nearest_airport_distance"] = (
                        nearest_airport_distance
                    )
                    plane["aligned_runway"] = (
                        f"{aligned_runway['le_ident']}/"
                        f"{aligned_runway['he_ident']}"
                        if aligned_runway is not None
                        else "NONE"
                    )

                    plane["weather"] = get_aircraft_weather(
                        plane.get("latitude"),
                        plane.get("longitude"),
                    )

                    aircraft_data[icao] = plane

                # Remove stale live entries, but retain history.
                # Keeping history lets a returning aircraft continue
                # with useful trend information.
                for icao in previous_ids - current_ids:
                    del aircraft_data[icao]

                # Bound long-lived history memory.
                cutoff = time.time() - 20 * 60
                for icao in list(aircraft_history.keys()):
                    history = aircraft_history[icao]
                    if history and history[-1]["time"] < cutoff:
                        aircraft_history.pop(icao, None)

            sleep_time = AIRCRAFT_UPDATE_INTERVAL

        else:
            if api_status.startswith(
                "RATE LIMITED"
            ):
                consecutive_rate_limits += 1

                backoff = min(
                    60 * consecutive_rate_limits,
                    300,
                )

                sleep_time = max(
                    retry_after_seconds,
                    backoff,
                )
            else:
                sleep_time = AIRCRAFT_UPDATE_INTERVAL

        time.sleep(sleep_time)


# ============================================================
# 10. MAIN WINDOW
# ============================================================


root = tk.Tk()

root.title(
    "Airspace Radar • Geographic Origin"
)

root.geometry(
    f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}"
)

root.resizable(False, False)

root.configure(bg=BG)


# ============================================================
# 11. HEADER
# ============================================================

header = tk.Frame(
    root,
    bg=PANEL,
    height=68,
)

header.pack(fill="x")

header.pack_propagate(False)

header_left = tk.Frame(
    header,
    bg=PANEL,
)

header_left.pack(
    side="left",
    padx=22,
)

logo = tk.Label(
    header_left,
    text="◉",
    fg=GREEN,
    bg=PANEL,
    font=("Arial", 20, "bold"),
)

logo.pack(
    side="left",
    padx=(0, 10),
)

title = tk.Label(
    header_left,
    text="AIRSPACE",
    fg=TEXT,
    bg=PANEL,
    font=("Arial", 17, "bold"),
)

title.pack(side="left")

title2 = tk.Label(
    header_left,
    text=" RADAR",
    fg=GREEN,
    bg=PANEL,
    font=("Arial", 17, "bold"),
)

title2.pack(side="left")


# ============================================================
# 12. HEADER MODE SWITCH
# ============================================================

view_frame = tk.Frame(
    header,
    bg=PANEL,
)

view_frame.pack(
    side="left",
    padx=42,
)


def apply_button_style(button, active, color):
    if active:
        button.config(
            bg=color,
            fg="#06100a",
            activebackground=color,
            activeforeground="#06100a",
        )
    else:
        button.config(
            bg=PANEL_2,
            fg=TEXT_DIM,
            activebackground=PANEL_2,
            activeforeground=TEXT,
        )


def set_view(mode):
    global VIEW_MODE

    VIEW_MODE = mode

    apply_button_style(
        radar_button,
        mode == "RADAR",
        GREEN,
    )

    apply_button_style(
        map_button,
        mode == "MAP",
        BLUE,
    )


radar_button = tk.Button(
    view_frame,
    text="RADAR",
    command=lambda: set_view("RADAR"),
    bg=GREEN,
    fg="#06100a",
    relief="flat",
    bd=0,
    width=9,
    font=("Arial", 9, "bold"),
)

radar_button.pack(
    side="left",
    padx=3,
)

map_button = tk.Button(
    view_frame,
    text="MAP",
    command=lambda: set_view("MAP"),
    bg=PANEL_2,
    fg=TEXT_DIM,
    relief="flat",
    bd=0,
    width=9,
    font=("Arial", 9, "bold"),
)

map_button.pack(
    side="left",
    padx=3,
)


# ============================================================
# 14. HEADER STATUS
# ============================================================

header_status = tk.Label(
    header,
    text="● CONNECTING",
    fg=YELLOW,
    bg=PANEL,
    font=("Arial", 10, "bold"),
)

header_status.pack(
    side="right",
    padx=24,
)


# ============================================================
# 15. MAIN AREA
# ============================================================

main = tk.Frame(
    root,
    bg=BG,
)

main.pack(
    fill="both",
    expand=True,
)

radar_frame = tk.Frame(
    main,
    bg=BG,
    width=RADAR_WIDTH,
    height=694,
)

radar_frame.pack(
    side="left"
)

radar_frame.pack_propagate(False)

canvas = tk.Canvas(
    radar_frame,
    width=RADAR_WIDTH,
    height=694,
    bg=BG,
    highlightthickness=0,
    bd=0,
)

canvas.pack(
    fill="both",
    expand=True,
)


# ============================================================
# 16. SIDE PANEL
# ============================================================

side_panel = tk.Frame(
    main,
    bg=PANEL,
    width=SIDE_WIDTH,
    height=694,
)

side_panel.pack(
    side="right"
)

side_panel.pack_propagate(False)

side_header = tk.Frame(
    side_panel,
    bg=PANEL,
    height=102,
)

side_header.pack(
    fill="x"
)

side_header.pack_propagate(False)

side_title = tk.Label(
    side_header,
    text=HOME_NAME,
    fg=TEXT,
    bg=PANEL,
    font=("Arial", 13, "bold"),
)

side_title.pack(
    anchor="w",
    padx=22,
    pady=(16, 0),
)

side_subtitle = tk.Label(
    side_header,
    text="BLR  •  VOBL  •  BENGALURU",
    fg=TEXT_DIM,
    bg=PANEL,
    font=("Arial", 9, "bold"),
)

side_subtitle.pack(
    anchor="w",
    padx=22,
    pady=(4, 0),
)

side_subtitle2 = tk.Label(
    side_header,
    text="RADAR ORIGIN • USER DEFINED",
    fg=BLUE,
    bg=PANEL,
    font=("Arial", 8, "bold"),
)

side_subtitle2.pack(
    anchor="w",
    padx=22,
    pady=(5, 0),
)


# ============================================================
# 17. STATS
# ============================================================

stats = tk.Frame(
    side_panel,
    bg=PANEL,
    height=100,
)

stats.pack(fill="x")

stats.pack_propagate(False)

stats_left = tk.Frame(
    stats,
    bg=PANEL,
)
stats_left.pack(
    side="left",
    padx=22,
)

tk.Label(
    stats_left,
    text="AIRCRAFT",
    fg=TEXT_DIM,
    bg=PANEL,
    font=("Arial", 8, "bold"),
).pack(anchor="w")

count_value = tk.Label(
    stats_left,
    text="0",
    fg=GREEN,
    bg=PANEL,
    font=("Arial", 24, "bold"),
)
count_value.pack(anchor="w")

stats_right = tk.Frame(
    stats,
    bg=PANEL,
)
stats_right.pack(
    side="right",
    padx=22,
)

tk.Label(
    stats_right,
    text="AIRPORTS",
    fg=TEXT_DIM,
    bg=PANEL,
    font=("Arial", 8, "bold"),
).pack(anchor="w")

airport_count_value = tk.Label(
    stats_right,
    text="0",
    fg=BLUE,
    bg=PANEL,
    font=("Arial", 24, "bold"),
)
airport_count_value.pack(anchor="w")


# ============================================================
# 18. CONNECTION / UPDATE STATUS
# ============================================================

connection_frame = tk.Frame(
    side_panel,
    bg=PANEL,
    height=82,
)

connection_frame.pack(fill="x")

connection_frame.pack_propagate(False)

connection_label = tk.Label(
    connection_frame,
    text="CONNECTION",
    fg=TEXT_DIM,
    bg=PANEL,
    font=("Arial", 8, "bold"),
)

connection_label.pack(
    anchor="w",
    padx=22,
    pady=(6, 0),
)

connection_value = tk.Label(
    connection_frame,
    text="CONNECTING",
    fg=YELLOW,
    bg=PANEL,
    font=("Arial", 12, "bold"),
)

connection_value.pack(
    anchor="w",
    padx=22,
    pady=(3, 0),
)


# ============================================================
# 19. RANGE + ALTITUDE + OPERATIONS
# ============================================================

controls = tk.Frame(
    side_panel,
    bg=PANEL,
    height=205,
)

controls.pack(
    fill="x",
)

controls.pack_propagate(False)


# ============================================================
# RANGE
# ============================================================

range_label = tk.Label(
    controls,
    text="RADAR RANGE",
    fg=TEXT_DIM,
    bg=PANEL,
    font=("Arial", 8, "bold"),
)

range_label.place(
    x=22,
    y=8,
)

range_var = tk.StringVar(
    value=f"{RADAR_RANGE_KM} km"
)

range_menu = tk.OptionMenu(
    controls,
    range_var,
    "10 km",
    "25 km",
    "50 km",
    "100 km",
    "200 km",
)

range_menu.config(
    bg=PANEL_2,
    fg=TEXT,
    activebackground="#1e292d",
    activeforeground=TEXT,
    highlightthickness=0,
    bd=0,
    width=10,
    anchor="w",
    font=("Arial", 9),
)

range_menu["menu"].config(
    bg=PANEL_2,
    fg=TEXT,
    activebackground="#1e292d",
    activeforeground=TEXT,
)

range_menu.place(
    x=22,
    y=26,
)


def change_range(*_args):
    global RADAR_RANGE_KM

    try:
        RADAR_RANGE_KM = int(
            range_var.get().replace(
                " km",
                "",
            )
        )
    except Exception:
        return

    with data_lock:
        for plane in aircraft_data.values():
            plane["distance"] = calculate_distance(
                HOME_LAT,
                HOME_LON,
                plane["latitude"],
                plane["longitude"],
            )
            plane["bearing"] = calculate_bearing(
                HOME_LAT,
                HOME_LON,
                plane["latitude"],
                plane["longitude"],
            )
            x, y = radar_position(
                plane["distance"],
                plane["bearing"],
            )
            plane["target_x"] = x
            plane["target_y"] = y


range_var.trace_add(
    "write",
    change_range,
)


# ============================================================
# ALTITUDE
# ============================================================

altitude_label = tk.Label(
    controls,
    text="ALTITUDE FILTER",
    fg=TEXT_DIM,
    bg=PANEL,
    font=("Arial", 8, "bold"),
)

altitude_label.place(
    x=190,
    y=8,
)

altitude_var = tk.StringVar(
    value="All"
)

altitude_menu = tk.OptionMenu(
    controls,
    altitude_var,
    "All",
    "Below 10,000 ft",
    "10,000 - 25,000 ft",
    "25,000 - 40,000 ft",
    "Above 40,000 ft",
)

altitude_menu.config(
    bg=PANEL_2,
    fg=TEXT,
    activebackground="#1e292d",
    activeforeground=TEXT,
    highlightthickness=0,
    bd=0,
    width=10,
    anchor="w",
    font=("Arial", 9),
)

altitude_menu["menu"].config(
    bg=PANEL_2,
    fg=TEXT,
    activebackground="#1e292d",
    activeforeground=TEXT,
)

altitude_menu.place(
    x=190,
    y=26,
)


# ============================================================
# TRACK
# ============================================================

track_label = tk.Label(
    controls,
    text="TRACK",
    fg=TEXT_DIM,
    bg=PANEL,
    font=("Arial", 8, "bold"),
)

track_label.place(
    x=22,
    y=80,
)

track_var = tk.StringVar(
    value=TRACK_DISPLAY_MODE,
)

track_menu = tk.OptionMenu(
    controls,
    track_var,
    "OFF",
    "SELECTED",
    "ALL",
)

track_menu.config(
    bg=PANEL_2,
    fg=TEXT,
    activebackground="#1e292d",
    activeforeground=TEXT,
    highlightthickness=0,
    bd=0,
    width=10,
    anchor="w",
    font=("Arial", 9),
)

track_menu["menu"].config(
    bg=PANEL_2,
    fg=TEXT,
    activebackground="#1e292d",
    activeforeground=TEXT,
)

track_menu.place(
    x=22,
    y=98,
)


def change_track_mode(*_args):
    global TRACK_DISPLAY_MODE
    TRACK_DISPLAY_MODE = track_var.get()


track_var.trace_add(
    "write",
    change_track_mode,
)


# ============================================================
# BEHAVIOR
# ============================================================

behavior_label = tk.Label(
    controls,
    text="BEHAVIOR",
    fg=TEXT_DIM,
    bg=PANEL,
    font=("Arial", 8, "bold"),
)

behavior_label.place(
    x=190,
    y=80,
)

behavior_var = tk.StringVar(
    value=BEHAVIOR_FILTER,
)

behavior_menu = tk.OptionMenu(
    controls,
    behavior_var,
    "ALL",
    "ARRIVAL",
    "DEPARTURE",
    "OVERFLIGHT",
    "HOLDING",
)

behavior_menu.config(
    bg=PANEL_2,
    fg=TEXT,
    activebackground="#1e292d",
    activeforeground=TEXT,
    highlightthickness=0,
    bd=0,
    width=10,
    anchor="w",
    font=("Arial", 9),
)

behavior_menu["menu"].config(
    bg=PANEL_2,
    fg=TEXT,
    activebackground="#1e292d",
    activeforeground=TEXT,
)

behavior_menu.place(
    x=190,
    y=98,
)


def change_behavior_filter(*_args):
    global BEHAVIOR_FILTER
    BEHAVIOR_FILTER = behavior_var.get()


behavior_var.trace_add(
    "write",
    change_behavior_filter,
)


# ============================================================
# AIRCRAFT SIZE FILTER
# ============================================================

size_label = tk.Label(
    controls,
    text="AIRCRAFT SIZE",
    fg=TEXT_DIM,
    bg=PANEL,
    font=("Arial", 8, "bold"),
)

size_label.place(
    x=22,
    y=154,
)

size_var = tk.StringVar(
    value=SIZE_FILTER,
)

size_menu = tk.OptionMenu(
    controls,
    size_var,
    "ALL",
    "small",
    "medium",
    "large",
    "very_large",
)

size_menu.config(
    bg=PANEL_2,
    fg=TEXT,
    activebackground="#1e292d",
    activeforeground=TEXT,
    highlightthickness=0,
    bd=0,
    width=10,
    anchor="w",
    font=("Arial", 9),
)

size_menu["menu"].config(
    bg=PANEL_2,
    fg=TEXT,
    activebackground="#1e292d",
    activeforeground=TEXT,
)

size_menu.place(
    x=22,
    y=172,
)


def change_size_filter(*_args):
    global SIZE_FILTER
    SIZE_FILTER = size_var.get()


size_var.trace_add(
    "write",
    change_size_filter,
)



def altitude_allowed(altitude):
    if altitude is None:
        return False

    altitude_ft = altitude * 3.28084
    selected = altitude_var.get()

    if selected == "All":
        return True

    if selected == "Below 10,000 ft":
        return altitude_ft < 10000

    if selected == "10,000 - 25,000 ft":
        return (
            10000 <= altitude_ft < 25000
        )

    if selected == "25,000 - 40,000 ft":
        return (
            25000 <= altitude_ft < 40000
        )

    if selected == "Above 40,000 ft":
        return altitude_ft >= 40000

    return True


# ============================================================
# 20. SELECTED OBJECT
# ============================================================

info_header = tk.Frame(
    side_panel,
    bg=PANEL,
    height=40,
)

info_header.pack(fill="x")

info_header.pack_propagate(False)

info_header_label = tk.Label(
    info_header,
    text="SELECTED OBJECT",
    fg=TEXT_DIM,
    bg=PANEL,
    font=("Arial", 8, "bold"),
)

info_header_label.pack(
    anchor="w",
    padx=22,
    pady=(12, 0),
)

info_container = tk.Frame(
    side_panel,
    bg=PANEL,
)

info_container.pack(
    fill="both",
    expand=True,
    padx=18,
    pady=(0, 12),
)

info_text = tk.Text(
    info_container,
    bg=PANEL,
    fg=TEXT,
    insertbackground=TEXT,
    font=("Consolas", 9),
    relief="flat",
    bd=0,
    wrap="word",
    width=30,
    height=18,
    padx=5,
    pady=5,
    cursor="arrow",
)

info_scroll = tk.Scrollbar(
    info_container,
    orient="vertical",
    command=info_text.yview,
    bg=PANEL,
    troughcolor=PANEL,
    activebackground=PANEL_2,
    relief="flat",
    bd=0,
    width=10,
    highlightthickness=0,
    highlightbackground=PANEL,
)

info_text.configure(
    yscrollcommand=info_scroll.set
)

info_text.pack(
    side="left",
    fill="both",
    expand=True,
)

info_scroll.pack(
    side="right",
    fill="y",
)


def set_info(
    text,
    color=None,
    preserve_scroll=True,
):
    if color is None:
        color = TEXT

    try:
        old_position = info_text.yview()[0]
    except Exception:
        old_position = 0.0

    info_text.configure(
        state="normal",
        fg=color,
    )

    info_text.delete(
        "1.0",
        "end",
    )

    info_text.insert(
        "1.0",
        text,
    )

    info_text.configure(
        state="disabled",
    )

    if preserve_scroll:
        try:
            info_text.yview_moveto(old_position)
        except Exception:
            pass
    else:
        info_text.yview_moveto(0.0)


set_info(
    "HOVER OVER AN AIRCRAFT OR AIRPORT.\n\n"
    "CLICK TO LOCK INFORMATION.\n\n"
    f"{HOME_IATA} / {HOME_ICAO} is the radar origin.",
    TEXT_DIM,
)


def info_mousewheel(event):
    info_text.yview_scroll(
        int(-1 * (event.delta / 120)),
        "units",
    )


info_text.bind(
    "<MouseWheel>",
    info_mousewheel,
)


# ============================================================
# 21. FOOTER
# ============================================================

footer = tk.Frame(
    root,
    bg=PANEL,
    height=38,
)

footer.pack(fill="x")

footer.pack_propagate(False)

footer_left = tk.Label(
    footer,
    text="● CONNECTING",
    fg=YELLOW,
    bg=PANEL,
    font=("Arial", 8, "bold"),
)

footer_left.pack(
    side="left",
    padx=18,
)

footer_source = tk.Label(
    footer,
    text="ADSB.LOL  •  OURAIRPORTS",
    fg=TEXT_DIM,
    bg=PANEL,
    font=("Arial", 8),
)

footer_source.pack(
    side="left",
    padx=10,
)

footer_right = tk.Label(
    footer,
    text="",
    fg=TEXT_DIM,
    bg=PANEL,
    font=("Consolas", 8),
)

footer_right.pack(
    side="right",
    padx=18,
)


# ============================================================
# 22. RADAR BACKGROUND
# ============================================================

def draw_radar_background():
    """Professional instrument-style radar scope.

    Frontend-only change: live aircraft, selection, hover, tracks,
    airports, runways, filtering, and intelligence are unchanged.
    """
    global CENTER_X
    global CENTER_Y

    CENTER_X = RADAR_WIDTH / 2
    CENTER_Y = 354

    scope_r = 300
    outer_r = 312

    # ------------------------------------------------------------
    # SCOPE BACKGROUND
    # ------------------------------------------------------------
    canvas.create_rectangle(
        0,
        0,
        RADAR_WIDTH,
        694,
        fill=THEME["SCOPE_BG"],
        outline="",
    )

    # Instrument header
    canvas.create_text(
        24,
        16,
        text="AIRSPACE RADAR",
        fill=TEXT,
        anchor="nw",
        font=("Arial", 11, "bold"),
    )

    canvas.create_text(
        24,
        35,
        text=(
            f"ORIGIN  {HOME_LAT:.4f}°  {HOME_LON:.4f}°"
        ),
        fill=TEXT_DIM,
        anchor="nw",
        font=("Consolas", 8),
    )

    canvas.create_text(
        RADAR_WIDTH - 24,
        16,
        text="SURVEILLANCE",
        fill=GREEN,
        anchor="ne",
        font=("Arial", 9, "bold"),
    )

    canvas.create_text(
        RADAR_WIDTH - 24,
        35,
        text=f"{RADAR_RANGE_KM} KM RANGE",
        fill=TEXT_DIM,
        anchor="ne",
        font=("Consolas", 8),
    )

    # ------------------------------------------------------------
    # OUTER INSTRUMENT RINGS
    # ------------------------------------------------------------
    canvas.create_oval(
        CENTER_X - outer_r,
        CENTER_Y - outer_r,
        CENTER_X + outer_r,
        CENTER_Y + outer_r,
        outline=GRID,
        width=1,
    )

    canvas.create_oval(
        CENTER_X - scope_r,
        CENTER_Y - scope_r,
        CENTER_X + scope_r,
        CENTER_Y + scope_r,
        outline=GREEN_DIM,
        width=2,
    )

    # Range rings
    ring_specs = [
        (0.25, GRID),
        (0.50, GRID),
        (0.75, GRID),
    ]

    for fraction, ring_color in ring_specs:
        r = scope_r * fraction

        canvas.create_oval(
            CENTER_X - r,
            CENTER_Y - r,
            CENTER_X + r,
            CENTER_Y + r,
            outline=ring_color,
            width=1,
        )

    # Very subtle center ring
    canvas.create_oval(
        CENTER_X - 32,
        CENTER_Y - 32,
        CENTER_X + 32,
        CENTER_Y + 32,
        outline=GRID,
        width=1,
    )

    # ------------------------------------------------------------
    # CROSSHAIR
    # ------------------------------------------------------------
    canvas.create_line(
        CENTER_X - scope_r,
        CENTER_Y,
        CENTER_X + scope_r,
        CENTER_Y,
        fill=GRID,
        width=1,
    )

    canvas.create_line(
        CENTER_X,
        CENTER_Y - scope_r,
        CENTER_X,
        CENTER_Y + scope_r,
        fill=GRID,
        width=1,
    )

    # Short center reference lines
    canvas.create_line(
        CENTER_X - 24,
        CENTER_Y,
        CENTER_X - 8,
        CENTER_Y,
        fill=GREEN_DIM,
        width=2,
    )

    canvas.create_line(
        CENTER_X + 8,
        CENTER_Y,
        CENTER_X + 24,
        CENTER_Y,
        fill=GREEN_DIM,
        width=2,
    )

    canvas.create_line(
        CENTER_X,
        CENTER_Y - 24,
        CENTER_X,
        CENTER_Y - 8,
        fill=GREEN_DIM,
        width=2,
    )

    canvas.create_line(
        CENTER_X,
        CENTER_Y + 8,
        CENTER_X,
        CENTER_Y + 24,
        fill=GREEN_DIM,
        width=2,
    )

    # ------------------------------------------------------------
    # AZIMUTH TICKS
    # ------------------------------------------------------------
    for degrees in range(0, 360, 5):
        angle = math.radians(degrees)

        major = degrees % 30 == 0
        medium = degrees % 10 == 0

        if major:
            tick_inner = outer_r - 13
            tick_width = 2
        elif medium:
            tick_inner = outer_r - 10
            tick_width = 1
        else:
            tick_inner = outer_r - 6
            tick_width = 1

        outer = outer_r

        x1 = (
            CENTER_X
            + tick_inner * math.sin(angle)
        )
        y1 = (
            CENTER_Y
            - tick_inner * math.cos(angle)
        )

        x2 = (
            CENTER_X
            + outer * math.sin(angle)
        )
        y2 = (
            CENTER_Y
            - outer * math.cos(angle)
        )

        canvas.create_line(
            x1,
            y1,
            x2,
            y2,
            fill=GREEN_DIM,
            width=tick_width,
        )

        if major:
            label_r = outer_r + 22
            lx = (
                CENTER_X
                + label_r * math.sin(angle)
            )
            ly = (
                CENTER_Y
                - label_r * math.cos(angle)
            )

            canvas.create_text(
                lx,
                ly,
                text=f"{degrees:03d}",
                fill=TEXT_DIM,
                font=("Consolas", 7),
            )

    # ------------------------------------------------------------
    # COMPASS
    # ------------------------------------------------------------
    compass = {
        0: "N",
        45: "NE",
        90: "E",
        135: "SE",
        180: "S",
        225: "SW",
        270: "W",
        315: "NW",
    }

    for degrees, label in compass.items():
        angle = math.radians(degrees)
        label_r = outer_r + 42

        x = (
            CENTER_X
            + label_r * math.sin(angle)
        )
        y = (
            CENTER_Y
            - label_r * math.cos(angle)
        )

        canvas.create_text(
            x,
            y,
            text=label,
            fill=TEXT if len(label) == 1 else TEXT_DIM,
            font=(
                "Arial",
                13 if len(label) == 1 else 8,
                "bold",
            ),
        )

    # ------------------------------------------------------------
    # RANGE MARKERS
    # ------------------------------------------------------------
    for fraction in (0.25, 0.50, 0.75, 1.0):
        r = scope_r * fraction
        distance = RADAR_RANGE_KM * fraction

        canvas.create_text(
            CENTER_X + 8,
            CENTER_Y - r,
            text=f"{distance:g} KM",
            fill=GREEN_DIM,
            anchor="sw",
            font=("Consolas", 7),
        )

    # ------------------------------------------------------------
    # HOME / RADAR ORIGIN
    # ------------------------------------------------------------
    canvas.create_oval(
        CENTER_X - 5,
        CENTER_Y - 5,
        CENTER_X + 5,
        CENTER_Y + 5,
        fill=RED,
        outline=RED,
    )

    canvas.create_oval(
        CENTER_X - 11,
        CENTER_Y - 11,
        CENTER_X + 11,
        CENTER_Y + 11,
        outline=RED,
        width=1,
    )

    canvas.create_text(
        CENTER_X + 16,
        CENTER_Y + 8,
        text=HOME_IATA,
        fill=TEXT,
        anchor="nw",
        font=("Arial", 9, "bold"),
    )

    canvas.create_text(
        CENTER_X + 16,
        CENTER_Y + 23,
        text=HOME_ICAO,
        fill=TEXT_DIM,
        anchor="nw",
        font=("Consolas", 7, "bold"),
    )

    # ------------------------------------------------------------
    # INSTRUMENT READOUTS
    # ------------------------------------------------------------
    canvas.create_text(
        CENTER_X,
        72,
        text="TRUE NORTH",
        fill=TEXT_DIM,
        font=("Consolas", 7, "bold"),
    )

    canvas.create_text(
        24,
        650,
        text="ADS-B SURVEILLANCE",
        fill=TEXT_DIM,
        anchor="sw",
        font=("Consolas", 7, "bold"),
    )

    canvas.create_text(
        RADAR_WIDTH - 24,
        650,
        text="NO TRAILS UNLESS SELECTED",
        fill=TEXT_DIM,
        anchor="se",
        font=("Consolas", 7),
    )


# ============================================================
# 23. MAP BACKGROUND
# ============================================================

def draw_map_background():
    global CENTER_X
    global CENTER_Y

    CENTER_X = RADAR_WIDTH / 2
    CENTER_Y = 347

    canvas.create_rectangle(
        0,
        0,
        RADAR_WIDTH,
        694,
        fill=MAP_LAND,
        outline="",
    )

    canvas.create_text(
        20,
        18,
        text="GEOGRAPHIC AIRSPACE MAP",
        fill=TEXT_DIM,
        anchor="nw",
        font=("Arial", 9, "bold"),
    )

    canvas.create_text(
        RADAR_WIDTH - 20,
        18,
        text=f"RANGE  {RADAR_RANGE_KM} KM",
        fill=TEXT_DIM,
        anchor="ne",
        font=("Consolas", 9, "bold"),
    )

    grid_km = 10
    limit = RADAR_RANGE_KM + grid_km

    distance = grid_km

    while distance <= limit:
        longitude_offset = (
            distance
            /
            (
                111
                * math.cos(
                    math.radians(HOME_LAT)
                )
            )
        )

        x1, _ = map_position(
            HOME_LAT,
            HOME_LON + longitude_offset,
        )

        x2, _ = map_position(
            HOME_LAT,
            HOME_LON - longitude_offset,
        )

        canvas.create_line(
            x1,
            0,
            x1,
            694,
            fill=MAP_GRID,
        )

        canvas.create_line(
            x2,
            0,
            x2,
            694,
            fill=MAP_GRID,
        )

        y_top = map_position(
            HOME_LAT + distance / 111,
            HOME_LON,
        )[1]

        y_bottom = map_position(
            HOME_LAT - distance / 111,
            HOME_LON,
        )[1]

        canvas.create_line(
            0,
            y_top,
            RADAR_WIDTH,
            y_top,
            fill=MAP_GRID,
        )

        canvas.create_line(
            0,
            y_bottom,
            RADAR_WIDTH,
            y_bottom,
            fill=MAP_GRID,
        )

        distance += grid_km

    # Airport-centered range circle
    canvas.create_oval(
        CENTER_X - RADAR_RADIUS,
        CENTER_Y - RADAR_RADIUS,
        CENTER_X + RADAR_RADIUS,
        CENTER_Y + RADAR_RADIUS,
        outline=BLUE_DIM,
        width=1,
    )

    # Home airport marker
    canvas.create_rectangle(
        CENTER_X - 5,
        CENTER_Y - 5,
        CENTER_X + 5,
        CENTER_Y + 5,
        fill=RED,
        outline=RED,
    )

    canvas.create_text(
        CENTER_X + 10,
        CENTER_Y + 10,
        text=f"{HOME_IATA} • {HOME_ICAO}",
        fill=TEXT,
        anchor="nw",
        font=("Arial", 9, "bold"),
    )


# ============================================================
# 24. MAP WEATHER GRAPHICS — DISABLED OVERLAY
# ============================================================

def draw_weather_layer():
    # Kept for compatibility; weather is no longer painted over MAP.
    return


def draw_weather_panel():
    # Kept for compatibility; weather is shown in aircraft details.
    return


# ============================================================
# 25. RUNWAY ORIENTATION
# ============================================================

def runway_bearing(runway):
    return calculate_bearing(
        runway["le_lat"],
        runway["le_lon"],
        runway["he_lat"],
        runway["he_lon"],
    )


def runway_length_km(runway):
    try:
        return (
            float(runway["length_ft"])
            * 0.3048
            / 1000.0
        )
    except Exception:
        return 0.0


def airport_runways_for_ident(ident):
    with airport_lock:
        return [
            runway
            for runway in runway_data
            if runway["airport_ident"] == ident
        ]


def draw_runways():
    with airport_lock:
        airports = list(airport_data)
        runways = list(runway_data)

    visible_airports = {
        airport["ident"]
        for airport in airports
        if airport["distance"] <= RADAR_RANGE_KM
    }

    for runway in runways:
        if (
            runway["airport_ident"]
            not in visible_airports
        ):
            continue

        if VIEW_MODE == "RADAR":
            d1 = calculate_distance(
                HOME_LAT,
                HOME_LON,
                runway["le_lat"],
                runway["le_lon"],
            )

            d2 = calculate_distance(
                HOME_LAT,
                HOME_LON,
                runway["he_lat"],
                runway["he_lon"],
            )

            b1 = calculate_bearing(
                HOME_LAT,
                HOME_LON,
                runway["le_lat"],
                runway["le_lon"],
            )

            b2 = calculate_bearing(
                HOME_LAT,
                HOME_LON,
                runway["he_lat"],
                runway["he_lon"],
            )

            x1, y1 = radar_position(
                d1,
                b1,
            )

            x2, y2 = radar_position(
                d2,
                b2,
            )

        else:
            x1, y1 = map_position(
                runway["le_lat"],
                runway["le_lon"],
            )

            x2, y2 = map_position(
                runway["he_lat"],
                runway["he_lon"],
            )

        runway_is_active = (
            runway_key(runway) == runway_key(selected_runway)
            if selected_runway is not None
            else False
        ) or (
            runway_key(runway) == runway_key(hovered_runway)
            if hovered_runway is not None
            else False
        )

        canvas.create_line(
            x1,
            y1,
            x2,
            y2,
            fill=YELLOW if runway_is_active else BLUE_DIM,
            width=5 if runway_is_active else 4,
        )

        canvas.create_line(
            x1,
            y1,
            x2,
            y2,
            fill=YELLOW if runway_is_active else THEME["RUNWAY"],
            width=2 if runway_is_active else 1,
        )

        # Draw runway orientation near the midpoint.
        if (
            runway.get("le_ident")
            and runway.get("he_ident")
        ):
            mx = (x1 + x2) / 2
            my = (y1 + y2) / 2

            label = (
                f"{runway['le_ident']}"
                f"/"
                f"{runway['he_ident']}"
            )

            canvas.create_text(
                mx,
                my - 7,
                text=label,
                fill=TEXT_DIM,
                font=("Consolas", 7, "bold"),
            )


# ============================================================
# 25. AIRPORT MARKERS
# ============================================================

def airport_size(airport_type):
    if airport_type == "large_airport":
        return 7

    if airport_type == "medium_airport":
        return 6

    if airport_type == "small_airport":
        return 4

    return 3


def draw_airports():
    with airport_lock:
        airports = list(airport_data)

    visible = []

    for airport in airports:
        if airport["distance"] > RADAR_RANGE_KM:
            continue

        if VIEW_MODE == "RADAR":
            x, y = radar_position(
                airport["distance"],
                airport["bearing"],
            )
        else:
            x, y = map_position(
                airport["latitude"],
                airport["longitude"],
            )

        size = airport_size(
            airport["type"]
        )

        selected = (
            airport["ident"] == selected_airport
        )

        hovered = (
            airport["ident"] == hovered_airport
        )

        is_home = airport.get(
            "is_home",
            False,
        )

        if is_home:
            color = RED
        elif selected:
            color = YELLOW
        elif hovered:
            color = TEXT
        else:
            color = BLUE

        if is_home:
            canvas.create_rectangle(
                x - size - 5,
                y - size - 5,
                x + size + 5,
                y + size + 5,
                outline=RED,
                width=1,
            )

        if selected:
            canvas.create_oval(
                x - size - 6,
                y - size - 6,
                x + size + 6,
                y + size + 6,
                outline=YELLOW,
                width=2,
            )

        canvas.create_oval(
            x - size,
            y - size,
            x + size,
            y + size,
            fill=color,
            outline=color,
        )

        canvas.create_line(
            x - size - 4,
            y,
            x + size + 4,
            y,
            fill=color,
        )

        canvas.create_line(
            x,
            y - size - 4,
            x,
            y + size + 4,
            fill=color,
        )

        label = (
            airport["iata"]
            or airport["icao"]
            or airport["ident"]
        )

        if is_home:
            label = "BLR  •  VOBL"

        show_label = (
            VIEW_MODE == "MAP"
            and (
                airport["type"]
                in {
                    "large_airport",
                    "medium_airport",
                }
                or is_home
            )
        )

        if show_label or selected or hovered:
            canvas.create_text(
                x + 13,
                y - 15,
                text=label,
                fill=(
                    YELLOW
                    if selected
                    else TEXT
                ),
                anchor="w",
                font=("Arial", 8, "bold"),
            )

        visible.append(airport)

    return visible


# ============================================================
# 26. AIRCRAFT ENTRY/EXIT ANIMATION
# ============================================================

def entry_alpha(icao):
    info = entry_animation.get(icao)

    if not info:
        return 1.0

    elapsed = time.time() - info["started"]
    duration = max(
        info["duration"],
        0.001,
    )

    progress = min(
        elapsed / duration,
        1.0,
    )

    if progress >= 1.0:
        entry_animation.pop(
            icao,
            None,
        )
        return 1.0

    # Smooth ease-out
    return 0.15 + (
        0.85
        * (
            1
            - (1 - progress) ** 3
        )
    )


def draw_exit_echoes():
    now = time.time()

    expired = []

    for icao, item in list(
        recently_removed.items()
    ):
        if now >= item["expires"]:
            expired.append(icao)
            continue

        plane = item["plane"]

        if VIEW_MODE == "RADAR":
            x = plane.get(
                "x",
                plane.get(
                    "target_x",
                    CENTER_X,
                ),
            )
            y = plane.get(
                "y",
                plane.get(
                    "target_y",
                    CENTER_Y,
                ),
            )
        else:
            x, y = map_position(
                plane["latitude"],
                plane["longitude"],
            )

        age = (
            item["expires"] - now
        ) / EXIT_RETENTION_SECONDS

        radius = 8 + (
            16 * (1 - age)
        )

        canvas.create_oval(
            x - radius,
            y - radius,
            x + radius,
            y + radius,
            outline=THEME["RED"],
            width=1,
            dash=(3, 4),
        )

        canvas.create_text(
            x + 14,
            y + 4,
            text=f"{plane['callsign']}  EXIT",
            fill=TEXT_DIM,
            anchor="w",
            font=("Consolas", 7),
        )

    for icao in expired:
        recently_removed.pop(
            icao,
            None,
        )


# ============================================================
# 27. AIRCRAFT ICON
# ============================================================

def draw_aircraft_icon(
    x,
    y,
    heading,
    scale,
    selected=False,
    hovered=False,
    alpha=1.0,
):
    if heading is None:
        heading = 0

    points = [
        (0, -10),
        (3, -1),
        (11, 5),
        (11, 6),
        (3, 5),
        (3, 12),
        (1, 11),
        (-1, 11),
        (-3, 12),
        (-3, 5),
        (-11, 6),
        (-10, 4),
        (-3, -1),
    ]

    angle = math.radians(heading)

    rotated = []

    for px, py in points:
        px *= scale
        py *= scale

        rx = (
            px * math.cos(angle)
            - py * math.sin(angle)
        )

        ry = (
            px * math.sin(angle)
            + py * math.cos(angle)
        )

        rotated.extend(
            [
                x + rx,
                y + ry,
            ]
        )

    if selected:
        color = YELLOW
    elif hovered:
        color = TEXT
    else:
        color = GREEN

    # Simple blinking-like entry effect using outline.
    if alpha < 0.999:
        canvas.create_oval(
            x - 14 * scale * alpha,
            y - 14 * scale * alpha,
            x + 14 * scale * alpha,
            y + 14 * scale * alpha,
            outline=GREEN_DIM,
            width=1,
        )

    canvas.create_polygon(
        rotated,
        fill=color,
        outline=color,
    )


def draw_aircraft_track(icao):
    """Draw the recent path of one aircraft from aircraft_history."""

    if not TRACK_HISTORY_ENABLED:
        return

    if not should_draw_track(icao):
        return

    history = list(aircraft_history.get(icao, []))

    if len(history) < 2:
        return

    history = history[-TRACK_DRAW_POINTS:]
    points = []

    previous_x = None
    previous_y = None

    for point in history:
        latitude = point.get("latitude")
        longitude = point.get("longitude")

        if latitude is None or longitude is None:
            continue

        if VIEW_MODE == "RADAR":
            distance = point.get("distance")
            bearing = point.get("bearing")

            if distance is None or bearing is None:
                continue

            x, y = radar_position(
                distance,
                bearing,
            )
        else:
            x, y = map_position(
                latitude,
                longitude,
            )

        if previous_x is not None:
            jump = math.hypot(
                x - previous_x,
                y - previous_y,
            )

            if jump > TRACK_MAX_SCREEN_JUMP:
                # Break the line across an implausibly large jump.
                previous_x = x
                previous_y = y
                continue

        points.append((x, y))
        previous_x = x
        previous_y = y

    if len(points) < 2:
        return

    track_color = (
        YELLOW
        if icao == selected_aircraft
        else GREEN_DIM
    )

    # Draw the history first so the aircraft symbol remains on top.
    total = len(points) - 1

    for index in range(total):
        x1, y1 = points[index]
        x2, y2 = points[index + 1]

        recency = (index + 1) / total
        width = 2 if recency > 0.70 else 1

        canvas.create_line(
            x1,
            y1,
            x2,
            y2,
            fill=track_color,
            width=width,
            dash=(3, 5),
        )

    # Small dots make the individual historical observations visible.
    for index, (x, y) in enumerate(points[:-1]):
        recency = (index + 1) / max(len(points), 1)
        radius = 1.5 + 1.2 * recency

        canvas.create_oval(
            x - radius,
            y - radius,
            x + radius,
            y + radius,
            fill=track_color,
            outline="",
        )


def map_aircraft_radius(icao):
    """Return MAP dot radius based on aircraft size."""

    with metadata_lock:
        metadata = aircraft_metadata.get(
            icao,
            {},
        )

    size = metadata.get(
        "size",
        "medium",
    )

    if size == "very_large":
        return 12

    if size == "large":
        return 9

    if size == "small":
        return 4

    return 7


def draw_map_aircraft_dots():
    """Draw aircraft as geographic dots in MAP mode."""

    with data_lock:
        planes = list(
            aircraft_data.values()
        )

    visible_count = 0

    for plane in planes:
        if not altitude_allowed(
            plane.get("altitude")
        ):
            continue

        if not aircraft_passes_operation_filters(plane):
            continue

        latitude = plane.get("latitude")
        longitude = plane.get("longitude")

        if latitude is None or longitude is None:
            continue

        x, y = map_position(
            latitude,
            longitude,
        )

        if math.hypot(
            x - CENTER_X,
            y - CENTER_Y,
        ) > RADAR_RADIUS:
            continue

        icao = plane["icao"]

        selected = (
            icao == selected_aircraft
        )

        hovered = (
            icao == hovered_aircraft
        )

        radius = map_aircraft_radius(
            icao
        )

        if selected:
            radius += 3
            dot_color = YELLOW
        elif hovered:
            dot_color = TEXT
        else:
            dot_color = GREEN

        # Direction indicator stays subtle in MAP mode.
        heading = plane.get("heading")
        if heading is not None:
            angle = math.radians(
                heading
            )

            direction_length = radius + 8

            canvas.create_line(
                x,
                y,
                x + direction_length * math.sin(angle),
                y - direction_length * math.cos(angle),
                fill=GREEN_DIM,
                width=1,
            )

        # Outer ring.
        canvas.create_oval(
            x - radius - 2,
            y - radius - 2,
            x + radius + 2,
            y + radius + 2,
            outline=GREEN_DIM,
            width=1,
        )

        # Main geographic dot.
        canvas.create_oval(
            x - radius,
            y - radius,
            x + radius,
            y + radius,
            fill=dot_color,
            outline=dot_color,
        )

        if selected or hovered:
            canvas.create_text(
                x + radius + 7,
                y,
                text=plane.get(
                    "callsign",
                    "UNKNOWN",
                ),
                fill=(
                    YELLOW
                    if selected
                    else TEXT
                ),
                anchor="w",
                font=(
                    "Consolas",
                    8,
                    "bold",
                ),
            )

        visible_count += 1

    return visible_count


def draw_aircraft():
    # MAP mode uses geographic dots rather than silhouettes.
    if VIEW_MODE == "MAP":
        return draw_map_aircraft_dots()

    with data_lock:
        planes = list(
            aircraft_data.values()
        )

    visible_count = 0

    for plane in planes:
        if not altitude_allowed(
            plane["altitude"]
        ):
            continue

        if not aircraft_passes_operation_filters(plane):
            continue

        visible_count += 1

        icao = plane["icao"]

        selected = (
            icao == selected_aircraft
        )

        hovered = (
            icao == hovered_aircraft
        )

        scale = get_marker_scale(
            icao
        )

        alpha = entry_alpha(
            icao
        )

        if VIEW_MODE == "RADAR":
            x = plane["x"]
            y = plane["y"]
        else:
            x, y = map_position(
                plane["latitude"],
                plane["longitude"],
            )

        if plane["heading"] is not None:
            angle = math.radians(
                plane["heading"]
            )

            length = 20 * scale

            hx = (
                x
                + length
                * math.sin(angle)
            )

            hy = (
                y
                - length
                * math.cos(angle)
            )

            canvas.create_line(
                x,
                y,
                hx,
                hy,
                fill=(
                    YELLOW
                    if selected
                    else GREEN_DIM
                ),
                width=1,
            )

        # Phase 5.2: render track history behind the aircraft symbol.
        draw_aircraft_track(icao)

        draw_aircraft_icon(
            x,
            y,
            plane["heading"],
            scale,
            selected,
            hovered,
            alpha,
        )

        # Pulse ring for a newly entered aircraft.
        if alpha < 0.999:
            pulse = (
                28
                - 16 * alpha
            )

            canvas.create_oval(
                x - pulse,
                y - pulse,
                x + pulse,
                y + pulse,
                outline=GREEN_DIM,
                width=1,
                dash=(2, 4),
            )

        if selected or hovered:
            with metadata_lock:
                metadata = aircraft_metadata.get(
                    icao,
                    {},
                )

            typecode = (
                metadata.get("typecode")
                or ""
            )

            label = plane["callsign"]

            if typecode:
                label += (
                    f" • {typecode}"
                )

            status = plane.get(
                "flight_status",
                "",
            )

            airport_behavior = plane.get(
                "airport_behavior",
                "",
            )

            if status:
                label += f"\n{status}"

            if (
                airport_behavior
                and airport_behavior not in {
                    "",
                    "AIRSPACE TRANSIT",
                    "UNKNOWN",
                }
            ):
                label += (
                    f"\n{airport_behavior}"
                )

            canvas.create_text(
                x + 18 * scale,
                y - 14 * scale,
                text=label,
                fill=(
                    YELLOW
                    if selected
                    else TEXT
                ),
                anchor="w",
                font=("Consolas", 8, "bold"),
            )

            track_points = len(
                aircraft_history.get(icao, [])
            )

            if track_points >= 2:
                canvas.create_text(
                    x + 18 * scale,
                    y + 12 * scale,
                    text=f"TRACK {track_points}",
                    fill=TEXT_DIM,
                    anchor="w",
                    font=("Consolas", 7),
                )

    return visible_count


# ============================================================
# 28. HIT TESTING
# ============================================================

def runway_key(runway):
    return (
        runway.get("airport_ident"),
        runway.get("le_ident"),
        runway.get("he_ident"),
    )


def find_aircraft_at(mx, my):
    nearest = None
    nearest_distance = float("inf")

    with data_lock:
        planes = list(
            aircraft_data.values()
        )

    for plane in planes:
        if not altitude_allowed(
            plane["altitude"]
        ):
            continue

        if not aircraft_passes_operation_filters(plane):
            continue

        if VIEW_MODE == "RADAR":
            x = plane["x"]
            y = plane["y"]
        else:
            x, y = map_position(
                plane["latitude"],
                plane["longitude"],
            )

        distance = math.hypot(
            x - mx,
            y - my,
        )

        scale = get_marker_scale(
            plane["icao"]
        )

        click_radius = max(
            24,
            24 * scale,
        )

        if distance <= click_radius:
            if distance < nearest_distance:
                nearest = plane["icao"]
                nearest_distance = distance

    return nearest


def find_airport_at(mx, my):
    nearest = None
    nearest_distance = float("inf")

    with airport_lock:
        airports = list(airport_data)

    for airport in airports:
        if airport["distance"] > RADAR_RANGE_KM:
            continue

        if VIEW_MODE == "RADAR":
            x, y = radar_position(
                airport["distance"],
                airport["bearing"],
            )
        else:
            x, y = map_position(
                airport["latitude"],
                airport["longitude"],
            )

        distance = math.hypot(
            x - mx,
            y - my,
        )

        if distance <= 16:
            if distance < nearest_distance:
                nearest = airport["ident"]
                nearest_distance = distance

    return nearest


def find_runway_at(mx, my):
    """Find the closest visible runway line to the mouse."""

    nearest = None
    nearest_distance = float("inf")

    with airport_lock:
        airports = list(airport_data)
        runways = list(runway_data)

    airport_lookup = {
        airport["ident"]: airport
        for airport in airports
    }

    for runway in runways:

        airport_ident = runway.get(
            "airport_ident"
        )

        airport = airport_lookup.get(
            airport_ident
        )

        if airport is None:
            continue

        if airport.get("distance", float("inf")) > RADAR_RANGE_KM:
            continue

        if VIEW_MODE == "RADAR":

            d1 = calculate_distance(
                HOME_LAT,
                HOME_LON,
                runway["le_lat"],
                runway["le_lon"],
            )

            d2 = calculate_distance(
                HOME_LAT,
                HOME_LON,
                runway["he_lat"],
                runway["he_lon"],
            )

            b1 = calculate_bearing(
                HOME_LAT,
                HOME_LON,
                runway["le_lat"],
                runway["le_lon"],
            )

            b2 = calculate_bearing(
                HOME_LAT,
                HOME_LON,
                runway["he_lat"],
                runway["he_lon"],
            )

            x1, y1 = radar_position(
                d1,
                b1,
            )

            x2, y2 = radar_position(
                d2,
                b2,
            )

        else:

            x1, y1 = map_position(
                runway["le_lat"],
                runway["le_lon"],
            )

            x2, y2 = map_position(
                runway["he_lat"],
                runway["he_lon"],
            )

        line_dx = x2 - x1
        line_dy = y2 - y1
        line_length_sq = (
            line_dx * line_dx
            + line_dy * line_dy
        )

        if line_length_sq <= 0:
            continue

        t = (
            (mx - x1) * line_dx
            + (my - y1) * line_dy
        ) / line_length_sq

        t = max(
            0.0,
            min(1.0, t),
        )

        closest_x = (
            x1 + t * line_dx
        )

        closest_y = (
            y1 + t * line_dy
        )

        distance = math.hypot(
            mx - closest_x,
            my - closest_y,
        )

        # Slightly generous click area because the visible runway
        # is intentionally thin like a real instrument.
        if distance <= 12:
            if distance < nearest_distance:
                nearest = runway
                nearest_distance = distance

    return nearest


def show_runway_info(runway, temporary=False):
    """Display detailed runway information in the right panel."""

    if runway is None:
        return

    airport_ident = runway.get(
        "airport_ident",
        "UNKNOWN",
    )

    with airport_lock:
        airport = next(
            (
                item
                for item in airport_data
                if item.get("ident") == airport_ident
            ),
            None,
        )

    if airport is None:
        return

    orientation = runway_bearing(
        runway
    )

    length_km = runway_length_km(
        runway
    )

    length = runway.get(
        "length_ft"
    ) or "Unknown"

    width = runway.get(
        "width_ft"
    ) or "Unknown"

    surface = runway.get(
        "surface"
    ) or "Unknown"

    text = (
        "● HOVER\n\n"
        if temporary
        else
        "● LOCKED\n\n"
    )

    text += (
        f"RUNWAY\n"
        f"{runway.get('le_ident', '?')}"
        f"/{runway.get('he_ident', '?')}\n\n"
        f"AIRPORT\n"
        f"{airport['name']}\n\n"
        f"IATA       {airport.get('iata') or '—'}\n"
        f"ICAO       {airport.get('icao') or airport_ident}\n\n"
        f"ORIENTATION\n"
        f"{orientation:.1f}° "
        f"{cardinal_direction(orientation)}\n\n"
        f"LENGTH\n"
        f"{length} ft "
        f"({length_km:.2f} km)\n\n"
        f"WIDTH\n"
        f"{width} ft\n\n"
        f"SURFACE\n"
        f"{surface}\n"
    )

    set_info(
        text,
        YELLOW if not temporary else TEXT,
        preserve_scroll=temporary,
    )


# ============================================================
# 29. INFORMATION PANEL
# ============================================================

def show_airport_info(
    ident,
    temporary=False,
):
    with airport_lock:
        airport = None

        for item in airport_data:
            if item["ident"] == ident:
                airport = item
                break

        airport_runways = [
            runway
            for runway in runway_data
            if runway["airport_ident"] == ident
        ]

    if airport is None:
        return

    iata = (
        airport["iata"]
        or "—"
    )

    icao = (
        airport["icao"]
        or airport["ident"]
        or "—"
    )

    elevation = (
        airport["elevation"]
        or "Unknown"
    )

    airport_type = (
        airport["type"]
        .replace("_", " ")
        .title()
    )

    text = (
        "● HOVER\n\n"
        if temporary
        else
        "● LOCKED\n\n"
    )

    if airport.get("is_home"):
        text += (
            "RADAR ORIGIN\n"
            f"{HOME_NAME}\n\n"
        )

    text += (
        f"{airport['name']}\n\n"
        f"IATA       {iata}\n"
        f"ICAO       {icao}\n"
        f"TYPE       {airport_type}\n\n"
        f"LOCATION\n"
        f"{airport['municipality']}\n"
        f"{airport['country']}\n\n"
        f"ELEVATION\n"
        f"{elevation} ft\n\n"
        f"DISTANCE\n"
        f"{airport['distance']:.2f} km\n\n"
        f"BEARING\n"
        f"{airport['bearing']:.1f}° "
        f"{cardinal_direction(airport['bearing'])}\n\n"
        f"RUNWAYS\n"
    )

    if not airport_runways:
        text += "No runway information"

    else:
        for runway in airport_runways[:8]:
            length = (
                runway["length_ft"]
                or "?"
            )

            width = (
                runway["width_ft"]
                or "?"
            )

            surface = (
                runway["surface"]
                or "?"
            )

            orientation = runway_bearing(
                runway
            )

            length_km = runway_length_km(
                runway
            )

            text += (
                f"{runway['le_ident']}/"
                f"{runway['he_ident']}\n"
                f"Orientation: "
                f"{orientation:.1f}°\n"
                f"Length: {length} ft"
                f" ({length_km:.2f} km)\n"
                f"Width: {width} ft\n"
                f"Surface: {surface}\n\n"
            )

    set_info(
        text,
        YELLOW if not temporary else TEXT,
        preserve_scroll=temporary,
    )


def show_aircraft_info(
    icao,
    temporary=False,
):
    with data_lock:
        plane = aircraft_data.get(
            icao
        )

    if not plane:
        return

    with metadata_lock:
        metadata = aircraft_metadata.get(
            icao,
            {},
        )

    typecode = (
        metadata.get("typecode")
        or "UNKNOWN"
    )

    model = (
        metadata.get("model")
        or "Unknown"
    )

    manufacturer = (
        metadata.get("manufacturer")
        or "Unknown"
    )

    operator_icao = (
        metadata.get("operator_icao")
        or "Unknown"
    )

    operator_iata = (
        metadata.get("operator_iata")
        or "Unknown"
    )

    owner = (
        metadata.get("owner")
        or "Unknown"
    )

    serial_number = (
        metadata.get("serial_number")
        or "Unknown"
    )

    built = (
        metadata.get("built")
        or "Unknown"
    )

    altitude = plane["altitude"]

    if altitude is not None:
        altitude_text = (
            f"{altitude * 3.28084:,.0f} ft"
        )
    else:
        altitude_text = "UNKNOWN"

    speed = plane["speed"]

    if speed is not None:
        speed_text = (
            f"{speed * 1.94384:.0f} kt"
        )
    else:
        speed_text = "UNKNOWN"

    heading = plane["heading"]

    if heading is not None:
        heading_text = (
            f"{heading:.1f}° "
            f"{cardinal_direction(heading)}"
        )
    else:
        heading_text = "UNKNOWN"

    alert = aircraft_alert_status(plane)

    text = (
        "● HOVER\n\n"
        if temporary
        else
        "● LOCKED\n\n"
    )

    if alert:
        text += f"⚠ {alert}\n\n"

    flight_status = plane.get(
        "flight_status",
        "TRACKING",
    )

    vertical_status = plane.get(
        "vertical_status",
        "UNKNOWN",
    )

    distance_status = plane.get(
        "distance_status",
        "UNKNOWN",
    )

    track_points = len(aircraft_history.get(icao, []))

    weather = plane.get("weather", {})
    aircraft_aqi = weather.get("aqi")
    aircraft_pm25 = weather.get("pm2_5")
    aircraft_pm10 = weather.get("pm10")
    aircraft_turbulence = weather.get("turbulence_level", "UNKNOWN")

    aircraft_aqi_text = (
        f"{aircraft_aqi:.0f}"
        if isinstance(aircraft_aqi, (int, float))
        else "UNKNOWN"
    )
    aircraft_pm25_text = (
        f"{aircraft_pm25:.1f}"
        if isinstance(aircraft_pm25, (int, float))
        else "UNKNOWN"
    )
    aircraft_pm10_text = (
        f"{aircraft_pm10:.1f}"
        if isinstance(aircraft_pm10, (int, float))
        else "UNKNOWN"
    )

    airport_behavior = plane.get(
        "airport_behavior",
        "UNKNOWN",
    )

    nearest_airport_ident = plane.get(
        "nearest_airport_ident",
        "UNKNOWN",
    )

    nearest_airport_name = plane.get(
        "nearest_airport_name",
        "UNKNOWN",
    )

    nearest_airport_distance = plane.get(
        "nearest_airport_distance"
    )

    aligned_runway = plane.get(
        "aligned_runway",
        "NONE",
    )

    if nearest_airport_distance is not None:
        nearest_airport_text = (
            f"{nearest_airport_ident}  "
            f"({nearest_airport_distance:.1f} km)"
        )
    else:
        nearest_airport_text = "UNKNOWN"

    text += (
        f"{plane['callsign']}\n\n"
        f"ICAO24\n"
        f"{plane['icao']}\n\n"
        f"REGISTRATION\n"
        f"{plane.get('registration') or 'UNKNOWN'}\n\n"
        f"AIRCRAFT\n"
        f"{model}\n\n"
        f"TYPE\n"
        f"{typecode}\n\n"
        f"MANUFACTURER\n"
        f"{manufacturer}\n\n"
        f"OPERATOR ICAO\n"
        f"{operator_icao}\n\n"
        f"OPERATOR IATA\n"
        f"{operator_iata}\n\n"
        f"OWNER\n"
        f"{owner}\n\n"
        f"SERIAL\n"
        f"{serial_number}\n\n"
        f"BUILT\n"
        f"{built}\n\n"
        f"ALTITUDE\n"
        f"{altitude_text}\n\n"
        f"SPEED\n"
        f"{speed_text}\n\n"
        f"HEADING\n"
        f"{heading_text}\n\n"
        f"DISTANCE\n"
        f"{plane['distance']:.2f} km\n\n"
        f"BEARING\n"
        f"{plane['bearing']:.1f}° "
        f"{cardinal_direction(plane['bearing'])}\n\n"
        f"STATUS\n"
        f"{flight_status}\n\n"
        f"VERTICAL TREND\n"
        f"{vertical_status}\n\n"
        f"RANGE TREND\n"
        f"{distance_status}\n\n"
        f"FLIGHT BEHAVIOR\n"
        f"{airport_behavior}\n\n"
        f"NEAREST AIRPORT\n"
        f"{nearest_airport_text}\n\n"
        f"RUNWAY ALIGNMENT\n"
        f"{aligned_runway}\n\n"
        f"AIRSPACE WEATHER\n"
        f"TURBULENCE POTENTIAL\n"
        f"{aircraft_turbulence}\n\n"
        f"AIR QUALITY\n"
        f"AQI        {aircraft_aqi_text}\n"
        f"PM2.5      {aircraft_pm25_text}\n"
        f"PM10       {aircraft_pm10_text}\n\n"
        f"TRACK HISTORY\n"
        f"{track_points} POINTS"
    )

    set_info(
        text,
        YELLOW if not temporary else TEXT,
        preserve_scroll=temporary,
    )


# ============================================================
# 30. MOUSE
# ============================================================

def on_mouse_move(event):
    global hovered_aircraft
    global hovered_airport
    global hovered_runway

    aircraft = find_aircraft_at(
        event.x,
        event.y,
    )

    # Runways are tested before airports so a click/hover on the
    # runway surface doesn't get swallowed by the airport marker.
    runway = find_runway_at(
        event.x,
        event.y,
    )

    airport = find_airport_at(
        event.x,
        event.y,
    )

    hovered_aircraft = aircraft

    hovered_runway = (
        None
        if aircraft
        else runway
    )

    hovered_airport = (
        None
        if aircraft or runway
        else airport
    )

    if aircraft:

        show_aircraft_info(
            aircraft,
            temporary=True,
        )

    elif runway:

        show_runway_info(
            runway,
            temporary=True,
        )

    elif airport:

        show_airport_info(
            airport,
            temporary=True,
        )

    elif selected_aircraft:

        show_aircraft_info(
            selected_aircraft
        )

    elif selected_runway:

        show_runway_info(
            selected_runway
        )

    elif selected_airport:

        show_airport_info(
            selected_airport
        )

    else:

        set_info(
            "HOVER OVER AN AIRCRAFT, AIRPORT OR RUNWAY.\n\n"
            "CLICK TO LOCK INFORMATION.\n\n"
            f"{HOME_IATA} / {HOME_ICAO} IS THE RADAR ORIGIN.",
            TEXT_DIM,
        )


def on_click(event):
    global selected_aircraft
    global selected_airport
    global selected_runway

    aircraft = find_aircraft_at(
        event.x,
        event.y,
    )

    runway = find_runway_at(
        event.x,
        event.y,
    )

    airport = find_airport_at(
        event.x,
        event.y,
    )

    # --------------------------------------------------------
    # AIRCRAFT
    # --------------------------------------------------------

    if aircraft:

        selected_aircraft = aircraft
        selected_airport = None
        selected_runway = None

        show_aircraft_info(
            aircraft,
            temporary=False,
        )

        return

    # --------------------------------------------------------
    # RUNWAY
    # --------------------------------------------------------

    if runway:

        selected_aircraft = None
        selected_airport = None
        selected_runway = runway

        show_runway_info(
            runway,
            temporary=False,
        )

        return

    # --------------------------------------------------------
    # AIRPORT
    # --------------------------------------------------------

    if airport:

        selected_aircraft = None
        selected_airport = airport
        selected_runway = None

        show_airport_info(
            airport,
            temporary=False,
        )

        return

    # --------------------------------------------------------
    # CLEAR
    # --------------------------------------------------------

    selected_aircraft = None
    selected_airport = None
    selected_runway = None

    set_info(
        "HOVER OVER AN AIRCRAFT, AIRPORT OR RUNWAY.\n\n"
        "CLICK TO LOCK INFORMATION.\n\n"
        f"{HOME_IATA} / {HOME_ICAO} IS THE RADAR ORIGIN.",
        TEXT_DIM,
        preserve_scroll=False,
    )


canvas.bind(
    "<Motion>",
    on_mouse_move,
)

canvas.bind(
    "<Button-1>",
    on_click,
)


# ============================================================
# 31. RADAR SWEEP
# ============================================================

def draw_sweep():
    global sweep_angle

    if VIEW_MODE != "RADAR":
        return

    angle = math.radians(
        sweep_angle
    )

    end_x = (
        CENTER_X
        + RADAR_RADIUS
        * math.sin(angle)
    )

    end_y = (
        CENTER_Y
        - RADAR_RADIUS
        * math.cos(angle)
    )

    canvas.create_line(
        CENTER_X,
        CENTER_Y,
        end_x,
        end_y,
        fill=GREEN_DIM,
        width=2,
    )

    sweep_angle += 4

    if sweep_angle >= 360:
        sweep_angle = 0


# ============================================================
# 32. LIVE CLOCK / CONNECTION STATUS
# ============================================================

def update_status_widgets():
    global connection_ok

    now = time.time()

    if last_update_time > 0:
        age = now - last_update_time
    else:
        age = None

    # Status quality is determined separately from mere internet access.
    if last_update_time <= 0:
        status_text = "CONNECTING"
        status_color = YELLOW
    elif api_status.startswith("RATE LIMITED"):
        status_text = "LIMITED"
        status_color = YELLOW
    elif age is not None and age <= AIRCRAFT_UPDATE_INTERVAL * 2.5:
        status_text = "LIVE"
        status_color = GREEN
    elif age is not None and age <= AIRCRAFT_UPDATE_INTERVAL * 4:
        status_text = "STALE"
        status_color = YELLOW
    else:
        status_text = "OFFLINE"
        status_color = RED

    header_status.config(
        text=f"● {status_text}",
        fg=status_color,
        bg=PANEL,
    )

    footer_left.config(
        text=f"● {status_text}",
        fg=status_color,
        bg=PANEL,
    )

    connection_value.config(
        text=status_text,
        fg=status_color,
        bg=PANEL,
    )

    update_text = (
        "—"
        if age is None
        else format_hms(age)
    )

    source = (
        api_status
        if api_status
        else "NO STATUS"
    )

    footer_right.config(
        text=(
            f"UPDATE {update_text}"
            f"   •   {VIEW_MODE}"
            f"   •   {RADAR_RANGE_KM} KM"
            f"   •   {source}"
        ),
        fg=TEXT_DIM,
        bg=PANEL,
    )


# ============================================================
# 33. ANIMATION / RENDER LOOP
# ============================================================

def animate():
    # Smooth aircraft movement
    with data_lock:
        for plane in aircraft_data.values():
            plane["x"] += (
                plane["target_x"]
                - plane["x"]
            ) * 0.08

            plane["y"] += (
                plane["target_y"]
                - plane["y"]
            ) * 0.08

    canvas.delete("all")

    if VIEW_MODE == "RADAR":
        draw_radar_background()

        draw_runways()
        airports_visible = draw_airports()
        aircraft_visible = draw_aircraft()

    else:
        draw_map_background()

        # Clean geographic MAP. Weather is intentionally not painted
        # over the map; it is available in aircraft intelligence.
        draw_runways()
        airports_visible = draw_airports()
        aircraft_visible = draw_aircraft()

    draw_exit_echoes()
    draw_sweep()

    count_value.config(
        text=str(
            aircraft_visible
        )
    )

    airport_count_value.config(
        text=str(
            len(airports_visible)
        )
    )

    update_status_widgets()

    # Selected aircraft/airport can disappear from live feed.
    global selected_aircraft
    global selected_airport

    with data_lock:
        selected_exists = (
            selected_aircraft in aircraft_data
            if selected_aircraft
            else False
        )

    with airport_lock:
        selected_airport_exists = any(
            airport["ident"]
            == selected_airport
            for airport in airport_data
        )

    if (
        selected_aircraft
        and not selected_exists
    ):
        selected_aircraft = None

    if (
        selected_airport
        and not selected_airport_exists
    ):
        selected_airport = None

    root.after(
        ANIMATION_INTERVAL,
        animate,
    )


# ============================================================
# SAFE WINDOW CLOSE
# ============================================================

def close_application():
    root.destroy()


root.protocol("WM_DELETE_WINDOW", close_application)


# ============================================================
# 34. START THREADS
# ============================================================

threading.Thread(
    target=api_loop,
    daemon=True,
).start()

threading.Thread(
    target=metadata_loop,
    daemon=True,
).start()

threading.Thread(
    target=weather_loop,
    daemon=True,
).start()

threading.Thread(
    target=airport_database_loop,
    daemon=True,
).start()


# ============================================================
# 35. START
# ============================================================

set_view("RADAR")
animate()
root.mainloop()
