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


# Construct the correct storage URL
BUNNY_STORAGE_URL = f"https://jh.storage.bunnycdn.com/{BUNNY_STORAGE_ZONE}"


def convert_ogg_to_mp3(audio_ogg, media_id):
    """Convert OGG to MP3 and upload to Bunny.net, returning the MP3 URL."""
    try:
        print("Converting OGG to MP3...")
        input_stream = io.BytesIO(audio_ogg)
        output_stream = io.BytesIO()

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

        # Upload MP3 to Bunny.net
        filename = f"audio_{media_id}.mp3"
        headers = {
            "AccessKey": BUNNY_API_KEY,
            "Content-Type": "application/octet-stream",
            "accept": "application/json",
        }

        # Send binary MP3 file using data
        response = requests.put(f"{BUNNY_STORAGE_URL}/{filename}", headers=headers, data=mp3_data)

        if response.status_code != 201:
            print(f"❌ Failed to upload MP3 to Bunny.net: {response.text}")
            return None

        # Return the final MP3 URL
        mp3_url = f"http://{BUNNY_PULL_URL}.b-cdn.net/{filename}"
        print(f"✅ MP3 uploaded successfully: {mp3_url}")

        return mp3_url

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
    Deletes a post from the database by its message ID.
    """
    try:
        connection = connect_db()
        cursor = connection.cursor()

        # Delete the message with the given message_id
        query = "DELETE FROM vivi_messages WHERE id = %s"
        cursor.execute(query, (message_id,))
        connection.commit()

        # Check if any row was affected (i.e., a message was deleted)
        if cursor.rowcount > 0:
            result = {"status": "success", "message": f"Post {message_id} deleted successfully."}
            status_code = 200
        else:
            result = {"status": "error", "message": "Post not found."}
            status_code = 404

        cursor.close()
        connection.close()

        return jsonify(result), status_code

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


def send_verification_whatsapp(sender_number):
    """
    Sends a WhatsApp message to the admin requesting verification for a new sender.
    The message includes a link to the /vivi/verify_sender endpoint for approval.
    """
    verify_link = f"http://{DOMAIN}/vivi/verify_sender?phone={sender_number}"
    message = f"New sender needs approval.\n\n" f"Sender: {sender_number}\n" f"Review details here: {verify_link}"

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
    If no message_id is provided, fetches the oldest message
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
                WHERE u.verified = 1
                ORDER BY m.id ASC LIMIT 1
            """
            cursor.execute(query)

        message_data = cursor.fetchone()
        cursor.close()
        connection.close()

        if message_data:
            return jsonify(message_data)
        else:
            return "Message not found or sender not verified", 404

    except Exception as e:
        return f"Error: {e}", 500


@vivi.route("/vivi/get_audio/<message_id>", methods=["GET"])
def get_audio(message_id):
    """
    Serves the stored OGG file for a given message ID.
    """
    try:
        connection = connect_db()
        cursor = connection.cursor()

        query = "SELECT audio_ogg FROM vivi_messages WHERE id = %s"
        cursor.execute(query, (message_id,))
        audio_data = cursor.fetchone()

        cursor.close()
        connection.close()

        if audio_data and audio_data[0]:
            return Response(audio_data[0], mimetype="audio/ogg")
        else:
            return "Audio file not found", 404

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
            "SELECT message, sender_name FROM vivi_messages WHERE sender_number = %s ORDER BY received_at DESC LIMIT 1",
            (sender_number,),
        )
        message_row = cursor.fetchone()
        sender_name = message_row.get("sender_name") if message_row else "Unknown"
        recent_message = message_row.get("message") if message_row else "No message found."

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

        return redirect(url_for("vivi.verify_sender", phone=sender_number))


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

            # Save message to database (only if sender not blocked)
            try:
                connection = connect_db()
                cursor = connection.cursor()
                insert_query = """
                    INSERT INTO vivi_messages (message, received_at, type, sender_name, sender_number, audio_ogg, mp3_url)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """
                cursor.execute(
                    insert_query, (text_body, received_at, message_type, sender_name, sender_number, audio_ogg, mp3_url)
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
