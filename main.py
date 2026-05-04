from fastapi import FastAPI, Request, Response
import requests
import time
from urllib.parse import urlparse
app = FastAPI()

# ================= META CONFIG =================
META_ACCESS_TOKEN = "EAAOTLjl1U7IBRb1wMZBPuJWC3kaDUesW6FaXHPeaIjTRmUEaghMIilVzIIDI9Ig0hlJwZCCA8Of0Eef2xSvo466KEqWbOZCxPv3s7rORRtL36b4ZA1Dnr1rEiB3jZAJrjFQN7H0kCMUwAYr0Y0JDdQsFwMzTuiwHlczyVgZBE8ZBODyCaFGQIEWRCor0o8FVRIFxPHGRS9mQcU4H0tm1tEVIDnid3J59qyrOumSYUMYo9XZCWXKZADLLBt1ApT8JaZBQ81Rp3w0573llpGZALJJvOF4"
META_PHONE_ID = "1059135423957769"
META_VERIFY_TOKEN = "my_secret_token_123"  # Invent a password here

META_API_URL = f"https://graph.facebook.com/v19.0/{META_PHONE_ID}/messages"

# ================= ODOO CONFIG =================
ODOO_BASE = "http://localhost:8069"
DB_NAME = "test_19e_05may01"
PUBLIC_BASE = "https://xlosu-2401-4900-1f3f-9efc-b6-7e0-5ebc-ab73.run.pinggy-free.link"

ODOO_PRODUCTS_API = f"{ODOO_BASE}/api/products"
ODOO_ORDER_API = f"{ODOO_BASE}/api/whatsapp/order"
ODOO_HEADERS = {"X-Odoo-Database": DB_NAME}

SESSION_TTL = 1800
SESSIONS = {}


# ================= META MESSAGING =================
def send_whatsapp_text(to_phone, message_text):
    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "text",
        "text": {"body": message_text}
    }
    try:
        requests.post(META_API_URL, headers=headers, json=payload)
    except Exception as e:
        print("[META ERROR]", e)


def send_whatsapp_interactive_list(to_phone, products):
    """Generates a native Meta Interactive List from Odoo products"""
    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    rows = []
    # WhatsApp allows max 10 rows in a list
    for p in products[:10]:
        rows.append({
            "id": str(p["id"]),  # We can pass the Odoo ID silently
            "title": str(p["name"])[:24],  # Meta enforces 24 chars max for titles
            "description": f"Price: {p.get('list_price', 0)}"[:72]  # 72 chars max
        })

    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {
                "type": "text",
                "text": "🛍️ Our Catalog"
            },
            "body": {
                "text": "Welcome to our store! Tap the button below to browse our products."
            },
            "footer": {
                "text": "Select a product to continue"
            },
            "action": {
                "button": "View Products",
                "sections": [
                    {
                        "title": "Available Items",
                        "rows": rows
                    }
                ]
            }
        }
    }

    try:
        requests.post(META_API_URL, headers=headers, json=payload)
    except Exception as e:
        print("[META LIST ERROR]", e)


# ================= STATE MANAGEMENT =================
def get_session(phone):
    s = SESSIONS.get(phone)
    if not s or time.time() - s.get("time", 0) > SESSION_TTL:
        new_session = {"step": "start", "time": time.time()}
        SESSIONS[phone] = new_session
        return new_session
    return s


def save_session(phone, data):
    data["time"] = time.time()
    SESSIONS[phone] = data


def reset_session(phone):
    SESSIONS.pop(phone, None)


# ================= ODOO INTEGRATION =================
def fetch_products():
    try:
        r = requests.get(ODOO_PRODUCTS_API, headers=ODOO_HEADERS, timeout=8)
        return r.json() if r.status_code == 200 else []
    except Exception:
        return []


