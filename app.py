from flask import Flask, jsonify
import time
import hmac
import hashlib
import base64
import urllib.parse
import requests
import datetime
import json

app = Flask(__name__)

# --- CONFIG ---
public_key = "7f1ab27292"
private_key = "29ad843d92a70ea"
site_url = "https://www.discoverhistotripsy.com"
form_ids = [9, 10, 11, 12]
google_api_key = "AIzaSyA5bTCRFCl08ErdqOCrCod08aH7gIoLS-c"
destination_url = "https://us-east1-histosonics.cloudfunctions.net/location_data_function/histosonics/locationsearchupdate/"
site_name = "discover"

# --- DATE RANGE: Today Only ---
today = datetime.date.today().strftime("%Y-%m-%d")
today_readable = datetime.date.today().strftime("%a %b %d %Y")  # Wed Oct 30 2025


# --- FUNCTIONS ---
def generate_signed_url(form_id):
    """Generate signed Gravity Forms v1 API URL for a specific form."""
    method = "GET"
    route = f"forms/{form_id}/entries"
    expires = str(int(time.time()) + 60)
    string_to_sign = f"{public_key}:{method}:{route}:{expires}"

    signature = base64.b64encode(
        hmac.new(private_key.encode(), string_to_sign.encode(), hashlib.sha1).digest()
    )
    encoded_signature = urllib.parse.quote_plus(signature)

    base_url = f"{site_url}/gravityformsapi/{route}"
    query = f"?api_key={public_key}&signature={encoded_signature}&expires={expires}"

    # Only today's entries
    search = {"start_date": today, "end_date": today}
    query += f"&search={urllib.parse.quote_plus(json.dumps(search))}"

    return f"{base_url}{query}"


def get_entries_for_form(form_id):
    """Fetch and simplify entries for a single form."""
    url = generate_signed_url(form_id)
    response = requests.get(url)
    response.raise_for_status()
    data = response.json()
    entries = data.get("response", {}).get("entries", [])

    simplified = []
    for e in entries:
        simplified.append({
            "form_id": e.get("form_id"),
            "entry_id": e.get("id"),
            "date_created": e.get("date_created"),
            "city": e.get("15", "").strip(),     # field 15 = City
            "state": e.get("14", "").strip(),    # field 14 = State
            "email": e.get("3", "").strip(),     # optional
        })
    return simplified


def geocode_city_state(city, state):
    """Use Google Geocoding API to get lat, lng, zip."""
    if not city or not state:
        return None, None, None
    address = f"{city}, {state}, USA"
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={urllib.parse.quote_plus(address)}&key={google_api_key}"
    response = requests.get(url)
    data = response.json()

    if data.get("status") != "OK" or not data.get("results"):
        print(f"No geocode results for {address}")
        return None, None, None

    result = data["results"][0]
    lat = result["geometry"]["location"]["lat"]
    lng = result["geometry"]["location"]["lng"]

    # extract zip code
    zip_code = ""
    for comp in result.get("address_components", []):
        if "postal_code" in comp.get("types", []):
            zip_code = comp.get("long_name")
            break

    return lat, lng, zip_code


def post_entry_to_db(entry):
    """Post a single entry to the cloud function endpoint."""
    lat, lng, zip_code = geocode_city_state(entry["city"], entry["state"])
    if lat is None or lng is None:
        return False

    payload = {
        "date": today_readable,
        "search_pattern": entry["city"],
        "address": f"{entry['city']}, {entry['state']}, USA",
        "city": entry["city"],
        "state": entry["state"],
        "country": "United States",
        "zip_code": zip_code or "",
        "lat": str(lat),
        "lng": str(lng),
        "site": site_name
    }

    headers = {
        "x-api-key": google_api_key,
        "Content-Type": "application/json"
    }

    response = requests.post(destination_url, headers=headers, json=payload)
    if response.status_code == 200:
        print(f"Posted entry {entry['entry_id']} ({entry['city']}, {entry['state']})")
        return True
    else:
        print(f"Failed to post entry {entry['entry_id']}: {response.text}")
        return False


# --- FLASK ROUTE ---
@app.route("/api/sync-entries", methods=["GET"])
def sync_entries():
    """Fetch today's Gravity Forms entries and sync to cloud DB."""
    all_entries = []
    results = []

    for fid in form_ids:
        try:
            print(f"🔍 Fetching entries for Form {fid}...")
            entries = get_entries_for_form(fid)
            print(f"  Found {len(entries)} entries today")
            all_entries.extend(entries)
        except Exception as e:
            print(f"Error fetching form {fid}: {e}")

    print(f"\n📋 Total entries today: {len(all_entries)}")

    for entry in all_entries:
        success = post_entry_to_db(entry)
        results.append({
            "entry_id": entry.get("entry_id"),
            "city": entry.get("city"),
            "state": entry.get("state"),
            "success": success
        })

    return jsonify({
        "date": today_readable,
        "total_entries": len(all_entries),
        "processed": len(results),
        "results": results
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)
