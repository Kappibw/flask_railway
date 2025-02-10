from flask import Blueprint, jsonify, request, Response
import requests
import os
from datetime import datetime
from database.database import connect_db

vivi = Blueprint("vivi", __name__)
GRAPH_API_TOKEN = os.getenv("GRAPH_API_TOKEN")
META_WEBHOOK_VERIFY_TOKEN = os.getenv("META_WEBHOOK_VERIFY_TOKEN")


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


@vivi.route("/vivi/get_post", defaults={"message_id": None}, methods=["GET"])
@vivi.route("/vivi/get_post/<message_id>", methods=["GET"])
def get_post(message_id):
    """
    Retrieves a text message from the database. If message_id is provided, fetches the corresponding message.
    If no message_id is provided, fetches the last message where type is "text".
    """
    try:
        connection = connect_db()
        cursor = connection.cursor(dictionary=True)

        if message_id:
            query = "SELECT sender_name, message FROM vivi_messages WHERE id = %s"
            cursor.execute(query, (message_id,))
        else:
            query = "SELECT sender_name, message FROM vivi_messages WHERE type = 'text' ORDER BY id DESC LIMIT 1"
            cursor.execute(query)

        message_data = cursor.fetchone()

        cursor.close()
        connection.close()

        if message_data:
            return jsonify(message_data)
        else:
            return "Message not found", 404

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


@vivi.route("/vivi", methods=["GET", "POST"])
def whatsapp_webhook():
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

            audio_ogg = None
            if message_type == "audio" and media_id:
                print(f"Received audio message with media ID: {media_id}")
                # Step 1: Retrieve the media URL from Meta's API
                media_url = get_media_url(media_id)
                if media_url:
                    # Step 2: Download & convert audio to MP3
                    audio_ogg = download_ogg_file(media_url, GRAPH_API_TOKEN)
                    if audio_ogg:
                        print("Audio retrieved.")
                    else:
                        print("Error retrieving audio from meta.")

            # Save message to database
            try:
                connection = connect_db()
                cursor = connection.cursor()

                insert_query = """
                    INSERT INTO vivi_messages (message, received_at, type, sender_name, sender_number, audio_ogg)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """
                cursor.execute(
                    insert_query, (text_body, received_at, message_type, sender_name, sender_number, audio_ogg)
                )
                connection.commit()
                cursor.close()
                connection.close()
                print("Message saved to database.")
            except Exception as e:
                print(f"Error saving message to database: {e}")

        return jsonify({"status": "received"}), 200
