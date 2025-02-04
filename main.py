from flask import Flask, jsonify, render_template, request
import mysql.connector
import random
import os
from datetime import datetime, timedelta

app = Flask(__name__)

# Database configuration
DB_HOST = os.getenv("MYSQLHOST")
DB_USER = os.getenv("MYSQLUSER")
DB_PASSWORD = os.getenv("MYSQL_ROOT_PASSWORD")
DB_PORT = os.getenv("MYSQLPORT")
DB_NAME = os.getenv("MYSQL_DATABASE")


def user_exists(username):
    """Check if the username exists in the users table."""
    cursor = None
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            port=DB_PORT,
            database=DB_NAME,
        )
        cursor = conn.cursor()
        query = "SELECT COUNT(*) FROM users WHERE username = %s;"
        cursor.execute(query, (username,))
        result = cursor.fetchone()
        return result[0] > 0
    except Exception as err:
        print(f"Error: {err}")
        return False
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def get_filtered_random_episode(is_live_filter, selected_presenters, username, exclude_months):
    """Fetch a filtered random episode from the fish_episodes table."""
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
        query = """
        SELECT * FROM fish_episodes WHERE 1=1
        """
        params = []

        # Add the is_live filter if specified
        if is_live_filter is not None:
            query += " AND is_live = %s"
            params.append(is_live_filter)

        # Add the presenter filters if specified
        if selected_presenters:
            presenter_conditions = []
            for presenter in selected_presenters:
                presenter_conditions.append("presenters LIKE %s")
                params.append(f"%{presenter}%")
            query += " AND " + " AND ".join(presenter_conditions)

        # Exclude episodes listened to in the last 'exclude_months'
        if username and exclude_months != "all":
            exclude_date = datetime.now() - timedelta(days=int(exclude_months) * 30)
            query += """
            AND id NOT IN (
                SELECT episode_id FROM fish_listening_history
                WHERE user_id = (SELECT id FROM users WHERE username = %s)
                AND listened_at >= %s
            )
            """
            params.extend([username, exclude_date])
        elif username:
            query += """
            AND id NOT IN (
                SELECT episode_id FROM fish_listening_history
                WHERE user_id = (SELECT id FROM users WHERE username = %s)
            )
            """
            params.append(username)

        # Fetch all matching episodes
        cursor.execute(query, params)
        episodes = cursor.fetchall()

        if episodes:
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


def mark_episode_listened(username, episode_id):
    """Mark an episode as listened by a user."""
    cursor = None
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            port=DB_PORT,
            database=DB_NAME,
        )
        cursor = conn.cursor()

        query = """
        INSERT INTO fish_listening_history (user_id, episode_id, listened_at)
        VALUES (
            (SELECT id FROM users WHERE username = %s), %s, %s
        )
        """
        cursor.execute(query, (username, episode_id, datetime.now()))
        conn.commit()
    except Exception as err:
        print(f"Error: {err}")
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
    error = None
    if request.method == "POST":
        username = request.form.get("username")
        is_live = request.form.get("is_live")
        selected_presenters = request.form.getlist("presenters")
        exclude_months = request.form.get("exclude_months", "all")
        episode_id = request.form.get("episode_id")
        action = request.form.get("action")

        # Verify username
        if not user_exists(username):
            error = "Username does not exist."
            return render_template("fish.html", episode=None, presenters=["Dan", "Anna", "Andy", "James"], error=error)

        # Mark episode as listened
        if action == "mark_listened" and episode_id:
            mark_episode_listened(username, episode_id)
            return render_template(
                "fish.html",
                episode=None,
                presenters=["Dan", "Anna", "Andy", "James"],
                success="Episode marked as listened!",
            )

        # Convert is_live filter to boolean or None
        if is_live == "live":
            is_live_filter = True
        elif is_live == "not_live":
            is_live_filter = False
        else:
            is_live_filter = None

        # Fetch a filtered random episode
        episode = get_filtered_random_episode(is_live_filter, selected_presenters, username, exclude_months)
        if episode:
            return render_template(
                "fish.html",
                episode=episode,
                presenters=["Dan", "Anna", "Andy", "James"],
                username=username,
                exclude_months=exclude_months,
            )
        else:
            error = "No episodes found with the selected filters."

    # Render the page with filters
    return render_template("fish.html", episode=None, presenters=["Dan", "Anna", "Andy", "James"], error=error)


if __name__ == "__main__":
    app.run(debug=True, port=os.getenv("PORT", default=5000))
