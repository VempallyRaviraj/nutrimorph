import os
import json
from datetime import datetime, date, timedelta

from flask import (
    Flask,
    request,
    jsonify,
    session,
    redirect,
    send_from_directory,
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS
from dotenv import load_dotenv

# Load .env file ------------------------------------------
load_dotenv()

# Fetch environment variables ------------------------------
FLASK_ENV = os.getenv("FLASK_ENV", "development")
SECRET_KEY = os.getenv("SECRET_KEY", "fallback-secret-key")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///instance/users.db")

# Initialize OpenAI client ---------------------------------
try:
    from openai import OpenAI

    openai_client = OpenAI(api_key=OPENAI_API_KEY)
except Exception:
    openai_client = None

# =========================================================
# 🔹 App Setup
# =========================================================
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
os.makedirs(os.path.join(BASE_DIR, "instance"), exist_ok=True)

app = Flask(__name__)

# Use secret from .env
app.secret_key = SECRET_KEY

# Use DB from .env
app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.permanent_session_lifetime = timedelta(days=7)

# Enable CORS for browser fetch
CORS(app, supports_credentials=True)

db = SQLAlchemy(app)

# =========================================================
# 🔹 Database Models
# =========================================================


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    gender = db.Column(db.String(20))
    age = db.Column(db.Integer)
    goal = db.Column(db.String(100))

    profile = db.relationship("UserProfile", backref="user", uselist=False)
    settings = db.relationship("UserSettings", backref="user", uselist=False)
    progress_entries = db.relationship(
        "ProgressEntry", backref="user", lazy=True, cascade="all, delete-orphan"
    )
    meal_plans = db.relationship(
        "MealPlan", backref="user", lazy=True, cascade="all, delete-orphan"
    )


class UserProfile(db.Model):
    """
    Extra health and lifestyle information that feeds into personalization.
    """

    __tablename__ = "user_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    height_cm = db.Column(db.Float)  # height
    current_weight_kg = db.Column(db.Float)
    target_weight_kg = db.Column(db.Float)

    activity_level = db.Column(db.String(50))  # e.g. sedentary, light, moderate, heavy
    dietary_preferences = db.Column(db.String(255))  # e.g. vegetarian, vegan, etc.
    allergies = db.Column(db.String(255))
    medical_conditions = db.Column(db.String(255))
    timezone = db.Column(db.String(64), default="UTC")


class MealPlan(db.Model):
    """
    Stores generated AI meal plans per day & goal.
    """

    __tablename__ = "meal_plans"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    plan_date = db.Column(db.Date, nullable=False, default=date.today)
    goal = db.Column(db.String(100))
    calories_target = db.Column(db.Integer)
    macro_split = db.Column(db.JSON)  # {"protein":..., "carbs":..., "fat":...}
    plan_data = db.Column(db.JSON)  # full JSON returned from AI
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ProgressEntry(db.Model):
    """
    Daily or periodic progress logs.
    """

    __tablename__ = "progress_entries"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    entry_date = db.Column(db.Date, nullable=False, default=date.today)
    weight_kg = db.Column(db.Float)
    calories_consumed = db.Column(db.Integer)
    protein_g = db.Column(db.Float)
    carbs_g = db.Column(db.Float)
    fats_g = db.Column(db.Float)
    mood = db.Column(db.String(50))
    notes = db.Column(db.String(500))
    adherence_score = db.Column(db.Float)  # 0-100


class UserSettings(db.Model):
    """
    Basic settings. (You can use/ignore depending on how far you go with settings page.)
    """

    __tablename__ = "user_settings"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    theme = db.Column(db.String(20), default="light")
    email_notifications = db.Column(db.Boolean, default=True)
    weekly_report = db.Column(db.Boolean, default=True)
    marketing_emails = db.Column(db.Boolean, default=False)


with app.app_context():
    db.create_all()

# =========================================================
# 🔹 Helpers
# =========================================================


def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return User.query.get(user_id)


def login_required_json(func):
    """
    Decorator for JSON APIs that require authentication.
    """
    from functools import wraps

    @wraps(func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"success": False, "message": "Unauthorized"}), 401
        return func(*args, **kwargs)

    return wrapper


