from flask import Blueprint, jsonify, request, Response, render_template, redirect, url_for
import ffmpeg
import io
import requests
import os
from datetime import datetime
from database.database import connect_db

vivi = Blueprint("vivi", __name__)
GRAPH_API_TOKEN = os.getenv("GRAPH_API_TOKEN")
META_WEBHOOK_VERIFY_TOKEN = os.getenv("META_WEBHOOK_VERIFY_TOKEN")

# Bunny.net storage details
BUNNY_STORAGE_ZONE = os.getenv("BUNNY_STORAGE_ZONE")
BUNNY_API_KEY = os.getenv("BUNNY_API_KEY")
BUNNY_PULL_URL = os.getenv("BUNNY_PULL_URL")

DOMAIN = os.getenv("DOMAIN")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
ADMIN_PHONE_NUMBER = os.getenv("ADMIN_PHONE_NUMBER")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_TTS_VOICE = "nova"  # British female voice

# Construct the correct storage URL
BUNNY_STORAGE_URL = f"https://jh.storage.bunnycdn.com/{BUNNY_STORAGE_ZONE}"


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


def get_media_url(media_id):
    """
    Fetches the media URL from Meta's API using the media ID.
    """
    url = f"https://graph.facebook.com/v18.0/{media_id}"
    headers = {"Authorization": f"Bearer {GRAPH_API_TOKEN}"}

    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        print(f"Fetched media URL: {response.json().get('url')}")
        return response.json().get("url")
    else:
        print(f"Failed to fetch media URL: {response.json()}")
        return None


def download_ogg_file(media_url, graph_api_token):
    """
    Downloads the OGG file from the Meta API and returns it as binary data for storage in MySQL.
    """
    try:
        headers = {"Authorization": f"Bearer {graph_api_token}"}
        response = requests.get(media_url, headers=headers, stream=True)

        if response.status_code == 200:
            print("✅ Audio file retrieved successfully.")
            return response.content  # Return OGG binary data directly

        else:
            print(f"❌ Failed to download audio file: {response.status_code}, {response.text}")
            return None

    except Exception as e:
        print(f"🚨 Error processing OGG file: {e}")
        return None


def get_media_url(media_id):
    """Fetch media URL from Meta's API."""
    url = f"https://graph.facebook.com/v18.0/{media_id}"
    headers = {"Authorization": f"Bearer {GRAPH_API_TOKEN}"}
    response = requests.get(url, headers=headers)
    return response.json().get("url") if response.status_code == 200 else None


