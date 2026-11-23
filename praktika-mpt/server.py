"""Локальный HTTP-сервер учебной системы распределения на практику."""

import argparse
from contextlib import contextmanager
import csv
from hashlib import pbkdf2_hmac
from hmac import compare_digest
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import secrets
import sqlite3
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit

from allocation import assign


ROOT = Path(__file__).resolve().parent
PROFILES = ("Веб-разработка", "Системное администрирование")
SESSION_TTL = 4 * 60 * 60
DEMO_PASSWORD = "Practice2026!"
PLACE_QUERY = """
    SELECT p.*, o.name AS organization,
           (SELECT count(*) FROM assignments a WHERE a.place_id = p.id) AS occupied
    FROM places p JOIN organizations o ON p.organization_id = o.id
    ORDER BY p.id
"""
ASSIGNMENT_QUERY = """
    SELECT a.*, s.name AS student, s.cohort, s.profile,
           o.name AS organization, p.title
    FROM assignments a JOIN students s ON s.id = a.student_id
    JOIN places p ON p.id = a.place_id JOIN organizations o ON o.id = p.organization_id
"""
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/mark.svg": ("mark.svg", "image/svg+xml"),
}


class RequestError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 310_000)
    return f"{salt}:{digest.hex()}"


@contextmanager
def connect(path, write=False):
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    try:
        with db:
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
    finally:
        db.close()