# =========================================================
# 🔹 Public Routes (Landing + Auth Pages)
# =========================================================


@app.route("/")
def index():
    """Serve the landing page."""
    return send_from_directory("assets/pages", "index.html")


@app.route("/login")
def login_page():
    """Serve login page."""
    return send_from_directory("assets/pages", "login.html")


@app.route("/register")
def register_page():
    """Serve register page."""
    return send_from_directory("assets/pages", "register.html")


# =========================================================
# 🔹 Static Files
# =========================================================


@app.route("/pages/<path:filename>")
def serve_page(filename):
    """Serve HTML pages from /assets/pages."""
    return send_from_directory("assets/pages", filename)


@app.route("/assets/<path:filename>")
def serve_static(filename):
    """Serve static files (CSS, JS, images, etc.)"""
    return send_from_directory("assets", filename)


# =========================================================
# 🔹 API: Authentication
# =========================================================


@app.route("/api/register", methods=["POST"])
def api_register():
    """Create a new user."""
    data = request.get_json() or request.form

    first_name = data.get("firstName")
    last_name = data.get("lastName")
    email = data.get("email")
    password = data.get("password")
    age = data.get("age")
    gender = data.get("gender")
    goal = data.get("goal")

    if not all([first_name, last_name, email, password]):
        return jsonify({"success": False, "message": "Missing required fields"}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"success": False, "message": "Email already registered"}), 409

    hashed_pw = generate_password_hash(password)
    new_user = User(
        first_name=first_name,
        last_name=last_name,
        email=email,
        password=hashed_pw,
        gender=gender,
        age=age,
        goal=goal,
    )
    db.session.add(new_user)
    db.session.flush()  # to get new_user.id

    # Create empty profile + default settings
    profile = UserProfile(user_id=new_user.id)
    settings = UserSettings(user_id=new_user.id)

    db.session.add(profile)
    db.session.add(settings)
    db.session.commit()

    return jsonify({"success": True, "message": "Account created successfully"}), 201


@app.route("/api/login", methods=["POST"])
def api_login():
    """Authenticate user."""
    data = request.get_json() or request.form

    email = data.get("email")
    password = data.get("password")

    user = User.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.password, password):
        return jsonify({"success": False, "message": "Invalid email or password"}), 401

    session.permanent = True
    session["user_id"] = user.id
    session["user_name"] = f"{user.first_name} {user.last_name}"
    session["user_email"] = user.email

    return jsonify(
        {
            "success": True,
            "message": "Login successful",
            "user": {
                "name": f"{user.first_name} {user.last_name}",
                "email": user.email,
            },
        }
    )


@app.route("/api/logout", methods=["POST"])
def api_logout():
    """Clear session and log out user."""
    session.clear()
    return jsonify({"success": True, "message": "Logged out successfully"})


@app.route("/api/me")
def api_me():
    """Return current user session info."""
    if "user_id" not in session:
        return jsonify({"loggedIn": False}), 401

    return jsonify(
        {
            "loggedIn": True,
            "user": {
                "name": session.get("user_name"),
                "email": session.get("user_email"),
            },
        }
    )


# =========================================================
# 🔹 API: Profile (personal + health)
# =========================================================


@app.route("/api/profile", methods=["GET"])
@login_required_json
def get_profile():
    user = get_current_user()
    profile = user.profile

    return jsonify(
        {
            "success": True,
            "data": {
                "firstName": user.first_name,
                "lastName": user.last_name,
                "email": user.email,
                "gender": user.gender,
                "age": user.age,
                "goal": user.goal,
                "profile": {
                    "heightCm": profile.height_cm,
                    "currentWeightKg": profile.current_weight_kg,
                    "targetWeightKg": profile.target_weight_kg,
                    "activityLevel": profile.activity_level,
                    "dietaryPreferences": profile.dietary_preferences,
                    "allergies": profile.allergies,
                    "medicalConditions": profile.medical_conditions,
                    "timezone": profile.timezone,
                },
            },
        }
    )