@vivi.route("/vivi/delete_post/<message_id>", methods=["DELETE"])
def delete_post(message_id):
    """
    Sets the message as listened in the database. TODO: Rename this endpoint to /vivi/listen_post/<message_id> once
    connection to the raspberry pi is re-established.
    """
    try:
        connection = connect_db()
        cursor = connection.cursor(dictionary=True)

        # Set the message as listened in the database
        cursor.execute("UPDATE vivi_messages SET listened = 1 WHERE id = %s", (message_id,))
        connection.commit()
        cursor.close()
        connection.close()
        return jsonify({"status": "success", "message": f"Post {message_id} marked as listened."}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

        # # Fetch the mp3_url from the database
        # cursor.execute("SELECT mp3_url FROM vivi_messages WHERE id = %s", (message_id,))
        # message = cursor.fetchone()

        # if not message:
        #     cursor.close()
        #     connection.close()
        #     return jsonify({"status": "error", "message": "Post not found."}), 404

        # mp3_url = message.get("mp3_url")

        # # Step 1: Attempt to delete the MP3 file from Bunny.net if it exists
        # if mp3_url:
        #     success = delete_mp3_from_bunny(mp3_url)
        #     if not success:
        #         print(f"Error: Failed to delete MP3 from Bunny.net for message ID {message_id}")

        # # Step 2: Delete the message from the database
        # cursor.execute("DELETE FROM vivi_messages WHERE id = %s", (message_id,))
        # connection.commit()

        # cursor.close()
        # connection.close()

        # return jsonify({"status": "success", "message": f"Post {message_id} deleted successfully."}), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


def delete_mp3_from_bunny(mp3_url):
    """
    Deletes the MP3 file from Bunny.net storage.
    """
    try:
        # Extract the filename from the URL
        filename = mp3_url.split("/")[-1]

        # Construct the Bunny.net DELETE request
        delete_url = f"{BUNNY_STORAGE_URL}/{filename}"
        headers = {
            "AccessKey": BUNNY_API_KEY,
            "accept": "application/json",
        }

        response = requests.delete(delete_url, headers=headers)

        if response.status_code == 200 or response.status_code == 204:
            print(f"✅ MP3 file {filename} deleted successfully from Bunny.net.")
            return True
        else:
            print(f"❌ Failed to delete MP3 from Bunny.net: {response.text}")
            return False

    except Exception as e:
        print(f"Error deleting MP3 from Bunny.net: {e}")
        return False


def send_verification_whatsapp(sender_number):
    """
    Sends a WhatsApp message to the admin requesting verification for a new sender.
    The message includes a link to the /vivi/verify_sender endpoint for approval.
    """
    verify_link = f"http://{DOMAIN}/vivi/verify_sender?phone={sender_number}"
    message = f"New sender to Vivi needs approval.\n\n" f"Review details here: {verify_link}"

    if not all([GRAPH_API_TOKEN, WHATSAPP_PHONE_ID, ADMIN_PHONE_NUMBER]):
        print("WhatsApp API credentials or admin phone number not configured.")
        return False

    url = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {GRAPH_API_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {"messaging_product": "whatsapp", "to": ADMIN_PHONE_NUMBER, "type": "text", "text": {"body": message}}

    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            print(f"WhatsApp message sent successfully to {ADMIN_PHONE_NUMBER}.")
            return True
        else:
            print(f"Error sending WhatsApp message: {response.status_code}, {response.text}")
            return False
    except Exception as e:
        print(f"Exception sending WhatsApp message: {e}")
        return False


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
            update_query = "UPDATE vivi_users SET verified = %s WHERE phone = %s"
            cursor.execute(update_query, (True, sender_number))
        elif action == "block":
            update_query = "UPDATE vivi_users SET blocked = %s WHERE phone = %s"
            cursor.execute(update_query, (True, sender_number))
        connection.commit()
        cursor.close()
        connection.close()

        return jsonify({"status": "success", "message": "Sender verification request processed."}), 200


@vivi.route("/vivi", methods=["GET", "POST"])
def whatsapp_webhook():
    print("Incoming webhook request:", request.method)
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")

        if mode == "subscribe" and token == META_WEBHOOK_VERIFY_TOKEN:
            print("Webhook verified successfully!")
            return challenge, 200
        else:
            return f"mode: {mode} token: {token}", 403

    elif request.method == "POST":
        data = request.get_json()
        print("Incoming webhook message:", data)

        messages = data.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {}).get("messages", [])
        contacts = data.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {}).get("contacts", [])

        for message_data, contact_data in zip(messages, contacts):
            message_type = message_data.get("type")
            text_body = message_data.get("text", {}).get("body") if message_type == "text" else None
            media_id = message_data.get("audio", {}).get("id") if message_type == "audio" else None
            sender_name = contact_data.get("profile", {}).get("name")
            sender_number = contact_data.get("wa_id")
            received_at = datetime.utcfromtimestamp(int(message_data.get("timestamp", 0)))

            print(f"Received message from {sender_name} ({sender_number}). Type: {message_type}")

            # Check if sender is in vivi_users and whether they are blocked
            connection = connect_db()
            cursor = connection.cursor(dictionary=True)
            cursor.execute("SELECT * FROM vivi_users WHERE phone = %s", (sender_number,))
            user = cursor.fetchone()
            cursor.close()
            connection.close()

            if user and user.get("blocked"):
                print(f"User {sender_number} is blocked. Skipping message storage.")
                continue  # Skip processing this message

            audio_ogg = None
            mp3_url = None
            if message_type == "audio" and media_id:
                print(f"Received audio message with media ID: {media_id}")
                # Step 1: Retrieve the media URL from Meta's API
                media_url = get_media_url(media_id)
                if media_url:
                    # Step 2: Download & convert audio to MP3
                    audio_ogg = download_ogg_file(media_url, GRAPH_API_TOKEN)
                    if audio_ogg:
                        print("Audio retrieved.")
                        mp3_url = convert_ogg_to_mp3(audio_ogg, received_at.timestamp())
                        print(f"MP3 conversion completed {'successfully' if mp3_url else 'unsuccessfully'}.")
                    else:
                        print("Error retrieving audio from Meta.")

            elif message_type == "text" and text_body:
                print(f"Received text message: {text_body}")
                mp3_data = text_to_speech(text_body)
                if mp3_data:
                    mp3_url = upload_mp3_to_bunny(mp3_data, received_at.timestamp())
                    print(f"MP3 conversion from text completed {'successfully' if mp3_url else 'unsuccessfully'}.")

            # Save message to database (only if sender not blocked)
            try:
                connection = connect_db()
                cursor = connection.cursor()
                insert_query = """
                    INSERT INTO vivi_messages (message, received_at, type, sender_name, sender_number, mp3_url)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """
                cursor.execute(
                    insert_query, (text_body, received_at, message_type, sender_name, sender_number, mp3_url)
                )
                connection.commit()
                message_id = cursor.lastrowid  # Get the ID of the newly inserted message
                cursor.close()
                connection.close()
                print("Message saved to database with ID:", message_id)
            except Exception as e:
                print(f"Error saving message to database: {e}")
                continue

            # If the sender is new or not verified, add/update in vivi_users and send a verification email.
            if not user:
                try:
                    connection = connect_db()
                    cursor = connection.cursor()
                    insert_user_query = """
                        INSERT INTO vivi_users (phone, verified, blocked, message_id)
                        VALUES (%s, %s, %s, %s)
                    """
                    cursor.execute(insert_user_query, (sender_number, False, False, message_id))
                    connection.commit()
                    cursor.close()
                    connection.close()
                    print(f"New user {sender_number} added to vivi_users.")
                except Exception as e:
                    print(f"Error adding new user to vivi_users: {e}")
            elif not user.get("verified"):
                try:
                    connection = connect_db()
                    cursor = connection.cursor()
                    update_user_query = "UPDATE vivi_users SET message_id = %s WHERE phone = %s"
                    cursor.execute(update_user_query, (message_id, sender_number))
                    connection.commit()
                    cursor.close()
                    connection.close()
                    print(f"Updated user {sender_number} with new message ID.")
                except Exception as e:
                    print(f"Error updating user in vivi_users: {e}")

            # If the sender is not verified, send an email to request verification.
            if not user or (user and not user.get("verified")):
                send_verification_whatsapp(sender_number)

        return jsonify({"status": "received"}), 200
