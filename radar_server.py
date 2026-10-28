from flask import Flask, request, jsonify, render_template_string
import math, time, threading, requests, csv, io
import os

app = Flask(__name__)

# ============================================================
# AIRSPACE RADAR — BROWSER GPS VERSION
# Each browser supplies its own GPS coordinates.
# ============================================================

RADAR_RANGE_KM = 50
AIRCRAFT_UPDATE_SECONDS = 15
AIRPORT_REFRESH_SECONDS = 3600

ADSBLOL_URL = "https://api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/{dist}"
AIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
RUNWAYS_URL = "https://davidmegginson.github.io/ourairports-data/runways.csv"

http = requests.Session()
http.headers.update({"User-Agent": "AirspaceRadar/3.0"})

airport_data = []
runway_data = []
airport_lock = threading.Lock()


def calculate_distance(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def calculate_bearing(lat1, lon1, lat2, lon2):
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def cardinal_direction(degrees):
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return dirs[int((degrees + 22.5) // 45) % 8]


def load_airports():
    global airport_data, runway_data
    try:
        a = http.get(AIRPORTS_URL, timeout=30)
        a.raise_for_status()
        r = http.get(RUNWAYS_URL, timeout=30)
        r.raise_for_status()

        airports = []
        for row in csv.DictReader(io.StringIO(a.text)):
            try:
                lat = float(row["latitude_deg"])
                lon = float(row["longitude_deg"])
            except Exception:
                continue
            if row.get("closed", "0") == "1":
                continue
            if row.get("type") not in {"large_airport", "medium_airport", "small_airport", "heliport", "seaplane_base"}:
                continue
            airports.append({
                "ident": row.get("ident", ""),
                "name": row.get("name", "Unknown Airport"),
                "type": row.get("type", ""),
                "latitude": lat,
                "longitude": lon,
                "iata": row.get("iata_code", ""),
                "icao": row.get("gps_code", ""),
                "elevation": row.get("elevation_ft", ""),
            })

        runways = []
        for row in csv.DictReader(io.StringIO(r.text)):
            try:
                le_lat = float(row["le_latitude_deg"])
                le_lon = float(row["le_longitude_deg"])
                he_lat = float(row["he_latitude_deg"])
                he_lon = float(row["he_longitude_deg"])
            except Exception:
                continue
            runways.append({
                "airport_ident": row.get("airport_ident", ""),
                "le_ident": row.get("le_ident", ""),
                "he_ident": row.get("he_ident", ""),
                "le_lat": le_lat, "le_lon": le_lon,
                "he_lat": he_lat, "he_lon": he_lon,
                "length_ft": row.get("length_ft", ""),
            })

        with airport_lock:
            airport_data = airports
            runway_data = runways
        print(f"Loaded {len(airports)} airports and {len(runways)} runways")
    except Exception as e:
        print("Airport database error:", e)


def airport_loop():
    while True:
        load_airports()
        time.sleep(AIRPORT_REFRESH_SECONDS)


def parse_aircraft(lat, lon, data):
    aircraft = []
    states = data.get("ac") if isinstance(data, dict) else []
    if states is None:
        states = data.get("aircraft", []) if isinstance(data, dict) else []

    for plane in states or []:
        try:
            plat = plane.get("lat")
            plon = plane.get("lon")
            if plat is None or plon is None:
                continue
            plat, plon = float(plat), float(plon)
            distance = calculate_distance(lat, lon, plat, plon)
            if distance > RADAR_RANGE_KM:
                continue

            raw_alt = plane.get("alt_baro", plane.get("alt_geom"))
            altitude_m = float(raw_alt) * 0.3048 if isinstance(raw_alt, (int, float)) else None
            raw_speed = plane.get("gs")
            speed_kmh = float(raw_speed) * 1.852 if isinstance(raw_speed, (int, float)) else None
            heading = plane.get("track", plane.get("nav_heading"))
            heading = float(heading) if isinstance(heading, (int, float)) else None
            icao = str(plane.get("hex") or plane.get("icao") or "").strip().lower()
            if not icao:
                continue

            aircraft.append({
                "icao": icao,
                "callsign": str(plane.get("flight") or plane.get("callsign") or plane.get("r") or "UNKNOWN").strip(),
                "registration": str(plane.get("r") or "").strip(),
                "latitude": plat,
                "longitude": plon,
                "distance": round(distance, 2),
                "bearing": round(calculate_bearing(lat, lon, plat, plon), 1),
                "direction": cardinal_direction(calculate_bearing(lat, lon, plat, plon)),
                "heading": round(heading, 1) if heading is not None else None,
                "altitude_m": round(altitude_m) if altitude_m is not None else None,
                "altitude_ft": round(altitude_m / 0.3048) if altitude_m is not None else None,
                "speed_kmh": round(speed_kmh) if speed_kmh is not None else None,
                "typecode": str(plane.get("t") or plane.get("type") or "").strip().upper(),
            })
        except Exception:
            continue
    return aircraft


def get_aircraft(lat, lon):
    dist_nm = max(1, math.ceil(RADAR_RANGE_KM * 0.539956803))
    url = ADSBLOL_URL.format(lat=lat, lon=lon, dist=dist_nm)
    response = http.get(url, timeout=15)
    response.raise_for_status()
    return parse_aircraft(lat, lon, response.json())


@app.get("/")
def index():
    return render_template_string(HTML)


@app.post("/api/location")
def location():
    data = request.get_json(silent=True) or {}
    try:
        lat = float(data["latitude"])
        lon = float(data["longitude"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError
    except Exception:
        return jsonify({"success": False, "error": "Invalid GPS coordinates"}), 400
    return jsonify({"success": True, "latitude": lat, "longitude": lon})


@app.get("/api/radar")
def radar():
    try:
        lat = float(request.args["lat"])
        lon = float(request.args["lon"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError
    except Exception:
        return jsonify({"success": False, "error": "GPS coordinates required"}), 400

    try:
        aircraft = get_aircraft(lat, lon)
        status = "LIVE • ADSB.LOL"
    except Exception as e:
        aircraft = []
        status = "AIRCRAFT API ERROR"
        print("Aircraft API error:", e)

    with airport_lock:
        nearby = []
        for a in airport_data:
            d = calculate_distance(lat, lon, a["latitude"], a["longitude"])
            if d <= RADAR_RANGE_KM:
                b = calculate_bearing(lat, lon, a["latitude"], a["longitude"])
                nearby.append({**a, "distance": round(d, 2), "bearing": round(b, 1), "direction": cardinal_direction(b)})

    return jsonify({
        "success": True,
        "origin": {"latitude": lat, "longitude": lon},
        "range_km": RADAR_RANGE_KM,
        "aircraft": aircraft,
        "airports": nearby,
        "status": status,
        "timestamp": time.time(),
    })


HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Airspace Radar</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#080b0d;color:#e7f1f3;font-family:Arial,sans-serif;overflow:hidden}
.app{height:100vh;display:flex}.scope-wrap{flex:1;position:relative;background:#07100d}.scope{width:100%;height:100%;display:block}
.panel{width:350px;background:#101518;border-left:1px solid #1d2c31;padding:18px;overflow:auto}.title{font-size:18px;font-weight:700;letter-spacing:.8px}.sub{font:11px Consolas,monospace;color:#829398;margin-top:5px}
.row{display:flex;justify-content:space-between;margin:10px 0;padding:10px;background:#141c20;border:1px solid #203036}.label{color:#829398;font-size:11px}.value{font:12px Consolas,monospace}.green{color:#39ff88}.yellow{color:#ffd84d}.red{color:#ff4d5a}
button{width:100%;padding:12px;background:#0b6b3c;border:1px solid #39ff88;color:#fff;font-weight:700;cursor:pointer;margin:10px 0}button:hover{background:#13804b}
.notice{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;background:rgba(4,8,10,.92);z-index:5}.card{width:min(430px,90vw);padding:28px;background:#101518;border:1px solid #2d444b;box-shadow:0 20px 60px #000}.card h1{margin:0 0 10px;font-size:20px}.card p{color:#9aaeb3;line-height:1.5;font-size:13px}.error{color:#ff4d5a;font-size:12px;margin-top:8px}
.aircraft{padding:9px;background:#141c20;border:1px solid #203036;margin:7px 0;cursor:pointer}.aircraft:hover{border-color:#39ff88}.callsign{font-weight:bold;color:#39ff88}.small{font:10px Consolas,monospace;color:#829398;margin-top:3px}
</style></head>
<body>
<div class="app"><div class="scope-wrap"><canvas id="radar" class="scope"></canvas>
<div id="notice" class="notice"><div class="card"><h1>LOCATION REQUIRED</h1><p>This radar uses your browser's GPS to make <b>your current position</b> the radar origin. Your browser will ask for location permission.</p><button onclick="requestLocation()">ENABLE GPS LOCATION</button><div id="err" class="error"></div></div></div>
</div><aside class="panel"><div class="title">AIRSPACE RADAR</div><div id="status" class="sub">WAITING FOR GPS</div>
<div class="row"><div><div class="label">LATITUDE</div><div id="lat" class="value">—</div></div><div><div class="label">LONGITUDE</div><div id="lon" class="value">—</div></div></div>
<div class="row"><div><div class="label">RANGE</div><div class="value">50 KM</div></div><div><div class="label">AIRCRAFT</div><div id="count" class="value green">0</div></div></div>
<div class="label" style="margin-top:18px">TRACKED AIRCRAFT</div><div id="aircraftList"></div></aside></div>
<script>
const canvas=document.getElementById('radar'),ctx=canvas.getContext('2d');let userLat=null,userLon=null,aircraft=[],airports=[];const RANGE=50;
function resize(){canvas.width=canvas.clientWidth*devicePixelRatio;canvas.height=canvas.clientHeight*devicePixelRatio;ctx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0);draw()}window.addEventListener('resize',resize);
function requestLocation(){
 if(!navigator.geolocation){document.getElementById('err').textContent='Geolocation is not supported by this browser.';return}
 document.getElementById('err').textContent='Requesting GPS permission...';
 navigator.geolocation.getCurrentPosition(pos=>{userLat=pos.coords.latitude;userLon=pos.coords.longitude;document.getElementById('notice').style.display='none';document.getElementById('lat').textContent=userLat.toFixed(6)+'°';document.getElementById('lon').textContent=userLon.toFixed(6)+'°';sendLocation();loadRadar();},err=>{document.getElementById('err').textContent='Location permission was denied or unavailable. Please allow location and try again.'},{enableHighAccuracy:true,maximumAge:30000,timeout:15000});
}
async function sendLocation(){try{await fetch('/api/location',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({latitude:userLat,longitude:userLon})})}catch(e){}}
async function loadRadar(){if(userLat===null)return;try{let r=await fetch(`/api/radar?lat=${encodeURIComponent(userLat)}&lon=${encodeURIComponent(userLon)}`);let d=await r.json();if(!d.success)throw Error(d.error);aircraft=d.aircraft||[];airports=d.airports||[];document.getElementById('status').textContent=d.status;document.getElementById('count').textContent=aircraft.length;renderList();draw()}catch(e){document.getElementById('status').textContent='CONNECTION ERROR';}}
function renderList(){let el=document.getElementById('aircraftList');el.innerHTML='';aircraft.sort((a,b)=>a.distance-b.distance).slice(0,30).forEach(p=>{let d=document.createElement('div');d.className='aircraft';d.innerHTML=`<div class="callsign">${esc(p.callsign)}</div><div class="small">${p.distance.toFixed(1)} KM • ${p.direction} • ${p.altitude_ft??'—'} FT</div><div class="small">${p.speed_kmh??'—'} KM/H • HDG ${p.heading??'—'}° • ${esc(p.typecode||'UNKNOWN')}</div>`;el.appendChild(d)})}
function esc(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function project(lat,lon){let latKm=(lat-userLat)*111,lonKm=(lon-userLon)*111*Math.cos(userLat*Math.PI/180);let scale=Math.min(canvas.clientWidth*.43,canvas.clientHeight*.43)/RANGE;return [canvas.clientWidth/2+lonKm*scale,canvas.clientHeight/2-latKm*scale]}
function polar(distance,bearing){let r=Math.min(distance,RANGE)/RANGE*Math.min(canvas.clientWidth*.43,canvas.clientHeight*.43);let a=bearing*Math.PI/180;return [canvas.clientWidth/2+r*Math.sin(a),canvas.clientHeight/2-r*Math.cos(a)]}
function draw(){let w=canvas.clientWidth,h=canvas.clientHeight;ctx.clearRect(0,0,w,h);ctx.fillStyle='#07100d';ctx.fillRect(0,0,w,h);let cx=w/2,cy=h/2,r=Math.min(w*.43,h*.43);ctx.strokeStyle='#163b2a';ctx.lineWidth=1;[.25,.5,.75,1].forEach(f=>{ctx.beginPath();ctx.arc(cx,cy,r*f,0,Math.PI*2);ctx.stroke()});ctx.beginPath();ctx.moveTo(cx-r,cy);ctx.lineTo(cx+r,cy);ctx.moveTo(cx,cy-r);ctx.lineTo(cx,cy+r);ctx.stroke();['N','E','S','W'].forEach((t,i)=>{let a=i*Math.PI/2;ctx.fillStyle='#829398';ctx.font='11px Consolas';ctx.textAlign='center';ctx.fillText(t,cx+(r+18)*Math.sin(a),cy-(r+18)*Math.cos(a))});
ctx.fillStyle='#ff4d5a';ctx.fillRect(cx-4,cy-4,8,8);ctx.fillStyle='#829398';ctx.font='10px Consolas';ctx.textAlign='left';ctx.fillText(`${userLat?userLat.toFixed(4):'—'}°, ${userLon?userLon.toFixed(4):'—'}°`,cx+10,cy+4);
 airports.forEach(a=>{let [x,y]=polar(a.distance,a.bearing);ctx.fillStyle='#44aaff';ctx.beginPath();ctx.arc(x,y,3,0,Math.PI*2);ctx.fill()});
 aircraft.forEach(p=>{let [x,y]=polar(p.distance,p.bearing);ctx.save();ctx.translate(x,y);ctx.rotate(((p.heading??p.bearing)-90)*Math.PI/180);ctx.fillStyle='#39ff88';ctx.beginPath();ctx.moveTo(7,0);ctx.lineTo(-5,-3);ctx.lineTo(-2,0);ctx.lineTo(-5,3);ctx.closePath();ctx.fill();ctx.restore()});
 ctx.fillStyle='#e7f1f3';ctx.font='12px Arial';ctx.textAlign='left';ctx.fillText('AIRSPACE RADAR',20,25);ctx.fillStyle='#829398';ctx.font='10px Consolas';ctx.fillText('GPS ORIGIN • LIVE AIRCRAFT',20,43);ctx.textAlign='right';ctx.fillText('50 KM RANGE',w-20,25)}
resize();
setInterval(()=>{if(userLat!==null)loadRadar()},15000);
</script></body></html>'''



if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)