@app.route("/api/profile", methods=["PUT"])
@login_required_json
def update_profile():
    user = get_current_user()
    profile = user.profile

    data = request.get_json() or {}

    # Update simple user fields
    user.first_name = data.get("firstName", user.first_name)
    user.last_name = data.get("lastName", user.last_name)
    user.gender = data.get("gender", user.gender)
    user.age = data.get("age", user.age)
    user.goal = data.get("goal", user.goal)

    # Update profile fields
    p = data.get("profile", {})
    if p:
        profile.height_cm = p.get("heightCm", profile.height_cm)
        profile.current_weight_kg = p.get("currentWeightKg", profile.current_weight_kg)
        profile.target_weight_kg = p.get("targetWeightKg", profile.target_weight_kg)
        profile.activity_level = p.get("activityLevel", profile.activity_level)
        profile.dietary_preferences = p.get(
            "dietaryPreferences", profile.dietary_preferences
        )
        profile.allergies = p.get("allergies", profile.allergies)
        profile.medical_conditions = p.get(
            "medicalConditions", profile.medical_conditions
        )
        profile.timezone = p.get("timezone", profile.timezone)

    db.session.commit()

    # Update session name if changed
    session["user_name"] = f"{user.first_name} {user.last_name}"

    return jsonify({"success": True, "message": "Profile updated successfully"})


# =========================================================
# 🔹 API: Progress Tracking
# =========================================================


@app.route("/api/progress", methods=["GET"])
@login_required_json
def list_progress():
    user = get_current_user()
    # Optional query params: ?limit=30
    limit = int(request.args.get("limit", 30))

    entries = (
        ProgressEntry.query.filter_by(user_id=user.id)
        .order_by(ProgressEntry.entry_date.desc())
        .limit(limit)
        .all()
    )

    data = [
        {
            "id": e.id,
            "date": e.entry_date.isoformat(),
            "weightKg": e.weight_kg,
            "caloriesConsumed": e.calories_consumed,
            "proteinG": e.protein_g,
            "carbsG": e.carbs_g,
            "fatsG": e.fats_g,
            "mood": e.mood,
            "notes": e.notes,
            "adherenceScore": e.adherence_score,
        }
        for e in entries
    ]

    return jsonify({"success": True, "data": data})


@app.route("/api/progress", methods=["POST"])
@login_required_json
def add_progress():
    user = get_current_user()
    data = request.get_json() or {}

    try:
        entry_date_str = data.get("date")
        if entry_date_str:
            entry_date = datetime.fromisoformat(entry_date_str).date()
        else:
            entry_date = date.today()
    except Exception:
        return jsonify({"success": False, "message": "Invalid date format"}), 400

    entry = ProgressEntry(
        user_id=user.id,
        entry_date=entry_date,
        weight_kg=data.get("weightKg"),
        calories_consumed=data.get("caloriesConsumed"),
        protein_g=data.get("proteinG"),
        carbs_g=data.get("carbsG"),
        fats_g=data.get("fatsG"),
        mood=data.get("mood"),
        notes=data.get("notes"),
        adherence_score=data.get("adherenceScore"),
    )

    db.session.add(entry)
    db.session.commit()

    return jsonify({"success": True, "message": "Progress entry saved"}), 201


# =========================================================
# 🔹 API: Meal Plan Generation (OpenAI)
# =========================================================


# =========================================================
# 🔹 API: Meal Plan Generation (OpenAI) — UPDATED (Option B)
# =========================================================


