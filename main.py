from flask import Flask, jsonify, render_template, request
import mysql.connector
import random
import os

app = Flask(__name__)

# Database configuration
DB_HOST = os.getenv("MYSQL_URL")
DB_USER = os.getenv("MYSQLUSER")
DB_PASSWORD = os.getenv("MYSQL_ROOT_PASSWORD")
DB_PORT = os.getenv("MYSQLPORT")
DB_NAME = os.getenv("MYSQL_DATABASE")


def get_random_episode():
    """Fetch a random episode from the fish_episodes table."""
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            port=DB_PORT,
            database=DB_NAME,
        )
        cursor = conn.cursor(dictionary=True)

        # Query to get the total number of episodes
        cursor.execute("SELECT COUNT(*) AS count FROM fish_episodes;")
        result = cursor.fetchone()
        total_episodes = result["count"]

        if total_episodes > 0:
            # Get a random ID
            random_id = random.randint(1, total_episodes)

            # Fetch the random episode
            cursor.execute("SELECT * FROM fish_episodes WHERE id = %s;", (random_id,))
            episode = cursor.fetchone()
            return episode

    except mysql.connector.Error as err:
        print(f"Error: {err}")
        return None
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.route("/")
def index():
    return jsonify({"Choo Choo": "Welcome to your Flask app, its kappi 🚅"})


@app.route("/fish", methods=["GET", "POST"])
def fish():
    if request.method == "POST":
        # Fetch a random episode from the database
        episode = get_random_episode()
        if episode:
            return render_template("fish.html", episode=episode)
        else:
            return "Could not fetch episode from the database.", 500

    # Render the page with the "random episode" button
    return render_template("fish.html", episode=None)


if __name__ == "__main__":
    app.run(debug=True, port=os.getenv("PORT", default=5000))
