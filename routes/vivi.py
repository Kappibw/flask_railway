from flask import Blueprint, jsonify, request, render_template
import telebot
import time
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
import ffmpeg
import io
import requests
import os
from datetime import datetime, timedelta
from database.database import connect_db

vivi = Blueprint("vivi", __name__)

# --- CONFIGURATION ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
# Using threaded=False is important when running inside a Flask Blueprint
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN, threaded=False)

BUNNY_STORAGE_ZONE = os.getenv("BUNNY_STORAGE_ZONE")
BUNNY_API_KEY = os.getenv("BUNNY_API_KEY")
BUNNY_PULL_URL = os.getenv("BUNNY_PULL_URL")
BUNNY_STORAGE_URL = f"https://jh.storage.bunnycdn.com/{BUNNY_STORAGE_ZONE}"

DOMAIN = os.getenv("DOMAIN")
ADMIN_TELEGRAM_IDS = [id.strip() for id in os.getenv("ADMIN_TELEGRAM_IDS", "").split(",") if id.strip()]

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_TTS_VOICE = "nova"

# --- NIGHTLIGHT CONTROL ---
nightlight_until = 0  # Timestamp until which the nightlight should be on


def get_admin_keyboard():
    """Big button keyboard at the bottom of the screen."""
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton("💡 Control Nightlight"))
    return markup


def get_duration_keyboard():
    """Buttons that appear inside the chat message."""
    markup = InlineKeyboardMarkup()
    # Callback data format: "nl_hours:X"
    markup.add(
        InlineKeyboardButton("1 Hour", callback_data="nl_hours:1"),
        InlineKeyboardButton("2 Hours", callback_data="nl_hours:2"),
    )
    markup.add(
        InlineKeyboardButton("4 Hours", callback_data="nl_hours:4"),
        InlineKeyboardButton("8 Hours", callback_data="nl_hours:8"),
    )
    markup.add(InlineKeyboardButton("Turn off Nightlight", callback_data="nl_off"))
    markup.add(InlineKeyboardButton("❌ Cancel", callback_data="nl_cancel"))
    return markup


@bot.message_handler(
    func=lambda message: str(message.from_user.id) in ADMIN_TELEGRAM_IDS and message.text == "💡 Control Nightlight"
)
def nightlight_trigger(message):
    bot.send_message(
        message.chat.id, "How long should the nightlight stay on for?", reply_markup=get_duration_keyboard()
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("nl_"))
def handle_nightlight_selection(call):
    if call.data == "nl_cancel":
        bot.edit_message_text("Nightlight request cancelled.", call.message.chat.id, call.message.message_id)
        return

    # 1. Determine the expiration datetime
    if call.data == "nl_off":
        expiration_dt = datetime.utcnow()  # Set to "now" to effectively turn it off
        msg_text = "✅ Nightlight will turn OFF in the next 5 seconds."
    else:
        # Extract hours from callback_data (e.g., "nl_hours:4")
        hours = int(call.data.split(":")[1])
        expiration_dt = datetime.utcnow() + timedelta(hours=hours)
        msg_text = f"✅ Nightlight will turn ON for {hours} hours in the next 5 seconds."

    # 2. Update the Database
    try:
        connection = connect_db()
        cursor = connection.cursor()

        # We use id=1 as the single record for the light state
        # ON DUPLICATE KEY UPDATE ensures we only ever have one row
        query = """
            INSERT INTO vivi_nightlight (id, expires_at) 
            VALUES (1, %s) 
            ON DUPLICATE KEY UPDATE expires_at = %s
        """
        cursor.execute(query, (expiration_dt, expiration_dt))
        connection.commit()

        cursor.close()
        connection.close()

        # 3. Give feedback to the Admin
        bot.edit_message_text(msg_text, call.message.chat.id, call.message.message_id)

    except Exception as e:
        print(f"Error saving nightlight to DB: {e}")
        bot.answer_callback_query(call.id, "Error saving settings to database.")