def build_mealplan_prompt(user: User, profile: UserProfile, payload: dict) -> str:
    """
    Build a clear, structured prompt for the AI.
    """
    goal = payload.get("goal") or user.goal
    calories_target = payload.get("caloriesTarget")
    meals_per_day = payload.get("mealsPerDay", 3)

    return f"""
You are NutriMorph, an AI nutrition coach.

Generate a 1-day meal plan for a single person with the following profile:

- Age: {user.age}
- Gender: {user.gender}
- Primary goal: {goal}
- Height (cm): {profile.height_cm}
- Current weight (kg): {profile.current_weight_kg}
- Target weight (kg): {profile.target_weight_kg}
- Activity level: {profile.activity_level}
- Dietary preferences: {profile.dietary_preferences}
- Allergies: {profile.allergies}
- Medical conditions: {profile.medical_conditions}

Requirements:
- Number of meals (including snacks): {meals_per_day}
- Aim for approximately {calories_target or 'a reasonable'} kcal per day
- Give each meal a name, short description, approximate calories, and macronutrient breakdown.
- Use accessible ingredients and simple prep methods.

Return ONLY valid JSON in the following format:

{{
  "daySummary": "Short human-readable summary of the plan",
  "totalCalories": <number>,
  "macros": {{
    "protein": <number>,
    "carbs": <number>,
    "fat": <number>
  }},
  "meals": [
    {{
      "timeOfDay": "Breakfast / Lunch / Dinner / Snack",
      "title": "Meal name",
      "description": "Short description",
      "calories": <number>,
      "protein": <grams>,
      "carbs": <grams>,
      "fat": <grams>,
      "items": ["list of ingredients or components"]
    }}
  ]
}}
"""


@app.route("/api/mealplan/generate", methods=["POST"])
@login_required_json
def generate_mealplan():
    if openai_client is None:
        return jsonify({"success": False, "message": "OpenAI not configured"}), 500

    user = get_current_user()
    profile = user.profile

    payload = request.get_json() or {}
    prompt = build_mealplan_prompt(user, profile, payload)

    try:
        response = openai_client.chat.completions.create(
            model="gpt-5-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "You are a careful nutrition assistant."},
                {"role": "user", "content": prompt},
            ],
        )
        plan_json = json.loads(response.choices[0].message.content)
    except Exception as e:
        return jsonify({"success": False, "message": f"OpenAI error: {e}"}), 500

    # ✨ No saving here — only generate
    return jsonify({"success": True, "data": plan_json})


@app.route("/api/mealplan/save", methods=["POST"])
@login_required_json
def save_mealplan():
    user = get_current_user()
    data = request.get_json()

    if not data:
        return jsonify({"success": False, "message": "Missing plan data"}), 400

    plan_json = data.get("plan")
    if not plan_json:
        return jsonify({"success": False, "message": "Invalid plan format"}), 400

    macros = plan_json.get("macros", {})

    plan = MealPlan(
        user_id=user.id,
        plan_date=date.today(),
        goal=user.goal,
        calories_target=plan_json.get("totalCalories"),
        macro_split=macros,
        plan_data=plan_json,
    )

    db.session.add(plan)
    db.session.commit()

    return jsonify({"success": True, "message": "Plan saved successfully"})


@app.route("/api/mealplan/latest", methods=["GET"])
@login_required_json
def get_latest_mealplan():
    user = get_current_user()
    plan = (
        MealPlan.query.filter_by(user_id=user.id)
        .order_by(MealPlan.created_at.desc())
        .first()
    )

    if not plan:
        return jsonify({"success": True, "data": None})

    return jsonify(
        {
            "success": True,
            "data": {
                "planDate": plan.plan_date.isoformat(),
                "goal": plan.goal,
                "caloriesTarget": plan.calories_target,
                "macroSplit": plan.macro_split,
                "plan": plan.plan_data,
            },
        }
    )


# =========================================================
# 🔹 API: Dashboard Summary
# =========================================================


