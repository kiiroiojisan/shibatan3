from openai import OpenAI
from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.utils import secure_filename
import os
import base64
import pandas as pd
from flask import send_from_directory
import json
import time
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
load_dotenv()
app = Flask(__name__)
app.secret_key = os.urandom(24)  # セッションのための秘密鍵（ランダム生成）

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
LOG_FILE = "chat_log.json"
USERS_FILE = "users.json"

UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'csv', 'xlsx', 'xls', 'mp3', 'wav', 'm4a'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
LOG_DIR = "logs"
FAILED_LOGINS_FILE = "failed_logins.json"

def load_failed_logins():
    if os.path.exists(FAILED_LOGINS_FILE):
        with open(FAILED_LOGINS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_failed_logins(data):
    with open(FAILED_LOGINS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}
def save_users(users):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)
def get_user_log_file():
    username = session.get("username", "default")
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)
    return os.path.join(LOG_DIR, f"{username}_chat_log.json")

def save_conversation_to_file(convo):
    log_file = get_user_log_file()
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(convo, f, ensure_ascii=False, indent=2)
def load_conversation_from_file():
    log_file = get_user_log_file()
    if os.path.exists(log_file):
        with open(log_file, "r", encoding="utf-8") as f:
            return json.load(f)
    else:
        return [{"role": "system", "content": "あなたは可愛い女の子のAIアシスタントです。"}]
#DALL-E画像生成関数の追加
def generate_image_with_gpt(prompt):
    response = client.images.generate(
        model="dall-e-3",
        prompt=prompt,
        size="1024x1024",
        quality="standard",
        n=1
    )
    image_url = response.data[0].url
    return image_url
def get_gpt_response(messages, model="gpt-3.5-turbo"):
    response = client.chat.completions.create(
        model=model,
        messages=messages
    )
    return response.choices[0].message.content, response.usage
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.',1)[1].lower() in ALLOWED_EXTENSIONS

total_cost = 0.0
def analyze_image_with_gpt(image_path):
    with open(image_path, "rb") as f:
        image_data = f.read()
    encoded = base64.b64encode(image_data).decode("utf-8")
    data_uri = f"data:image/png;base64,{encoded}"

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "この画像についてどう思う？"},
                    {"type": "image_url", "image_url": {"url": data_uri}}
                ]
            }
        ],
        max_tokens=1000
    )
    return response.choices[0].message.content
def transcribe_audio(file_path):
    with open(file_path, "rb") as f:
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            response_format="text"
        )
    return transcript
def analyze_table_file(file_path):
    try:
        if file_path.endswith(".csv"):
            df = pd.read_csv(file_path)
        else:
            df = pd.read_excel(file_path)

        content_preview = df.head(5).to_string()
        prompt = f"以下はデータの一部です。全体の傾向を要約してください：\n\n{content_preview}"

        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        return response.choices[0].message.content

    except Exception as e:
        return f"解析中にエラーが発生しました: {e}"
@app.route("/")
def index():
    return redirect(url_for("login"))
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        users = load_users()

        if username in users:
            return render_template("register.html", error="このユーザー名は既に存在します。")

        # ✅ ハッシュ化して保存
        hashed_password = generate_password_hash(password)
        users[username] = hashed_password

        save_users(users)
        return redirect(url_for("login"))

    return render_template("register.html")
