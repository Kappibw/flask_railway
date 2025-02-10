from flask import Blueprint, request, render_template, make_response
from database.database import (
    fish_user_exists,
    get_listened_episodes,
    mark_episode_listened,
    remove_listened_episode,
    get_filtered_random_episode,
)

fish = Blueprint("fish", __name__)


@fish.route("/fish", methods=["GET", "POST"])
def landing_page():
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
            if not fish_user_exists(username):
                error = "Username not found. Please enter a valid username."
            else:
                listened_episodes = get_listened_episodes(username)

        # Remove an episode from the listening history
        elif action == "remove_listened" and episode_id:
            remove_listened_episode(username, episode_id)
            listened_episodes = get_listened_episodes(username)  # Refresh list

        # Mark episode as listened
        if action == "mark_listened" and episode_id:
            if not fish_user_exists(username):
                error = "Username not found. Please enter a valid username."
            else:
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