@app.route("/api/dashboard/summary", methods=["GET"])
@login_required_json
def dashboard_summary():
    user = get_current_user()
    today = date.today()
    seven_days_ago = today - timedelta(days=7)

    # --- Calories today ---
    today_entries = ProgressEntry.query.filter_by(
        user_id=user.id, entry_date=today
    ).all()
    calories_today = sum(e.calories_consumed or 0 for e in today_entries)

    # --- Latest weight ---
    latest_weight_entry = (
        ProgressEntry.query.filter_by(user_id=user.id)
        .order_by(ProgressEntry.entry_date.desc())
        .first()
    )
    current_weight = latest_weight_entry.weight_kg if latest_weight_entry else None

    # --- Recent weight trend (last 7 days for chart) ---
    recent_entries = (
        ProgressEntry.query.filter(
            ProgressEntry.user_id == user.id, ProgressEntry.entry_date >= seven_days_ago
        )
        .order_by(ProgressEntry.entry_date.asc())
        .all()
    )

    recent_weights = [
        {"date": e.entry_date.isoformat(), "weight": e.weight_kg}
        for e in recent_entries
        if e.weight_kg is not None
    ]

    if len(recent_weights) >= 2:
        trend = recent_weights[-1]["weight"] - recent_weights[0]["weight"]
    else:
        trend = 0

    # --- Latest saved meal plan ---
    latest_plan = (
        MealPlan.query.filter_by(user_id=user.id)
        .order_by(MealPlan.created_at.desc())
        .first()
    )

    latest_mealplan_json = latest_plan.plan_data if latest_plan else None

    # --- Recommendations ---
    recommendations = []

    if calories_today == 0:
        recommendations.append(
            {
                "title": "No meals logged today",
                "body": "Try logging your meals to keep your plan on track.",
                "icon": "📝",
            }
        )

    if trend < 0 and user.goal and "lose" in user.goal.lower():
        recommendations.append(
            {
                "title": "Weight trending down",
                "body": "Nice progress — keep it steady.",
                "icon": "📉",
            }
        )
    elif trend > 0 and user.goal and "gain" in user.goal.lower():
        recommendations.append(
            {
                "title": "Muscle gain continuing",
                "body": "Keep increasing protein intake.",
                "icon": "💪",
            }
        )

    return jsonify(
        {
            "success": True,
            "data": {
                "caloriesToday": calories_today,
                "currentWeightKg": current_weight,
                "streakDays": len(recent_weights),
                "weightTrendLast7Days": trend,
                "recentWeights": recent_weights,
                "latestMealPlan": latest_mealplan_json,
                "recommendations": recommendations,
            },
        }
    )


# =========================================================
# 🔹 API: Settings (optional based on your UI)
# =========================================================


@app.route("/api/settings", methods=["GET"])
@login_required_json
def get_settings():
    user = get_current_user()
    settings = user.settings
    if not settings:
        settings = UserSettings(user_id=user.id)
        db.session.add(settings)
        db.session.commit()

    return jsonify(
        {
            "success": True,
            "data": {
                "theme": settings.theme,
                "emailNotifications": settings.email_notifications,
                "weeklyReport": settings.weekly_report,
                "marketingEmails": settings.marketing_emails,
            },
        }
    )


@app.route("/api/settings", methods=["PUT"])
@login_required_json
def update_settings():
    user = get_current_user()
    settings = user.settings
    if not settings:
        settings = UserSettings(user_id=user.id)
        db.session.add(settings)

    data = request.get_json() or {}

    if "theme" in data:
        settings.theme = data["theme"]
    if "emailNotifications" in data:
        settings.email_notifications = bool(data["emailNotifications"])
    if "weeklyReport" in data:
        settings.weekly_report = bool(data["weeklyReport"])
    if "marketingEmails" in data:
        settings.marketing_emails = bool(data["marketingEmails"])

    db.session.commit()

    return jsonify({"success": True, "message": "Settings updated"})


# =========================================================
# 🔹 Middleware: Protect Dashboard & Private Pages
# =========================================================


@app.before_request
def protect_private_pages():
    """Redirect unauthenticated users from private pages."""
    protected_pages = [
        "dashboard.html",
        "mealplan.html",
        "progress.html",
        "profile.html",
    ]

    if any(page in request.path for page in protected_pages):
        if "user_id" not in session:
            return redirect("/login")

    return None


# =========================================================
# 🔹 Default Error Handling
# =========================================================


@app.errorhandler(404)
def handle_404(e):
    """Redirect all unknown routes to landing page."""
    return redirect("/")


# =========================================================
# 🔹 Run Server
# =========================================================

if __name__ == "__main__":
    app.run(debug=True)
