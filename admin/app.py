import os
import io
import json
import uuid
import base64
import mimetypes
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory, render_template

BASE_DIR = Path(__file__).parent
# A pasta do site chama-se "docs" porque o GitHub Pages só serve a raiz
# do repositório ou /docs quando publica a partir de uma branch.
SITE_DIR = BASE_DIR.parent / "docs"
PRODUCTS_JSON = SITE_DIR / "products.json"
IMAGES_DIR = SITE_DIR / "images"
CONFIG_JSON = BASE_DIR / "config.json"
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

# ─── Config (admin-only settings; NÃO publicado no site público) ──────────────
DEFAULT_CONFIG = {
    "server": {
        "host": "127.0.0.1",     # use 0.0.0.0 para acessar de outros dispositivos
        "port": 5001,          # 5000 é usada pelo AirPlay Receiver no macOS
        "publicUrl": "",         # URL pública do admin quando hospedado num servidor
        "apiToken": "",          # token exigido de quem conectar neste catálogo remotamente
    },
    "dataSource": {
        "mode": "local",         # "local" (arquivo) ou "remote" (servidor)
        "localPath": "",         # caminho do products.json (vazio = padrão do projeto)
        "remoteUrl": "",         # URL do /api/catalog do servidor remoto
        "remoteToken": "",       # token para autenticar no catálogo remoto
    },
}

DEFAULT_CATALOG = {
    "store": {"name": "Divina Lolla", "description": "Catálogo de produtos", "logo": ""},
    "contact": {
        "whatsapp": "",
        "interestTemplate": "Olá! Tenho interesse no produto:\n*{nome}*{preco}\nEle ainda está disponível?",
    },
    "categories": [],
    "products": [],
}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB


# ─── Config helpers ───────────────────────────────────────────────────────────
def _deep_merge(base, override):
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    if CONFIG_JSON.exists():
        try:
            with open(CONFIG_JSON, "r", encoding="utf-8") as f:
                cfg = _deep_merge(cfg, json.load(f))
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


def save_config(cfg):
    with open(CONFIG_JSON, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ─── Armazenamento do catálogo (respeita a fonte de dados configurada) ────────
def _local_path():
    cfg = load_config()
    custom = (cfg["dataSource"].get("localPath") or "").strip()
    return Path(custom).expanduser() if custom else PRODUCTS_JSON


def _normalize(data):
    """Garante que store/contact/categories/products existam com defaults."""
    data = data or {}
    data["store"] = _deep_merge(DEFAULT_CATALOG["store"], data.get("store"))
    data["contact"] = _deep_merge(DEFAULT_CATALOG["contact"], data.get("contact"))
    data.setdefault("categories", [])
    data.setdefault("products", [])
    return data


def load_local():
    path = _local_path()
    if not path.exists():
        return json.loads(json.dumps(DEFAULT_CATALOG))
    with open(path, "r", encoding="utf-8") as f:
        return _normalize(json.load(f))


def save_local(data):
    path = _local_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_normalize(data), f, ensure_ascii=False, indent=2)


def _remote_request(url, token, method="GET", payload=None):
    headers = {"Accept": "application/json"}
    if token:
        headers["X-Api-Token"] = token
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def load_data():
    cfg = load_config()
    if cfg["dataSource"]["mode"] == "remote":
        url = cfg["dataSource"].get("remoteUrl", "").strip()
        if not url:
            raise RuntimeError("Fonte de dados remota sem URL configurada.")
        return _normalize(_remote_request(url, cfg["dataSource"].get("remoteToken", "")))
    return load_local()


def save_data(data):
    cfg = load_config()
    if cfg["dataSource"]["mode"] == "remote":
        url = cfg["dataSource"].get("remoteUrl", "").strip()
        if not url:
            raise RuntimeError("Fonte de dados remota sem URL configurada.")
        _remote_request(url, cfg["dataSource"].get("remoteToken", ""), method="PUT", payload=_normalize(data))
        return
    save_local(data)


def is_remote():
    return load_config()["dataSource"]["mode"] == "remote"


