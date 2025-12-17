from flask import Blueprint, jsonify, request, render_template
import telebot
import ffmpeg
import io
import requests
import os
from datetime import datetime
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
ADMIN_TELEGRAM_ID = os.getenv("ADMIN_TELEGRAM_ID")  # Your Telegram ID to receive approvals

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_TTS_VOICE = "nova"

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


@bot.message_handler(content_types=["text", "voice"])
def handle_incoming_message(message):
    sender_id = str(message.from_user.id)
    sender_name = message.from_user.first_name
    received_at = datetime.utcnow()

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
    if ADMIN_TELEGRAM_ID:
        try:
            bot.send_message(ADMIN_TELEGRAM_ID, msg, parse_mode="Markdown")
        except Exception as e:
            print(f"Failed to notify admin: {e}")


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
    """
    Displays a page for an admin to verify or block a sender.
    GET: Renders a page showing the sender's details (name, phone, most recent message)
         with buttons for "verify" or "block".
         Expects a query parameter 'phone'.
    POST: Processes the form submission to either verify or block the sender.
    """
    if request.method == "GET":
        sender_number = request.args.get("phone")
        if not sender_number:
            return "Sender phone number missing", 400

        # Fetch sender info from vivi_users
        connection = connect_db()
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM vivi_users WHERE phone = %s", (sender_number,))
        user = cursor.fetchone()

        if not user:
            cursor.close()
            connection.close()
            return f"No user found for phone {sender_number}", 404

        # Fetch the most recent message for this sender
        cursor.execute(
            "SELECT message, mp3_url, sender_name FROM vivi_messages WHERE sender_number = %s ORDER BY received_at DESC LIMIT 1",
            (sender_number,),
        )
        message_row = cursor.fetchone()
        sender_name = message_row.get("sender_name") if message_row else "Unknown"
        recent_message = message_row.get("message") if message_row else "No message found."
        mp3_url = message_row.get("mp3_url") if message_row else None
        if mp3_url is not None:
            recent_message = mp3_url

        cursor.close()
        connection.close()

        return render_template(
            "verify_sender.html", sender_number=sender_number, sender_name=sender_name, recent_message=recent_message
        )

    elif request.method == "POST":
        sender_number = request.form.get("phone")
        action = request.form.get("action")  # either "verify" or "block"

        if not sender_number or action not in ["verify", "block"]:
            return "Invalid request", 400

        # Update the user record accordingly
        connection = connect_db()
        cursor = connection.cursor()
        if action == "verify":
            cursor.execute("UPDATE vivi_users SET verified = 1 WHERE phone = %s", (sender_number,))
            bot.send_message(sender_number, "🎉 You've been verified! Vivi can now hear your messages.")
        elif action == "block":
            cursor.execute("UPDATE vivi_users SET blocked = 1 WHERE phone = %s", (sender_number,))
        connection.commit()
        cursor.close()
        connection.close()
        return jsonify({"status": "success", "message": "Sender verification request processed."}), 200