# ================= ODOO =================
def create_order(phone, product, quantity, customer_name=None, customer_email=None):
    try:
        r = requests.post(
            ODOO_ORDER_API,
            headers={**ODOO_HEADERS, "Content-Type": "application/json"},
            json={
                "phone": phone,
                "product": product,
                "quantity": quantity,
                "customer_name": customer_name,
                "customer_email": customer_email
            },
            timeout=15
        )
        data = r.json()

        if "payment_link" in data and data["payment_link"]:
            # BULLETPROOF REWRITE: Ignore Odoo's domain entirely. Extract only the path & query.
            parsed = urlparse(data["payment_link"])
            relative_path = parsed.path
            if parsed.query:
                relative_path += "?" + parsed.query

            data["payment_link"] = PUBLIC_BASE + relative_path

        return data
    except Exception as e:
        return {"error": str(e)}


# ================= WEBHOOK VERIFICATION (META ONLY) =================
@app.get("/whatsapp/webhook")
async def verify_webhook(request: Request):
    """Meta requires this GET endpoint to verify your webhook URL."""
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode and token:
        if mode == "subscribe" and token == META_VERIFY_TOKEN:
            print("WEBHOOK VERIFIED BY META")
            # Must return the integer challenge back to Meta
            return Response(content=challenge, media_type="text/plain")
        return Response(content="Forbidden", status_code=403)
    return Response(content="Bad Request", status_code=400)


# ================= INCOMING MESSAGES =================
@app.post("/whatsapp/webhook")
async def handle_messages(request: Request):
    """Handles incoming JSON payloads from Meta."""
    body = await request.json()

    # Verify this is a WhatsApp status/message update
    if body.get("object") != "whatsapp_business_account":
        return Response(content="OK", status_code=200)

    try:
        entry = body["entry"][0]["changes"][0]["value"]

        # Meta sends delivery statuses (sent, delivered, read) to the webhook too. We ignore them.
        if "messages" not in entry:
            return Response(content="OK", status_code=200)

        message = entry["messages"][0]
        phone = message["from"]
        msg_type = message["type"]

        # Extract the user's name from their WhatsApp profile
        contact_name = entry["contacts"][0]["profile"]["name"]

        clean_text = ""
        selected_product_id = None
        selected_product_title = None

        # Parse text messages
        if msg_type == "text":
            clean_text = message["text"]["body"].lower().strip()

        # Parse interactive list replies
        elif msg_type == "interactive":
            if message["interactive"]["type"] == "list_reply":
                selected_product_id = message["interactive"]["list_reply"]["id"]
                selected_product_title = message["interactive"]["list_reply"]["title"]
                clean_text = selected_product_title.lower()  # Treat the click like text for logic

        print(f"\n[Incoming] From: {phone} | Type: {msg_type} | Data: {clean_text or selected_product_title}")

        if clean_text in {"hi", "hello", "menu", "start"}:
            reset_session(phone)

        session = get_session(phone)
        step = session.get("step", "start")

        # ===== START =====
        if step == "start":
            products = fetch_products()
            if not products:
                send_whatsapp_text(phone, "🚫 No products available right now.")
                return Response(content="OK", status_code=200)

            save_session(phone, {"step": "product", "products": products})
            # Send the interactive list popup!
            send_whatsapp_interactive_list(phone, products)
            return Response(content="OK", status_code=200)

        # ===== PRODUCT =====
        if step == "product":
            products = session.get("products", [])
            selected_product = None

            # If they clicked the menu, we match the exact title
            if selected_product_title:
                for p in products:
                    if str(p["name"])[:24] == selected_product_title:
                        selected_product = p
                        break

            # Fallback if they manually typed a name instead of clicking
            if not selected_product:
                for p in products:
                    if str(p["name"]).lower() == clean_text:
                        selected_product = p
                        break

            if not selected_product:
                send_whatsapp_text(phone, "❌ Please tap the menu button and select a product.")
                return Response(content="OK", status_code=200)

            save_session(phone, {"step": "quantity", "product": selected_product, "customer_name": contact_name})
            send_whatsapp_text(phone, f"How many *{selected_product['name']}* would you like? (e.g. 1, 2, 3)")
            return Response(content="OK", status_code=200)

        # ===== QUANTITY =====
        if step == "quantity":
            try:
                qty = int(clean_text)
                if qty <= 0: raise ValueError
            except:
                send_whatsapp_text(phone, "⚠️ Please enter a valid number (e.g. 1, 2, 3).")
                return Response(content="OK", status_code=200)

            save_session(phone, {
                "step": "email",
                "product": session["product"],
                "quantity": qty,
                "customer_name": session["customer_name"]  # Using their WhatsApp profile name
            })

            send_whatsapp_text(phone,
                               f"Thanks {session['customer_name']}! What is your email address? (Or reply 'skip')")
            return Response(content="OK", status_code=200)

        # ===== EMAIL =====
        if step == "email":
            email = "" if clean_text == "skip" else clean_text

            save_session(phone, {
                "step": "confirm",
                "product": session["product"],
                "quantity": session["quantity"],
                "customer_name": session["customer_name"],
                "customer_email": email
            })

            p_name = session['product']['name']
            qty = session['quantity']
            c_name = session['customer_name']

            send_whatsapp_text(phone,
                               f"Please confirm your order, *{c_name}*:\n\n🛒 {p_name} x {qty}\n\nReply *YES* to confirm or *NO* to cancel.")
            return Response(content="OK", status_code=200)

        # ===== CONFIRM =====
        if step == "confirm":
            if clean_text == "no":
                reset_session(phone)
                send_whatsapp_text(phone, "🚫 Order cancelled. Send 'menu' to start again.")
                return Response(content="OK", status_code=200)

            if clean_text != "yes":
                send_whatsapp_text(phone, "Please reply YES to confirm or NO to cancel.")
                return Response(content="OK", status_code=200)

            send_whatsapp_text(phone, "⏳ Processing your order in Odoo...")

            result = create_order(
                phone,
                session["product"]["name"],
                session["quantity"],
                session["customer_name"],
                session["customer_email"]
            )
            reset_session(phone)

            if "error" in result:
                send_whatsapp_text(phone, f"❌ Error: {result['error']}")
                return Response(content="OK", status_code=200)

            send_whatsapp_text(phone, f"✅ Order Created!\n💳 Pay securely here:\n{result.get('payment_link')}")
            return Response(content="OK", status_code=200)

        # Fallback
        reset_session(phone)
        send_whatsapp_text(phone, "Send *menu* to start.")
        return Response(content="OK", status_code=200)

    except Exception as e:
        print("[WEBHOOK PARSING ERROR]", e)
        return Response(content="OK", status_code=200)