def _store_image(product_id, file):
    """Salva a imagem. Local: arquivo em docs/images. Remoto: data URI embutido."""
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return None
    if is_remote():
        mime = mimetypes.types_map.get(ext, "image/jpeg")
        b64 = base64.b64encode(file.read()).decode("ascii")
        return f"data:{mime};base64,{b64}"
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{product_id}{ext}"
    file.save(IMAGES_DIR / filename)
    return f"images/{filename}"


def _remove_image(image_ref):
    if not image_ref or image_ref.startswith("data:"):
        return
    old = SITE_DIR / image_ref
    if old.exists():
        old.unlink()


# ─── Páginas ──────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


# ─── Dados do catálogo (usados pelo admin) ────────────────────────────────────
@app.route("/api/data")
def get_data():
    try:
        return jsonify(load_data())
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/store", methods=["PUT"])
def update_store():
    data = load_data()
    body = request.json or {}
    if "name" in body:
        data["store"]["name"] = body["name"]
    if "description" in body:
        data["store"]["description"] = body["description"]
    if "logo" in body:
        data["store"]["logo"] = body["logo"]
    if "whatsapp" in body:
        data["contact"]["whatsapp"] = body["whatsapp"]
    if "interestTemplate" in body:
        data["contact"]["interestTemplate"] = body["interestTemplate"]
    if "categories" in body:
        data["categories"] = body["categories"]
    if "products" in body:
        data["products"] = body["products"]
    save_data(data)
    return jsonify({"ok": True})


@app.route("/api/products", methods=["POST"])
def add_product():
    data = load_data()
    product = {
        "id": str(uuid.uuid4()),
        "name": request.form.get("name", "").strip(),
        "description": request.form.get("description", "").strip(),
        "price": request.form.get("price", "").strip(),
        "category": request.form.get("category", "").strip(),
        "image": "",
    }

    file = request.files.get("image")
    if file and file.filename:
        ref = _store_image(product["id"], file)
        if ref:
            product["image"] = ref

    data["products"].append(product)

    cat = product["category"]
    if cat and cat not in data["categories"]:
        data["categories"].append(cat)

    save_data(data)
    return jsonify({"ok": True, "product": product})


@app.route("/api/products/<product_id>", methods=["PUT"])
def update_product(product_id):
    data = load_data()
    product = next((p for p in data["products"] if p["id"] == product_id), None)
    if not product:
        return jsonify({"error": "Produto não encontrado"}), 404

    product["name"] = request.form.get("name", product["name"]).strip()
    product["description"] = request.form.get("description", product["description"]).strip()
    product["price"] = request.form.get("price", product["price"]).strip()
    product["category"] = request.form.get("category", product["category"]).strip()

    file = request.files.get("image")
    if file and file.filename:
        ref = _store_image(product_id, file)
        if ref:
            _remove_image(product.get("image"))
            product["image"] = ref

    data["categories"] = sorted(set(
        p["category"] for p in data["products"] if p.get("category")
    ))

    save_data(data)
    return jsonify({"ok": True, "product": product})


@app.route("/api/products/<product_id>", methods=["DELETE"])
def delete_product(product_id):
    data = load_data()
    product = next((p for p in data["products"] if p["id"] == product_id), None)
    if not product:
        return jsonify({"error": "Produto não encontrado"}), 404

    _remove_image(product.get("image"))

    data["products"] = [p for p in data["products"] if p["id"] != product_id]
    data["categories"] = sorted(set(
        p["category"] for p in data["products"] if p.get("category")
    ))

    save_data(data)
    return jsonify({"ok": True})


# ─── Configurador ─────────────────────────────────────────────────────────────
@app.route("/api/config")
def get_config():
    return jsonify(load_config())


@app.route("/api/config", methods=["PUT"])
def put_config():
    body = request.json or {}
    cfg = load_config()
    cfg = _deep_merge(cfg, {
        "server": body.get("server", {}),
        "dataSource": body.get("dataSource", {}),
    })
    try:
        cfg["server"]["port"] = int(cfg["server"]["port"])
    except (TypeError, ValueError):
        cfg["server"]["port"] = 5001
    if cfg["dataSource"]["mode"] not in ("local", "remote"):
        cfg["dataSource"]["mode"] = "local"
    save_config(cfg)
    return jsonify({"ok": True, "config": cfg, "restart_required": True})


