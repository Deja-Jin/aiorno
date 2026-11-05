from pathlib import Path
import random
import json
from flask import Flask, render_template, request, session, redirect, url_for
from flask_session import Session

app = Flask(__name__)
app.secret_key = "change-this-secret-key"

# Store session data on the server instead of in the browser cookie.
# This prevents large quizzes (especially "all pairs") from exceeding
# the browser's cookie size limit.
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_FILE_DIR"] = str(Path(__file__).parent / ".flask_session")
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_USE_SIGNER"] = True
Session(app)

ROOT = Path(__file__).parent
REAL_DIR = ROOT / "static" / "images" / "real"
AI_DIR = ROOT / "static" / "images" / "ai"
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_QUESTIONS = 100
EXPLANATIONS_FILE = ROOT / "pair_explanations.json"


def load_explanations():
    """Load pair explanations keyed by the real photo filename."""
    try:
        with EXPLANATIONS_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def image_files(folder):
    """Return supported image files directly inside a folder."""
    folder.mkdir(parents=True, exist_ok=True)
    return sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in ALLOWED_EXTENSIONS
    )


def pair_key(path, kind):
    """
    Match files by their shared base name.
    Real: photo1.jpg
    AI:   photo1_ai.jpg (or photo1-ai.jpg / photo1_fake.jpg / photo1-fake.jpg)
    """
    stem = path.stem.casefold()
    if kind == "ai":
        for suffix in ("_ai", "-ai", " ai", "_fake", "-fake", " fake",
                       "_generated", "-generated", " generated"):
            if stem.endswith(suffix):
                stem = stem[:-len(suffix)]
                break
    return stem


def find_pairs():
    real_files = image_files(REAL_DIR)
    ai_files = image_files(AI_DIR)
    ai_by_key = {}
    for path in ai_files:
        key = pair_key(path, "ai")
        # If duplicate matching names exist, keep the first one deterministically.
        ai_by_key.setdefault(key, path)

    pairs = []
    for real_path in real_files:
        key = pair_key(real_path, "real")
        ai_path = ai_by_key.get(key)
        if ai_path:
            pairs.append({
                "real": f"images/real/{real_path.name}",
                "ai": f"images/ai/{ai_path.name}",
                "name": real_path.stem,
                "explanation": load_explanations().get(
                    real_path.name,
                    "Пояснение для этой пары пока не добавлено. Его можно внести в файл pair_explanations.json.",
                ),
            })
    return pairs


@app.route("/", methods=["GET", "POST"])
def index():
    pairs = find_pairs()
    available = len(pairs)
    if request.method == "POST":
        choice = request.form.get("question_count", "10")
        if choice == "all":
            count = min(available, MAX_QUESTIONS)
        else:
            try:
                count = int(choice)
            except ValueError:
                count = 10
        if count < 1 or count > MAX_QUESTIONS or count > available:
            return render_template(
                "index.html",
                available=available,
                error=f"Выбери от 1 до {min(available, MAX_QUESTIONS)} вопросов. "
                      "Для каждого вопроса нужна совпадающая пара изображений."
            )
        selected = random.sample(pairs, count)
        questions = []
        for pair in selected:
            options = [
                {"src": pair["real"], "kind": "real"},
                {"src": pair["ai"], "kind": "ai"},
            ]
            random.shuffle(options)
            questions.append({
                "name": pair["name"],
                "explanation": pair["explanation"],
                "options": options,
                "correct": next(i for i, opt in enumerate(options) if opt["kind"] == "real"),
            })
        session["questions"] = questions
        session["answers"] = []
        session["current"] = 0
        return redirect(url_for("quiz"))
    return render_template("index.html", available=available, error=None)


@app.route("/quiz", methods=["GET", "POST"])
def quiz():
    questions = session.get("questions", [])
    if not questions:
        return redirect(url_for("index"))

    current = session.get("current", 0)
    answers = session.get("answers", [])

    if request.method == "POST":
        try:
            selected = int(request.form.get("answer", "-1"))
        except ValueError:
            selected = -1
        if selected not in (0, 1):
            return redirect(url_for("quiz"))
        answers.append({
            "question": current,
            "selected": selected,
            "correct": selected == questions[current]["correct"],
        })
        session["answers"] = answers
        current += 1
        session["current"] = current
        if current >= len(questions):
            return redirect(url_for("result"))
        return redirect(url_for("quiz"))

    q = questions[current]
    return render_template(
        "quiz.html",
        question=q,
        number=current + 1,
        total=len(questions),
    )


@app.route("/result")
def result():
    questions = session.get("questions", [])
    answers = session.get("answers", [])
    if not questions or len(answers) < len(questions):
        return redirect(url_for("index"))

    correct_count = sum(1 for a in answers if a["correct"])
    review = []
    for answer in answers:
        q = questions[answer["question"]]
        review.append({
            "number": answer["question"] + 1,
            "correct": answer["correct"],
            "real": next(opt["src"] for opt in q["options"] if opt["kind"] == "real"),
            "ai": next(opt["src"] for opt in q["options"] if opt["kind"] == "ai"),
            "explanation": q.get("explanation", "Пояснение пока не добавлено."),
        })
    return render_template(
        "result.html",
        correct=correct_count,
        total=len(questions),
        percent=round(correct_count / len(questions) * 100),
        review=review,
    )


if __name__ == "__main__":
    REAL_DIR.mkdir(parents=True, exist_ok=True)
    AI_DIR.mkdir(parents=True, exist_ok=True)
    app.run(debug=True)
