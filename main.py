from flask import Flask, jsonify, render_template, request, redirect, url_for, make_response
import mysql.connector
import random
import os
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime, timedelta
import threading
import time

app = Flask(__name__)

# Database configuration
DB_HOST = os.getenv("MYSQLHOST")
DB_USER = os.getenv("MYSQLUSER")
DB_PASSWORD = os.getenv("MYSQL_ROOT_PASSWORD")
DB_PORT = os.getenv("MYSQLPORT")
DB_NAME = os.getenv("MYSQL_DATABASE")

BASE_URL = "https://nstaaf.fandom.com"
MAIN_URL = f"{BASE_URL}/wiki/List_of_Episodes_of_No_Such_Thing_As_A_Fish"

# ========================== DATABASE FUNCTIONS ==========================


def connect_db():
    """Helper function to connect to the database."""
    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        port=DB_PORT,
        database=DB_NAME,
    )


def user_exists(username):
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


# ========================== SCRAPER FUNCTIONS ==========================


def fetch_episode_details(episode_url):
    """Fetch details for a single episode."""
    response = requests.get(episode_url)
    soup = BeautifulSoup(response.content, "html.parser")

    presenters = []
    location = None
    date_object = None

    date_label = soup.find("h3", string="First Broadcast")
    if date_label:
        date_div = date_label.find_next_sibling("div", class_="pi-data-value")
        if date_div:
            date = date_div.get_text(strip=True)
            try:
                date_object = datetime.strptime(date, "%d %B %Y").strftime("%Y-%m-%d")
            except ValueError:
                date_object = datetime.strptime(date, "%d %b %Y").strftime("%Y-%m-%d")

    presenters_label = soup.find("h3", string="Presenters")
    if presenters_label:
        presenters_div = presenters_label.find_next_sibling("div", class_="pi-data-value")
        if presenters_div:
            presenters = [a.get_text(strip=True) for a in presenters_div.find_all("a")]

    location_label = soup.find("h3", string="Location")
    if location_label:
        location_div = location_label.find_next_sibling("div", class_="pi-data-value")
        if location_div:
            location = location_div.get_text(strip=True)

    return {"presenters": presenters, "location": location, "date": date_object}


def extract_episode_info(url):
    """Extract episode number and title from URL."""
    match = re.search(r"Episode_(\d+):_(.+)", url)
    if match:
        episode_number = int(match.group(1))
        episode_title = match.group(2).replace("_", " ")
        return episode_number, episode_title
    else:
        raise ValueError("URL format is incorrect or doesn't match the expected pattern")


def scrape_new_episodes():
    """Scrape the website and add new episodes to the database."""
    response = requests.get(MAIN_URL)
    soup = BeautifulSoup(response.content, "html.parser")

    episode_links = soup.find_all("a", href=True, title=True)

    try:
        conn = connect_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT MAX(number) AS max_number FROM fish_episodes;")
        result = cursor.fetchone()
        max_episode_number = result["max_number"] if result["max_number"] is not None else 0
        new_episode_found = False
        for link in episode_links:
            if link["href"].startswith("/wiki/Episode_"):
                ep_number, ep_title = extract_episode_info(link["href"])

                if ep_number <= max_episode_number:
                    continue

                print(f"Scraping Episode {ep_number}: {ep_title}...")
                new_episode_found = True

                episode_url = BASE_URL + link["href"]
                details = fetch_episode_details(episode_url)

                is_live = "office" not in details["location"].lower()

                query = """
                INSERT INTO fish_episodes (number, title, presenters, location, is_live, date)
                VALUES (%s, %s, %s, %s, %s, %s)
                """
                cursor.execute(
                    query,
                    (
                        ep_number,
                        ep_title,
                        ", ".join(details["presenters"]),
                        details["location"],
                        is_live,
                        details["date"],
                    ),
                )
                print(f"Added Episode {ep_number}: {ep_title}")

        if not new_episode_found:
            print("No new episodes found.")
        conn.commit()
    except Exception as err:
        print(f"Error: {err}")
    finally:
        cursor.close()
        conn.close()


def periodic_scraper():
    """Run the scraper every hour in a background thread."""
    while True:
        print(f"Scraping new episodes at {datetime.now()}...")
        scrape_new_episodes()
        print("Scraping completed. Waiting for the next run...")
        # time.sleep(3600)  # Wait for 1 hour
        # Wait for 5 mins
        time.sleep(300)


# ========================== FLASK ROUTES ==========================


@app.route("/")
def index():
    return jsonify({"Choo Choo": "Welcome to your Flask app, its kappi 🚅"})


@app.route("/fish", methods=["GET", "POST"])
def fish():
    error = None
    username = request.cookies.get("username")  # Retrieve username from cookie

    # Default values
    episode = None
    is_live = request.form.get("is_live", "either")
    selected_presenters = request.form.getlist("presenters")
    exclude_months = request.form.get("exclude_months", "all")
    listened_episodes = []  # Stores the episodes user has listened to

    resp = make_response()  # Create a response object to modify later

    if request.method == "POST":
        episode_id = request.form.get("episode_id")
        action = request.form.get("action")

        # If the user submits a username, store it in a cookie (but continue processing)
        submitted_username = request.form.get("username")
        if submitted_username:
            username = submitted_username  # Update username for the session
            resp.set_cookie("username", username, max_age=60 * 60 * 24 * 30)  # Store for 30 days

            # Show listened episodes
        if action == "see_listened":
            listened_episodes = get_listened_episodes(username)

        # Remove an episode from the listening history
        elif action == "remove_listened" and episode_id:
            remove_listened_episode(username, episode_id)
            listened_episodes = get_listened_episodes(username)  # Refresh list

        # Mark episode as listened
        if action == "mark_listened" and episode_id:
            mark_episode_listened(username, episode_id)
            resp.set_data(
                render_template(
                    "fish.html",
                    episode=None,
                    presenters=["Dan", "Anna", "Andrew", "James"],
                    username=username,
                    is_live=is_live,
                    selected_presenters=selected_presenters,
                    exclude_months=exclude_months,
                    listened_episodes=get_listened_episodes(username),
                    success="Episode marked as listened!",
                )
            )
            return resp  # Return the modified response

        if action == "get_random_episode":
            episode = get_filtered_random_episode(is_live, selected_presenters, username, exclude_months)
            if not episode:
                error = "No episodes found with the selected filters."

    resp.set_data(
        render_template(
            "fish.html",
            episode=episode,
            presenters=["Dan", "Anna", "Andrew", "James"],
            username=username,
            is_live=is_live,
            selected_presenters=selected_presenters,
            exclude_months=exclude_months,
            listened_episodes=listened_episodes,
            error=error,
        )
    )
    return resp  # Return the modified response


if __name__ == "__main__":
    scraper_thread = threading.Thread(target=periodic_scraper, daemon=True)
    scraper_thread.start()
    app.run(debug=True, port=os.getenv("PORT", default=5000))
