import requests
import math

# =========================
# YOUR RADAR CENTER
# =========================

HOME_LAT = 12.9716
HOME_LON = 77.5946

# Search area around Bengaluru
URL = "https://opensky-network.org/api/states/all"

params = {
    "lamin": 12.50,
    "lamax": 13.45,
    "lomin": 77.10,
    "lomax": 78.10
}


# =========================
# DISTANCE CALCULATION
# =========================

def calculate_distance(lat1, lon1, lat2, lon2):

    R = 6371.0  # Earth radius in km

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

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


# =========================
# BEARING CALCULATION
# =========================

def calculate_bearing(lat1, lon1, lat2, lon2):

    lat1 = math.radians(lat1)
    lat2 = math.radians(lat2)

    dlon = math.radians(lon2 - lon1)

    x = math.sin(dlon) * math.cos(lat2)

    y = (
        math.cos(lat1) * math.sin(lat2)
        - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    )

    bearing = math.degrees(math.atan2(x, y))

    return (bearing + 360) % 360


# =========================
# GET LIVE AIRCRAFT
# =========================

response = requests.get(URL, params=params)

print("HTTP status:", response.status_code)

data = response.json()

if data["states"] is None:

    print("No aircraft currently available.")

else:

    print("\nAircraft detected:", len(data["states"]))
    print("=" * 70)

    for plane in data["states"]:

        callsign = plane[1].strip() if plane[1] else "UNKNOWN"

        longitude = plane[5]
        latitude = plane[6]

        altitude = plane[7]
        speed = plane[9]
        heading = plane[10]

        # Skip aircraft with no position
        if latitude is None or longitude is None:
            continue

        distance = calculate_distance(
            HOME_LAT,
            HOME_LON,
            latitude,
            longitude
        )

        bearing = calculate_bearing(
            HOME_LAT,
            HOME_LON,
            latitude,
            longitude
        )

        print(f"""
Callsign : {callsign}
Position : {latitude:.4f}, {longitude:.4f}
Distance : {distance:.2f} km
Bearing  : {bearing:.1f}°
Altitude : {altitude} m
Speed    : {speed} m/s
Heading  : {heading}°
----------------------------------------
""")