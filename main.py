from flask import Flask, jsonify, render_template, request
import mysql.connector
import random
import os

app = Flask(__name__)

# Database configuration
DB_HOST = os.getenv("MYSQLHOST")
DB_USER = os.getenv("MYSQLUSER")
DB_PASSWORD = os.getenv("MYSQL_ROOT_PASSWORD")
DB_PORT = os.getenv("MYSQLPORT")
DB_NAME = os.getenv("MYSQL_DATABASE")


def get_filtered_random_episode(is_live_filter, selected_presenters):
    """Fetch a filtered random episode from the fish_episodes table."""
    print(f"Connecting to database at {DB_HOST}...")
    cursor = None
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            port=DB_PORT,
            database=DB_NAME,
        )
        cursor = conn.cursor(dictionary=True)

        # Build the query with filters
        query = "SELECT * FROM fish_episodes WHERE 1=1"
        params = []

        # Add the is_live filter if specified
        if is_live_filter is not None:
            query += " AND is_live = %s"
            params.append(is_live_filter)

        # Add the presenter filters if specified
        if selected_presenters:
            presenter_conditions = []
            for presenter in selected_presenters:
                presenter_conditions.append(f"presenters LIKE %s")
                params.append(f"%{presenter}%")
            query += " AND " + " AND ".join(presenter_conditions)

        # Fetch all matching episodes
        cursor.execute(query, params)
        episodes = cursor.fetchall()

        if episodes:
            # Pick a random episode from the filtered results
            return random.choice(episodes)
        return None

    except Exception as err:
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
        # Get filters from the form
        is_live = request.form.get("is_live")
        selected_presenters = request.form.getlist("presenters")

        # Convert is_live filter to boolean or None
        if is_live == "live":
            is_live_filter = True
        elif is_live == "not_live":
            is_live_filter = False
        else:
            is_live_filter = None

        # Fetch a filtered random episode
        episode = get_filtered_random_episode(is_live_filter, selected_presenters)
        if episode:
            return render_template("fish.html", episode=episode, presenters=["Dan", "Anna", "Andy", "James"])
        else:
            return render_template(
                "fish.html",
                episode=None,
                presenters=["Dan", "Anna", "Andy", "James"],
                error="No episodes found with the selected filters.",
            )

    # Render the page with the "random episode" button and filters
    return render_template("fish.html", episode=None, presenters=["Dan", "Anna", "Andy", "James"])


if __name__ == "__main__":
    app.run(debug=True, port=os.getenv("PORT", default=5000))