@app.route("/change_password", methods=["GET", "POST"])
def change_password():
    if request.method == "POST":
        username = request.form.get("username")
        current = request.form.get("current_password")
        new_pw = request.form.get("new_password")

        users = load_users()

        if username not in users:
            return render_template("change_password.html", error="ユーザーが存在しません。")

        if check_password_hash(users[username], current):
            users[username] = generate_password_hash(new_pw)
            save_users(users)
            return render_template("change_password.html", message="パスワードを変更しました。")
        else:
            return render_template("change_password.html", error="現在のパスワードが間違っています。")

    return render_template("change_password.html")
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        users = load_users()
        failed_logins = load_failed_logins()

        # ロックされているか確認
        if failed_logins.get(username, {}).get("locked", False):
            return render_template("login.html", error="このアカウントはロックされています。")

        # 正しいログインか
        if username in users and check_password_hash(users[username], password):
            session["logged_in"] = True
            session["username"] = username
            failed_logins.pop(username, None)  # 成功時は記録削除
            save_failed_logins(failed_logins)
            return redirect(url_for("chat"))
        else:
            # 失敗回数カウント
            user_record = failed_logins.get(username, {"count": 0, "locked": False})
            user_record["count"] += 1
            if user_record["count"] >= 5:
                user_record["locked"] = True
            (failed_logins)
            failed_logins[username] = user_record
            save_failed_logins
            msg = "ログイン失敗。ユーザー名またはパスワードが間違っています。"
            if user_record["locked"]:
                msg = "5回連続で失敗したためアカウントがロックされました。"
            return render_template("login.html", error=msg)

    return render_template("login.html")

@app.route("/chat", methods=["GET", "POST"])
def chat():
    global total_cost
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    # 会話履歴をファイルから読み込み
    conversation = load_conversation_from_file()

    reply = ""
    cost_info = ""
    file_preview = None
    uploaded_filename = ""

    if request.method == "POST":
        user_input = request.form.get("user_input", "")
        file = request.files.get("file")

        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            ext = filename.rsplit(".", 1)[1].lower()
            unique_filename = f"{session['username']}_{int(time.time())}.{ext}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
            file.save(filepath)

            ext = filename.rsplit(".", 1)[1].lower()

            if ext in {"png", "jpg", "jpeg", "gif"}:
                reply = analyze_image_with_gpt(filepath)
            elif ext in {"csv", "xlsx", "xls"}:
                reply = analyze_table_file(filepath)
            elif ext in {"mp3", "wav", "m4a"}:
                transcript = transcribe_audio(filepath)
                conversation.append({"role": "user", "content": transcript})
                reply, usage = get_gpt_response(conversation)
                total_cost += (usage.prompt_tokens * 0.0005 + usage.completion_tokens * 0.0015) / 1000
            else:
                reply = f"{filename} をアップロードしました。"

            conversation.append({"role": "user", "content": f"[ファイルアップロード: {filename}]\n{user_input}"})
            conversation.append({"role": "assistant", "content": reply})

        elif user_input:
            # 🔍 「画像生成っぽい」キーワードが入っているか判定
            keywords = ["画像", "イラスト", "写真", "出力して", "見せて", "描いて", "絵"]
            if any(kw in user_input for kw in keywords):
                image_prompt = user_input.strip()
                image_url = generate_image_with_gpt(image_prompt)

                reply = f"こちらが「{image_prompt}」のイメージです：<br><img src='{image_url}' alt='生成画像' style='max-width:100%;' />"
                conversation.append({"role": "user", "content": user_input})
                conversation.append({"role": "assistant", "content": reply})
            else:
                conversation.append({"role": "user", "content": user_input})
                reply, usage = get_gpt_response(conversation)
                conversation.append({"role": "assistant", "content": reply})
                total_cost += (usage.prompt_tokens * 0.0005 + usage.completion_tokens * 0.0015) / 1000

        #  会話ログを保存
        save_conversation_to_file(conversation)

        cost_info = f"合計料金: ${total_cost:.6f}"

    return render_template("chat.html", conversation=conversation, reply=reply, cost_info=cost_info, file_preview=file_preview, uploaded_filename=uploaded_filename)

@app.route("/reset", methods=["POST"])
def reset_chat():
    initial_prompt = [{"role": "system", "content": "あなたは可愛い女の子のAIアシスタントです。"}]
    save_conversation_to_file(initial_prompt)
    return redirect(url_for("chat"))
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
@app.route("/admin")
def admin_page():
    if not session.get("logged_in") or session.get("username") != "admin":
        return redirect(url_for("login"))

    users = load_users()
    failed_logins = load_failed_logins()
    return render_template("admin.html", users=users, failed_logins=failed_logins)
if __name__ == "__main__":
    app.run(debug=True)