@app.route("/api/test-connection", methods=["POST"])
def test_connection():
    body = request.json or {}
    url = (body.get("remoteUrl") or "").strip()
    token = body.get("remoteToken") or ""
    if not url:
        return jsonify({"ok": False, "error": "Informe a URL do catálogo remoto."})
    try:
        data = _normalize(_remote_request(url, token))
        return jsonify({
            "ok": True,
            "store": data["store"].get("name", ""),
            "products": len(data.get("products", [])),
        })
    except urllib.error.HTTPError as e:
        return jsonify({"ok": False, "error": f"HTTP {e.code}: {e.reason}"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ─── API do catálogo (permite que ESTE servidor seja a fonte remota) ──────────
def _check_api_token():
    required = load_config()["server"].get("apiToken", "")
    if not required:
        return True
    return request.headers.get("X-Api-Token", "") == required


@app.route("/api/catalog", methods=["GET"])
def catalog_get():
    if not _check_api_token():
        return jsonify({"error": "Token inválido"}), 401
    return jsonify(load_local())


@app.route("/api/catalog", methods=["PUT"])
def catalog_put():
    if not _check_api_token():
        return jsonify({"error": "Token inválido"}), 401
    save_local(request.json or {})
    return jsonify({"ok": True})


# ─── Publicação no GitHub Pages ───────────────────────────────────────────────
@app.route("/api/publish", methods=["POST"])
def publish():
    body = request.json or {}
    message = body.get("message", "Atualizar catálogo de produtos").strip() or "Atualizar catálogo"
    repo_dir = SITE_DIR.parent

    # "Publicar" só faz sentido para enviar ao site online (GitHub Pages).
    # Localmente o catálogo já é atualizado ao salvar — não precisa publicar.
    inside = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=repo_dir, capture_output=True, text=True
    )
    if inside.returncode != 0:
        return jsonify({
            "ok": False,
            "local_only": True,
            "error": "Ainda não há um repositório GitHub configurado, então não há site online para atualizar. "
                     "As alterações já valem no site local automaticamente. "
                     "Para publicar na internet, siga o guia CONFIGURAR-GITHUB.md."
        })

    try:
        subprocess.run(["git", "add", "-A"], cwd=repo_dir, check=True, capture_output=True)
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=repo_dir, capture_output=True
        )
        if result.returncode == 0:
            return jsonify({"ok": True, "message": "Nenhuma alteração para publicar."})

        subprocess.run(["git", "commit", "-m", message], cwd=repo_dir, check=True, capture_output=True)
        push = subprocess.run(["git", "push"], cwd=repo_dir, capture_output=True, text=True)

        if push.returncode != 0:
            return jsonify({"ok": False, "error": push.stderr or "Erro ao enviar para GitHub."})

        return jsonify({"ok": True, "message": "Publicado com sucesso no GitHub Pages!"})
    except subprocess.CalledProcessError as e:
        return jsonify({"ok": False, "error": e.stderr.decode() if e.stderr else str(e)})
    except FileNotFoundError:
        return jsonify({"ok": False, "error": "Git não encontrado. Instale o Git e configure o repositório."})


@app.route("/api/git-status")
def git_status():
    repo_dir = SITE_DIR.parent
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_dir, capture_output=True, text=True, check=True
        )
        return jsonify({"ok": True, "has_changes": bool(result.stdout.strip())})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/site/<path:filename>")
def site_files(filename):
    return send_from_directory(SITE_DIR, filename)


if __name__ == "__main__":
    import webbrowser
    import threading

    cfg = load_config()
    host = cfg["server"].get("host", "127.0.0.1")
    port = int(cfg["server"].get("port", 5001))
    open_host = "localhost" if host in ("0.0.0.0", "127.0.0.1", "") else host

    def open_browser():
        import time
        time.sleep(1)
        webbrowser.open(f"http://{open_host}:{port}")

    threading.Thread(target=open_browser, daemon=True).start()
    print(f"\n✓ Divina Lolla Admin iniciado em http://{open_host}:{port}")
    if host == "0.0.0.0":
        print("  (acessível na rede local por outros dispositivos)")
    print("  Pressione Ctrl+C para parar.\n")
    app.run(debug=False, host=host, port=port)