@vivi.route("/vivi/nightlight", methods=["GET"])
def get_nightlight_status():
    """Raspberry Pi calls this to see if the light should be on."""
    try:
        connection = connect_db()
        cursor = connection.cursor(dictionary=True)

        # Fetch the single state record from your table
        cursor.execute("SELECT expires_at FROM vivi_nightlight WHERE id = 1")
        row = cursor.fetchone()

        cursor.close()
        connection.close()

        if row:
            expires_at = row["expires_at"]
            now = datetime.utcnow()

            # Calculate remaining seconds (must be positive or zero)
            # .total_seconds() is the reliable way to get the float difference
            remaining = (expires_at - now).total_seconds()
            remaining_seconds = max(0, int(remaining))

            # Nightlight is active if the expiration time is still in the future
            is_active = remaining_seconds > 0

            return jsonify({"nightlight": is_active, "remaining_seconds": remaining_seconds})

        # Default if no row exists yet
        return jsonify({"nightlight": False, "remaining_seconds": 0})

    except Exception as e:
        print(f"Error fetching nightlight status: {e}")
        return jsonify({"error": "Database error", "nightlight": False, "remaining_seconds": 0}), 500


# --- CORE UTILITIES ---
def upload_mp3_to_bunny(mp3_data, timestamp):
    """Upload MP3 file to Bunny.net and return the public URL."""
    try:
        filename = f"audio_{timestamp}.mp3"
        headers = {
            "AccessKey": BUNNY_API_KEY,
            "Content-Type": "application/octet-stream",
            "accept": "application/json",
        }

        response = requests.put(f"{BUNNY_STORAGE_URL}/{filename}", headers=headers, data=mp3_data)

        if response.status_code != 201:
            print(f"❌ Failed to upload MP3 to Bunny.net: {response.text}")
            return None

        mp3_url = f"http://{BUNNY_PULL_URL}.b-cdn.net/{filename}"
        print(f"✅ MP3 uploaded successfully: {mp3_url}")

        return mp3_url

    except Exception as e:
        print(f"Error uploading MP3 to Bunny.net: {e}")
        return None


def text_to_speech(text):
    """Convert text to speech using OpenAI API and return MP3 audio data."""
    try:
        print("Converting text to speech...")
        url = "https://api.openai.com/v1/audio/speech"
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": "tts-1", "input": text, "voice": OPENAI_TTS_VOICE}

        response = requests.post(url, json=payload, headers=headers)
        if response.status_code == 200:
            print("TTS conversion successful!")
            return response.content  # MP3 binary data
        else:
            print(f"OpenAI API Error: {response.text}")
            return None
    except Exception as e:
        print(f"Error converting text to speech: {e}")
        return None


def convert_ogg_to_mp3(audio_ogg, media_id):
    """Convert OGG to MP3 and upload to Bunny.net, returning the MP3 URL."""
    try:
        print("Converting OGG to MP3...")
        input_stream = io.BytesIO(audio_ogg)

        # Convert OGG to MP3 using FFmpeg
        process = (
            ffmpeg.input("pipe:0", format="ogg")
            .output("pipe:1", format="mp3", audio_bitrate="192k")
            .run_async(pipe_stdin=True, pipe_stdout=True, pipe_stderr=True)
        )
        mp3_data, err = process.communicate(input_stream.read())

        if process.returncode != 0:
            print(f"FFmpeg error: {err}")
            return None

        print("Conversion successful!")

        return upload_mp3_to_bunny(mp3_data, media_id)

    except Exception as e:
        print(f"Error during conversion or upload: {e}")
        return None


# --- TELEGRAM WEBHOOK HANDLING ---


@vivi.route("/vivi/telegram", methods=["POST"])
def telegram_webhook():
    """Receives updates from Telegram."""
    if request.headers.get("content-type") == "application/json":
        json_string = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "OK", 200
    return "Forbidden", 403