# Keep your Odoo proxy setup if you still need it here...

# ================= PROXY =================
@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy(request: Request, full_path: str):
    url = f"{ODOO_BASE}/{full_path}"

    # 1. Forward headers, but swap the Host so Odoo doesn't get confused
    headers = dict(request.headers)
    headers.pop("host", None)
    headers["X-Odoo-Database"] = DB_NAME

    try:
        # 2. allow_redirects=False is CRITICAL!
        # Odoo uses redirects during checkout. The customer's browser must handle them.
        if request.method == "GET":
            resp = requests.get(
                url,
                params=request.query_params,
                headers=headers,
                cookies=request.cookies,
                allow_redirects=False
            )
        else:
            resp = requests.post(
                url,
                params=request.query_params,
                data=await request.body(),
                headers=headers,
                cookies=request.cookies,
                allow_redirects=False
            )

        # 3. Create the response maintaining Odoo's exact status code
        response = Response(content=resp.content, status_code=resp.status_code)

        # 4. Forward Odoo's headers back to the browser (Cookies, Redirects, etc.)
        for key, value in resp.headers.items():
            if key.lower() not in ["content-encoding", "transfer-encoding", "content-length"]:
                # If Odoo redirects to a relative path (e.g., /my/orders), attach the ngrok domain
                if key.lower() == "location" and value.startswith("/"):
                    value = PUBLIC_BASE + value
                response.headers[key] = value

        return response

    except Exception as e:
        return Response(content=f"Proxy Error: {str(e)}", status_code=500)