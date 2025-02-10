import mysql.connector
import os
from datetime import datetime, timedelta
import html
import urllib.parse
import random

# Load database credentials from environment variables
DB_HOST = os.getenv("MYSQLHOST")
DB_USER = os.getenv("MYSQLUSER")
DB_PASSWORD = os.getenv("MYSQL_ROOT_PASSWORD")
DB_PORT = os.getenv("MYSQLPORT")
DB_NAME = os.getenv("MYSQL_DATABASE")


def connect_db():
    """Helper function to connect to the database."""
    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        port=DB_PORT,
        database=DB_NAME,
    )


def fish_user_exists(username):
    """Check if the username exists in the users table."""
    try:
        conn = connect_db()
        cursor = conn.cursor()
        query = "SELECT COUNT(*) FROM users WHERE username = %s;"
        cursor.execute(query, (username,))
        result = cursor.fetchone()
        return result[0] > 0
    except Exception as err:
        print(f"Error: {err}")
        return False
    finally:
        cursor.close()
        conn.close()


def get_listened_episodes(username):
    """Fetch all episodes the user has listened to, ordered by most recent."""
    try:
        conn = connect_db()
        cursor = conn.cursor(dictionary=True)

        query = """
        SELECT f.id, f.number, f.title, f.presenters, f.location, f.date, l.listened_at
        FROM fish_listening_history l
        JOIN fish_episodes f ON l.episode_id = f.id
        WHERE l.user_id = (SELECT id FROM users WHERE username = %s)
        ORDER BY l.listened_at DESC;
        """
        cursor.execute(query, (username,))
        return cursor.fetchall()
    except Exception as err:
        print(f"Error: {err}")
        return []
    finally:
        cursor.close()
        conn.close()


def remove_listened_episode(username, episode_id):
    """Remove an episode from the user's listening history."""
    try:
        conn = connect_db()
        cursor = conn.cursor()

        query = """
        DELETE FROM fish_listening_history
        WHERE user_id = (SELECT id FROM users WHERE username = %s)
        AND episode_id = %s;
        """
        cursor.execute(query, (username, episode_id))
        conn.commit()
    except Exception as err:
        print(f"Error: {err}")
    finally:
        cursor.close()
        conn.close()


def get_filtered_random_episode(is_live_filter, selected_presenters, username, exclude_months):
    """Fetch a filtered random episode from the fish_episodes table."""
    try:
        conn = connect_db()
        cursor = conn.cursor(dictionary=True)

        # Build the query with filters
        query = "SELECT * FROM fish_episodes WHERE 1=1"
        params = []

        if is_live_filter is not None:
            query += " AND is_live = %s"
            params.append(is_live_filter)

        if selected_presenters:
            for presenter in selected_presenters:
                query += " AND LOWER(presenters) LIKE LOWER(%s)"
                params.append(f"%{presenter}%")  # Case-insensitive search

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

        cursor.execute(query, params)
        episodes = cursor.fetchall()

        for episode in episodes:
            episode["title"] = html.unescape(urllib.parse.unquote(episode["title"]))

        return random.choice(episodes) if episodes else None
    except Exception as err:
        print(f"Error: {err}")
        return None
    finally:
        cursor.close()
        conn.close()


def mark_episode_listened(username, episode_id):
    """Mark an episode as listened by a user."""
    try:
        conn = connect_db()
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
        cursor.close()
        conn.close()