@bot.message_handler(commands=["start"])
def send_welcome(message):
    sender_id = str(message.from_user.id)
    if sender_id in ADMIN_TELEGRAM_IDS:
        bot.send_message(
            message.chat.id,
            "Hi Jones's! Use the button below to control the postbox.",
            reply_markup=get_admin_keyboard(),
        )
    else:
        bot.send_message(
            message.chat.id,
            "👋 Welcome to Vivi's Postbox! Send me a voice message or text, and I'll make sure Vivi hears it. If you're new, your message will need approval first.",
        )


@bot.message_handler(content_types=["text", "voice"])
def handle_incoming_message(message):
    sender_id = str(message.from_user.id)
    sender_name = message.from_user.first_name + " " + (message.from_user.last_name or "")
    received_at = datetime.utcnow()

    if message.text and message.text.startswith("/"):
        print(f"Ignoring command message from {sender_id}, command: {message.text}")
        return

    # Check if user is blocked
    connection = connect_db()
    cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT * FROM vivi_users WHERE phone = %s", (sender_id,))
    user = cursor.fetchone()
    cursor.close()
    connection.close()

    if user and user.get("blocked"):
        return

    mp3_url = None
    text_body = None
    message_type = "text"

    if message.content_type == "voice":
        message_type = "audio"
        file_info = bot.get_file(message.voice.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        mp3_url = convert_ogg_to_mp3(downloaded_file, received_at.timestamp())
    elif message.content_type == "text":
        text_body = message.text
        mp3_data = text_to_speech(text_body)
        if mp3_data:
            mp3_url = upload_mp3_to_bunny(mp3_data, received_at.timestamp())

    # Save to Database
    try:
        connection = connect_db()
        cursor = connection.cursor()
        insert_query = """
            INSERT INTO vivi_messages (message, received_at, type, sender_name, sender_number, mp3_url)
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        cursor.execute(insert_query, (text_body, received_at, message_type, sender_name, sender_id, mp3_url))
        connection.commit()
        message_id = cursor.lastrowid

        # New User / Verification Logic
        if not user:
            cursor.execute(
                "INSERT INTO vivi_users (phone, verified, blocked, message_id) VALUES (%s, %s, %s, %s)",
                (sender_id, False, False, message_id),
            )
            connection.commit()
            send_admin_verification(sender_id, sender_name)
        elif not user.get("verified"):
            cursor.execute("UPDATE vivi_users SET message_id = %s WHERE phone = %s", (message_id, sender_id))
            connection.commit()
            send_admin_verification(sender_id, sender_name)

        cursor.close()
        connection.close()
        bot.reply_to(message, "✅ Got it! Your message is saved and waiting for Vivi to listen to it.")
    except Exception as e:
        print(f"Error saving message: {e}")


def send_admin_verification(sender_id, sender_name):
    """Notifies you on Telegram when a new user needs approval."""
    verify_link = f"http://{DOMAIN}/vivi/verify_sender?phone={sender_id}"
    msg = f"🔔 *New Message from Unverified Vivi Postbox User*\nName: {sender_name}\nID: {sender_id}\n\n[Verify or Block Here]({verify_link})"
    for admin in ADMIN_TELEGRAM_IDS:
        try:
            bot.send_message(admin, msg, parse_mode="Markdown")
        except Exception as e:
            print(f"Failed to notify admin {admin}: {e}")


# --- RASPBERRY PI ENDPOINTS ---


@vivi.route("/vivi/get_post", defaults={"message_id": None}, methods=["GET"])
@vivi.route("/vivi/get_post/<message_id>", methods=["GET"])
def get_post(message_id):
    """
    Retrieves a text message from the database only if the sender is verified.
    If message_id is provided, fetches the corresponding message.
    If no message_id is provided, fetches the oldest unlistened message
    from a verified sender.
    """
    try:
        connection = connect_db()
        cursor = connection.cursor(dictionary=True)

        if message_id:
            query = """
                SELECT m.sender_name, m.type, m.message, m.mp3_url 
                FROM vivi_messages m
                JOIN vivi_users u ON m.sender_number = u.phone
                WHERE m.id = %s AND u.verified = 1
            """
            cursor.execute(query, (message_id,))
        else:
            query = """
                SELECT m.id, m.sender_name, m.type, m.message, m.mp3_url 
                FROM vivi_messages m
                JOIN vivi_users u ON m.sender_number = u.phone
                WHERE u.verified = 1 and m.listened = 0
                ORDER BY m.id ASC LIMIT 1
            """
            cursor.execute(query)

        message_data = cursor.fetchone()
        cursor.close()
        connection.close()

        if message_data:
            return jsonify(message_data)
        else:
            if message_id:
                return "Message not found or sender not verified", 404
            else:
                return "No unlistened messages from verified senders", 404

    except Exception as e:
        return f"Error: {e}", 500


@vivi.route("/vivi/listen_post/<message_id>", methods=["DELETE"])
def listen_post(message_id):
    """Marks message as listened and notifies the sender."""
    try:
        connection = connect_db()
        cursor = connection.cursor(dictionary=True)

        # Get sender ID before updating
        cursor.execute("SELECT sender_number FROM vivi_messages WHERE id = %s", (message_id,))
        msg = cursor.fetchone()

        if msg:
            sender_id = msg["sender_number"]
            cursor.execute("UPDATE vivi_messages SET listened = 1 WHERE id = %s", (message_id,))
            connection.commit()

            # Send notification to sender
            try:
                bot.send_message(sender_id, "❤️ Vivi just listened to your message!")
            except Exception as e:
                print(f"Notification error: {e}")

        cursor.close()
        connection.close()
        return jsonify({"status": "success"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# --- ADMIN INTERFACE ---


@vivi.route("/vivi/verify_sender", methods=["GET", "POST"])
def verify_sender():
    sender_number = request.args.get("phone") if request.method == "GET" else request.form.get("phone")

    if not sender_number:
        return "Sender phone number missing", 400

    # Connect to check current status
    connection = connect_db()
    cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT verified, blocked FROM vivi_users WHERE phone = %s", (sender_number,))
    user = cursor.fetchone()

    if not user:
        cursor.close()
        connection.close()
        return f"No user found for phone {sender_number}", 404

    # --- THE MULTI-ADMIN CHECK ---
    if request.method == "POST":
        action = request.form.get("action")

        # 1. If user is already verified and admin tries to verify again
        if user["verified"] and action == "verify":
            cursor.close()
            connection.close()
            return (
                jsonify({"status": "already_done", "message": "Another admin has already approved this sender."}),
                200,
            )

        # 2. If user is already blocked and admin tries to block again
        if user["blocked"] and action == "block":
            cursor.close()
            connection.close()
            return jsonify({"status": "already_done", "message": "Another admin has already blocked this sender."}), 200

        # --- PROCEED WITH UPDATE ---
        cursor = connection.cursor()  # Switch to non-dictionary cursor for updates if preferred
        if action == "verify":
            cursor.execute("UPDATE vivi_users SET verified = 1 WHERE phone = %s", (sender_number,))
            bot.send_message(sender_number, "🎉 You've been verified! Vivi can now hear your messages.")
        elif action == "block":
            cursor.execute("UPDATE vivi_users SET blocked = 1 WHERE phone = %s", (sender_number,))

        connection.commit()
        cursor.close()
        connection.close()
        return jsonify({"status": "success", "message": "Verification processed successfully."}), 200

    # --- GET LOGIC ---
    cursor.execute(
        "SELECT message, mp3_url, sender_name FROM vivi_messages WHERE sender_number = %s ORDER BY received_at DESC LIMIT 1",
        (sender_number,),
    )
    message_row = cursor.fetchone()
    sender_name = message_row.get("sender_name") if message_row else "Unknown"
    recent_message = (
        message_row.get("mp3_url")
        if (message_row and message_row.get("mp3_url"))
        else (message_row.get("message") if message_row else "No message found.")
    )

    cursor.close()
    connection.close()

    # Pass 'user' status to the template so you can disable buttons if already done
    return render_template(
        "verify_sender.html",
        sender_number=sender_number,
        sender_name=sender_name,
        recent_message=recent_message,
        is_verified=user["verified"],
        is_blocked=user["blocked"],
    )