def setup(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA foreign_keys = ON")
        db.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
        if db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            return
        db.executescript("BEGIN IMMEDIATE;\n" + (ROOT / "demo.sql").read_text(encoding="utf-8"))
        accounts = [("coordinator", "coordinator", None, None)]
        accounts += [("student" if i == 1 else f"student{i}", "student", i, None) for i in range(1, 9)]
        accounts += [("partner" if i == 1 else f"partner{i}", "partner", None, i) for i in range(1, 4)]
        db.executemany(
            "INSERT INTO users (login,password_hash,role,student_id,organization_id) VALUES (?,?,?,?,?)",
            [(login, password_hash(DEMO_PASSWORD), role, student, partner)
             for login, role, student, partner in accounts],
        )
        db.execute("INSERT INTO audit (login,event) VALUES (?,?)", ("system", "Создан демонстрационный набор."))


def rows(db, query, args=()):
    return [dict(row) for row in db.execute(query, args)]


def published(db):
    return db.execute("SELECT 1 FROM assignments WHERE published=1 LIMIT 1").fetchone() is not None


def state(db, user):
    role = user["role"]
    data = {"role": role, "login": user["login"], "profiles": PROFILES, "published": published(db)}
    if role == "coordinator":
        data.update(
            students=rows(db, """
                SELECT s.*, u.login, count(p.place_id) AS preferences
                FROM students s JOIN users u ON s.id=u.student_id
                LEFT JOIN preferences p ON p.student_id=s.id
                GROUP BY s.id ORDER BY s.id
            """),
            organizations=rows(db, "SELECT * FROM organizations ORDER BY id"),
            places=rows(db, PLACE_QUERY),
            assignments=rows(db, ASSIGNMENT_QUERY + " ORDER BY s.id"),
            audit=rows(db, "SELECT * FROM audit ORDER BY id DESC LIMIT 30"),
        )
    elif role == "student":
        student = user["student_id"]
        profile = dict(db.execute("SELECT * FROM students WHERE id=?", (student,)).fetchone())
        places = [p for p in rows(db, PLACE_QUERY) if p["profile"] == profile["profile"]]
        for place in places:
            del place["occupied"]
        data.update(
            student=profile, places=places,
            preferences=rows(db, "SELECT place_id,rank FROM preferences WHERE student_id=? ORDER BY rank", (student,)),
            feedback=rows(db, """
                SELECT p.title, o.name AS organization, f.comment
                FROM feedback f JOIN places p ON p.id=f.place_id
                JOIN organizations o ON o.id=p.organization_id WHERE f.student_id=?
            """, (student,)),
            assignments=rows(db, ASSIGNMENT_QUERY + " WHERE a.student_id=? AND a.published=1", (student,)),
        )
    else:
        org = user["organization_id"]
        data.update(
            organization=db.execute("SELECT name FROM organizations WHERE id=?", (org,)).fetchone()[0],
            places=rows(db, """
                SELECT p.id,p.title,p.profile,p.capacity FROM places p
                WHERE p.organization_id=? ORDER BY p.id
            """, (org,)),
            applicants=rows(db, """
                SELECT s.id AS student_id,s.name,s.cohort,s.resume,p.id AS place_id,p.title,
                       (f.place_id IS NOT NULL) AS interested, f.comment
                FROM preferences pr JOIN students s ON pr.student_id=s.id
                JOIN places p ON pr.place_id=p.id
                LEFT JOIN feedback f USING (student_id,place_id)
                WHERE p.organization_id=? ORDER BY p.id,s.id
            """, (org,)),
            assignments=rows(db, ASSIGNMENT_QUERY + " WHERE p.organization_id=? AND a.published=1 ORDER BY s.id", (org,)),
        )
    return data


def field(data, key, maximum, required=True):
    raw = data.get(key, "")
    if not isinstance(raw, str):
        raise RequestError(f"Поле «{key}» должно быть текстом.")
    value = raw.strip()
    if (required and not value) or len(value) > maximum:
        raise RequestError(f"Проверьте заполнение поля «{key}» (до {maximum} символов).")
    return value


def integer(data, key, low=1, high=2**31 - 1):
    value = data.get(key)
    if type(value) is not int or not low <= value <= high:
        raise RequestError(f"Укажите целое число от {low} до {high} в поле «{key}».")
    return value


def profile_value(data):
    value = field(data, "profile", 100)
    if value not in PROFILES:
        raise RequestError("Выберите одно из направлений подготовки.")
    return value


def draft_required(db):
    if published(db):
        raise RequestError("Сначала отзовите опубликованные результаты.", 409)


def audit(db, user, event):
    db.execute("INSERT INTO audit (login,event) VALUES (?,?)", (user["login"], event))


def change(db, user, path, data):
    role = user["role"]
    allowed = {
        "coordinator": {"/students", "/organizations", "/places", "/capacity", "/calculate", "/publish", "/withdraw"},
        "student": {"/resume", "/preferences"},
        "partner": {"/feedback"},
    }
    if path not in allowed[role]:
        raise RequestError("Это действие недоступно для вашей роли.", 403)

    invalidates = {"/students", "/places", "/capacity", "/preferences", "/feedback"}
    if path in invalidates | {"/calculate"}:
        draft_required(db)
    if path in invalidates:
        db.execute("DELETE FROM assignments")

    if path == "/resume":
        resume = field(data, "resume", 1200, False)
        db.execute("UPDATE students SET resume=? WHERE id=?", (resume, user["student_id"]))
        return "Обновлено резюме."
    if path == "/preferences":
        student = user["student_id"]
        selected = data.get("places")
        if not isinstance(selected, list) or len(selected) > 3 or any(type(x) is not int or not 1 <= x < 2**31 for x in selected):
            raise RequestError("Выберите до трёх мест практики.")
        if len(set(selected)) != len(selected):
            raise RequestError("Одно место нельзя указать дважды.")
        profile = db.execute("SELECT profile FROM students WHERE id=?", (student,)).fetchone()[0]
        valid = {p[0] for p in db.execute("SELECT id FROM places WHERE profile=?", (profile,))}
        if set(selected) - valid:
            raise RequestError("Выбранное место не соответствует направлению подготовки.")
        saved_feedback = rows(db, "SELECT place_id,comment FROM feedback WHERE student_id=?", (student,))
        db.execute("DELETE FROM preferences WHERE student_id=?", (student,))
        db.executemany("INSERT INTO preferences VALUES (?,?,?)", [(student, place, rank) for rank, place in enumerate(selected, 1)])
        db.executemany("INSERT INTO feedback VALUES (?,?,?)", [
            (student, item["place_id"], item["comment"]) for item in saved_feedback if item["place_id"] in selected
        ])
        return "Сохранены приоритеты."
    if path == "/feedback":
        student, place = integer(data, "student_id"), integer(data, "place_id")
        match = db.execute("""
            SELECT 1 FROM preferences pr JOIN places p ON p.id=pr.place_id
            WHERE pr.student_id=? AND pr.place_id=? AND p.organization_id=?
        """, (student, place, user["organization_id"])).fetchone()
        if not match:
            raise RequestError("Заявка недоступна.", 404)
        interested = data.get("interested")
        if type(interested) is not bool:
            raise RequestError("Укажите статус отклика.")
        if interested:
            db.execute("""
                INSERT INTO feedback VALUES (?,?,?) ON CONFLICT(student_id,place_id)
                DO UPDATE SET comment=excluded.comment
            """, (student, place, field(data, "comment", 500, False)))
            return "Сохранён отклик организации."
        db.execute("DELETE FROM feedback WHERE student_id=? AND place_id=?", (student, place))
        return "Отклик организации снят."
    if path == "/students":
        name = field(data, "name", 100)
        cohort = field(data, "cohort", 32)
        login = field(data, "login", 40)
        password = field(data, "password", 96)
        if not login.isascii() or not login.replace("-", "").replace("_", "").isalnum() or len(password) < 10:
            raise RequestError("Логин — латиница, цифры, дефис или подчёркивание. Пароль — от 10 символов.")
        if db.execute("SELECT 1 FROM users WHERE login=?", (login,)).fetchone():
            raise RequestError("Такой логин уже занят.")
        student = db.execute("INSERT INTO students (name,cohort,profile) VALUES (?,?,?)", (name, cohort, profile_value(data))).lastrowid
        db.execute("INSERT INTO users (login,password_hash,role,student_id) VALUES (?,?,'student',?)", (login, password_hash(password), student))
        return f"Добавлен студент {name}."
    if path == "/organizations":
        name = field(data, "name", 100)
        if db.execute("SELECT 1 FROM organizations WHERE name=?", (name,)).fetchone():
            raise RequestError("Организация с таким названием уже есть.")
        db.execute("INSERT INTO organizations (name) VALUES (?)", (name,))
        return f"Добавлена организация {name}."
    if path == "/places":
        org = integer(data, "organization_id")
        if not db.execute("SELECT 1 FROM organizations WHERE id=?", (org,)).fetchone():
            raise RequestError("Выберите организацию из списка.")
        title = field(data, "title", 100)
        db.execute("INSERT INTO places (organization_id,title,profile,capacity) VALUES (?,?,?,?)",
                   (org, title, profile_value(data), integer(data, "capacity", 1, 100)))
        return f"Добавлено место «{title}»."
    if path == "/capacity":
        capacity = integer(data, "capacity", 1, 100)
        if not db.execute("UPDATE places SET capacity=? WHERE id=?", (capacity, integer(data, "place_id"))).rowcount:
            raise RequestError("Место не найдено.", 404)
        return f"Квота изменена на {capacity}."
    if path == "/calculate":
        result = assign(
            rows(db, "SELECT * FROM students ORDER BY id"), rows(db, PLACE_QUERY),
            rows(db, "SELECT * FROM preferences ORDER BY student_id,rank"),
            set(map(tuple, db.execute("SELECT student_id,place_id FROM feedback"))),
        )
        db.execute("DELETE FROM assignments")
        db.executemany("INSERT INTO assignments (student_id,place_id,rank) VALUES (?,?,?)", [
            (student, place, rank) for student, (place, rank) in result.items()
        ])
        return f"Расчёт завершён. Назначений: {len(result)}."
    if path == "/publish":
        if published(db):
            raise RequestError("Результаты уже опубликованы.", 409)
        if not db.execute("UPDATE assignments SET published=1").rowcount:
            raise RequestError("Сначала рассчитайте распределение с назначениями.", 409)
        return "Результаты опубликованы."
    if not published(db):
        raise RequestError("Опубликованных результатов пока нет.", 409)
    db.execute("UPDATE assignments SET published=0")
    return "Публикация отозвана. Назначения сохранены как черновик."


def csv_cell(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


class Server(ThreadingHTTPServer):
    def __init__(self, port, database):
        super().__init__(("127.0.0.1", port), Handler)
        self.database = database
        self.sessions = {}
        self.lock = Lock()
        self.hosts = {f"{host}:{self.server_port}" for host in ("127.0.0.1", "localhost")}


class Handler(BaseHTTPRequestHandler):
    def send_data(self, body, content_type, status=HTTPStatus.OK, headers=()):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, data, status=HTTPStatus.OK, headers=()):
        self.send_data(json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", status, headers)

    def token(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except CookieError:
            return None
        return cookie["session"].value if "session" in cookie else None

    def user(self, db):
        with self.server.lock:
            session = self.server.sessions.get(self.token())
        if not session or session[1] <= monotonic():
            raise RequestError("Войдите в систему.", 401)
        return db.execute("SELECT * FROM users WHERE id=?", (session[0],)).fetchone()

    def payload(self):
        host = self.headers.get("Host")
        if self.headers.get("Origin") != f"http://{host}":
            raise RequestError("Запрос должен быть отправлен из интерфейса приложения.", 403)
        if self.headers.get_content_type() != "application/json":
            raise RequestError("Ожидается запрос JSON.", 415)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 16384:
                raise RequestError("Недопустимый размер запроса.", 413)
            data = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeError):
            raise RequestError("Не удалось прочитать JSON.") from None
        if not isinstance(data, dict):
            raise RequestError("Ожидается объект JSON.")
        return data

    def do_GET(self):
        self.dispatch(self.get)

    def do_POST(self):
        self.dispatch(self.post)

    def dispatch(self, method):
        try:
            if self.headers.get("Host") not in self.server.hosts:
                raise RequestError("Используйте локальный адрес приложения.", 403)
            method(urlsplit(self.path).path)
        except RequestError as error:
            self.send_json({"error": str(error)}, error.status)
        except sqlite3.OperationalError as error:
            self.log_error("%s", error)
            self.send_json({"error": "Не удалось выполнить запрос к базе. Повторите действие."}, 503)

    def get(self, path):
        if path in STATIC:
            filename, content_type = STATIC[path]
            self.send_data((ROOT / "static" / filename).read_bytes(), content_type)
            return
        if path not in {"/api/state", "/api/export"}:
            raise RequestError("Страница не найдена.", 404)
        with connect(self.server.database) as db:
            user = self.user(db)
            if path == "/api/state":
                data = state(db, user)
            else:
                if user["role"] != "coordinator":
                    raise RequestError("Выгрузка доступна координатору.", 403)
                data = rows(db, ASSIGNMENT_QUERY + " ORDER BY s.cohort,s.name")
                if not data:
                    raise RequestError("Пока нет назначений для выгрузки.", 409)
        if path == "/api/state":
            self.send_json(data)
            return
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, delimiter=";")
        writer.writerow(["Студент", "Группа", "Направление", "Организация", "Место", "Приоритет", "Статус"])
        for item in data:
            values = [item[key] for key in ("student", "cohort", "profile", "organization", "title", "rank")]
            writer.writerow([*map(csv_cell, values), "Опубликовано" if item["published"] else "Черновик"])
        self.send_data(buffer.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8",
                       headers=[("Content-Disposition", 'attachment; filename="assignments.csv"')])

    def post(self, path):
        if not path.startswith("/api/"):
            raise RequestError("Страница не найдена.", 404)
        data = self.payload()
        if path == "/api/login":
            self.login(data)
            return
        if path == "/api/logout":
            with self.server.lock:
                self.server.sessions.pop(self.token(), None)
            self.send_json({}, headers=[("Set-Cookie", "session=; Max-Age=0; Path=/; HttpOnly; SameSite=Strict")])
            return
        with connect(self.server.database, write=True) as db:
            user = self.user(db)
            message = change(db, user, path.removeprefix("/api"), data)
            audit(db, user, message)
        self.send_json({"message": message})

    def login(self, data):
        login = field(data, "login", 40)
        password = field(data, "password", 96)
        with connect(self.server.database) as db:
            user = db.execute("SELECT * FROM users WHERE login=?", (login,)).fetchone()
        stored = user["password_hash"] if user else "0" * 32 + ":" + "0" * 64
        valid = compare_digest(stored, password_hash(password, stored.split(":")[0]))
        if not user or not valid:
            raise RequestError("Неверный логин или пароль.", 401)
        token = secrets.token_urlsafe(32)
        with self.server.lock:
            now = monotonic()
            self.server.sessions.pop(self.token(), None)
            self.server.sessions = {key: item for key, item in self.server.sessions.items() if item[1] > now}
            self.server.sessions[token] = (user["id"], now + SESSION_TTL)
        self.send_json({}, headers=[("Set-Cookie", f"session={token}; Path=/; HttpOnly; SameSite=Strict")])


def main():
    parser = argparse.ArgumentParser(description="Запуск учебной системы распределения на практику.")
    parser.add_argument("--port", type=int, default=8000, help="Локальный порт HTTP.")
    parser.add_argument("--database", type=Path, default=ROOT / "data" / "practice.sqlite3", help="Путь к файлу SQLite.")
    options = parser.parse_args()
    setup(options.database)
    with Server(options.port, options.database) as server:
        print(f"Откройте http://127.0.0.1:{server.server_port}/  |  Остановка: Ctrl+C", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()


