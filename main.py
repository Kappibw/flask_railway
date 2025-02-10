from flask import Flask
from routes.vivi import vivi
from routes.fish import fish

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
)

# Register Blueprints
app.register_blueprint(vivi)
app.register_blueprint(fish)


@app.route("/")
def index():
    return {"message": "Welcome to the Flask app. Try /vivi or /fish routes."}


if __name__ == "__main__":
    app.run(debug=True, port=5000)
