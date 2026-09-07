import os
import io
import json
import hmac
import time
import uuid
import base64
import secrets
import mimetypes
import subprocess
import urllib.request
import urllib.error
from datetime import timedelta
from pathlib import Path
from flask import (
    Flask, request, jsonify, send_from_directory, render_template,
    session, redirect, url_for,
)

BASE_DIR = Path(__file__).parent

# Hospedado, o painel trabalha num clone do repositório feito no boot, porque o
# disco desses serviços é efêmero e o GitHub é o armazenamento de verdade.
# Sem REPO_DIR, o comportamento é o de sempre: a pasta do próprio projeto.
_repo_dir = os.environ.get("REPO_DIR", "").strip()
REPO_ROOT = Path(_repo_dir).expanduser() if _repo_dir else BASE_DIR.parent

# A pasta do site chama-se "docs" porque o GitHub Pages só serve a raiz
# do repositório ou /docs quando publica a partir de uma branch.
SITE_DIR = REPO_ROOT / "docs"
PRODUCTS_JSON = SITE_DIR / "products.json"
IMAGES_DIR = SITE_DIR / "images"
CONFIG_JSON = BASE_DIR / "config.json"
# Credencial de publicação. No pacote de desktop ela viaja em chave/publicar;
# hospedado, o entrypoint grava num caminho fora do repositório e aponta
# PUBLISH_KEY_PATH para lá. Vale só para este repositório e nunca é versionada.
_key_path = os.environ.get("PUBLISH_KEY_PATH", "").strip()
PUBLISH_KEY = Path(_key_path).expanduser() if _key_path else BASE_DIR.parent / "chave" / "publicar"
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


# ─── Senha do painel ──────────────────────────────────────────────────────────
# A senha só existe quando ADMIN_PASSWORD está no ambiente. Sem ela, o painel
# roda como sempre rodou — o que é seguro porque escuta em 127.0.0.1, alcançável
# apenas pela própria máquina. Hospedado, sem senha, seria um formulário público
# de edição do site: por isso as duas travas mais abaixo se recusam a subir.
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
AUTH_ENABLED = bool(ADMIN_PASSWORD)

# Hospedado, cada alteração já vai para o site. O disco desses serviços é
# efêmero: o que ficasse esperando o botão Publicar sumiria no próximo
# reinício, sem aviso. No pacote de desktop nada muda — lá o arquivo fica no
# computador e publicar continua sendo uma decisão de quem cadastra.
AUTO_PUBLISH = os.environ.get(
    "AUTO_PUBLISH", "1" if _repo_dir else "0"
).strip() not in ("", "0")

# Chave de sessão fixa entre reinícios quando informada; sem ela, todo restart
# desloga quem estava dentro.
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # Atrás de HTTPS o cookie não deve trafegar em claro. Localmente não há
    # HTTPS, e exigir isso impediria o login.
    SESSION_COOKIE_SECURE=os.environ.get("FORCE_HTTPS", "").strip() not in ("", "0"),
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
)

# Hospedado é justamente onde a senha não pode faltar.
if _repo_dir and not AUTH_ENABLED:
    raise RuntimeError(
        "REPO_DIR indica painel hospedado, mas ADMIN_PASSWORD não foi definida. "
        "Sem senha o painel ficaria aberto na internet: qualquer pessoa com o "
        "endereço poderia apagar o catálogo e publicar no site."
    )

# Rotas que a sessão não guarda: a própria tela de login, os arquivos estáticos
# e a API de catálogo, que tem o seu próprio token.
OPEN_ENDPOINTS = {"login", "logout", "static", "catalog_get", "catalog_put"}

MAX_TENTATIVAS = 5
BLOQUEIO_SEGUNDOS = 60
_tentativas = {}  # ip -> [falhas, momento da última]


def _bloqueio_restante(ip):
    falhas, quando = _tentativas.get(ip, (0, 0.0))
    if falhas < MAX_TENTATIVAS:
        return 0
    faltam = int(BLOQUEIO_SEGUNDOS - (time.time() - quando))
    if faltam <= 0:
        _tentativas.pop(ip, None)
        return 0
    return faltam


def _registrar_falha(ip):
    falhas, _ = _tentativas.get(ip, (0, 0.0))
    _tentativas[ip] = (falhas + 1, time.time())


def logado():
    return bool(session.get("auth"))


@app.before_request
def _exigir_login():
    if not AUTH_ENABLED or logado() or request.endpoint in OPEN_ENDPOINTS:
        return None
    # Chamada de tela devolve JSON; navegação vai para o login.
    if request.path.startswith("/api/"):
        return jsonify({"error": "Sessão expirada. Entre de novo para continuar."}), 401
    # full_path deixa um "?" solto quando não há query; ele iria para a barra
    # de endereços depois do login.
    return redirect(url_for("login", next=request.full_path.rstrip("?")))


@app.route("/login", methods=["GET", "POST"])
def login():
    if not AUTH_ENABLED:
        return redirect("/")

    erro = None
    ip = request.remote_addr or "?"

    if request.method == "POST":
        faltam = _bloqueio_restante(ip)
        if faltam:
            erro = f"Muitas tentativas erradas. Espere {faltam} segundos."
        elif hmac.compare_digest(request.form.get("password", ""), ADMIN_PASSWORD):
            session.clear()
            session["auth"] = True
            session.permanent = True
            _tentativas.pop(ip, None)
            destino = request.args.get("next") or "/"
            # Só caminho interno: "//outro.site" seria um redirecionamento externo.
            if not destino.startswith("/") or destino.startswith("//"):
                destino = "/"
            return redirect(destino)
        else:
            _registrar_falha(ip)
            erro = "Senha incorreta."

    return render_template("login.html", erro=erro), (401 if erro else 200)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login") if AUTH_ENABLED else "/")


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


def _git_env(extra=None):
    """Ambiente dos comandos git, já com a credencial de publicação do pacote.

    Quando a chave vem junto, o git usa só ela — nem agente SSH, nem chave
    pessoal. É o que permite o painel publicar numa máquina onde ninguém
    configurou GitHub à mão.
    """
    env = dict(os.environ)
    if PUBLISH_KEY.exists():
        # Descompactar o pacote costuma deixar a permissão aberta, e aí o ssh
        # recusa a chave.
        try:
            os.chmod(PUBLISH_KEY, 0o600)
        except OSError:
            pass
        env["GIT_SSH_COMMAND"] = (
            f'ssh -i "{PUBLISH_KEY}" -o IdentitiesOnly=yes -o IdentityAgent=none'
            f" -o StrictHostKeyChecking=accept-new"
        )
    env.update(extra or {})
    return env


def _git(repo_dir, *args, env=None):
    return subprocess.run(
        ["git", *args], cwd=repo_dir, capture_output=True, text=True, env=_git_env(env)
    )


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
    # O botão de sair só faz sentido quando há uma sessão para encerrar.
    return render_template("index.html", auth=AUTH_ENABLED)


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
    aviso = _auto_publicar("Atualizar dados da loja")
    return jsonify({"ok": True, "aviso": aviso})


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
    aviso = _auto_publicar(f"Cadastrar {product['name'] or 'peça'}")
    return jsonify({"ok": True, "product": product, "aviso": aviso})


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
    aviso = _auto_publicar(f"Editar {product['name'] or 'peça'}")
    return jsonify({"ok": True, "product": product, "aviso": aviso})


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
    aviso = _auto_publicar(f"Remover {product.get('name') or 'peça'}")
    return jsonify({"ok": True, "aviso": aviso})


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
    # Servidor remoto sem URL deixaria o painel sem de onde ler os produtos, e
    # a tela abriria vazia sem explicar por quê.
    if cfg["dataSource"]["mode"] == "remote" and not (cfg["dataSource"].get("remoteUrl") or "").strip():
        return jsonify({
            "ok": False,
            "error": "Para usar um servidor remoto, informe a URL do catálogo. "
                     "Sem ela o painel não teria de onde ler os produtos. "
                     "Se você não tem um servidor, use \"Arquivo local\".",
        }), 400
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
    if required and hmac.compare_digest(request.headers.get("X-Api-Token", ""), required):
        return True
    if logado():
        return True
    # Sem senha e sem token, a API segue aberta como antes — o que só é seguro
    # porque nesse caso o painel escuta em 127.0.0.1. Com senha configurada
    # (painel hospedado), liberar aqui seria reabrir a porta por outro caminho.
    return not AUTH_ENABLED and not required


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


# ─── Juntar catálogos que foram editados em paralelo ──────────────────────────
def _explain_git_error(stderr):
    """Traduz os erros de git mais comuns para algo que dê para agir."""
    t = (stderr or "").lower()
    # Rede primeiro: "access rights" aparece no rodapé de quase toda falha de
    # SSH do git, inclusive quando o problema foi só de conexão.
    if any(x in t for x in ("could not resolve host", "network is unreachable",
                            "timed out", "connection refused", "no route to host",
                            "temporary failure in name resolution")):
        return "Sem conexão com a internet. Conecte e tente publicar de novo."
    if "permission denied" in t or "publickey" in t:
        return ("O GitHub recusou a credencial de publicação. Ela pode ter sido "
                "revogada, ou a pasta 'chave' pode ter ficado de fora ao copiar "
                "o painel. Suas peças continuam salvas aqui — chame o Rafael.")
    if any(x in t for x in ("non-fast-forward", "fetch first", "[rejected]")):
        return ("A outra máquina publicou algo novo nesse meio-tempo. Clique em "
                "Publicar mais uma vez para juntar as alterações e enviar.")
    return (stderr or "").strip() or "Erro ao enviar para o GitHub."


def _merge_names(base, remote, local):
    """Une duas listas de nomes respeitando o que cada lado removeu."""
    b, r, l = set(base), set(remote), set(local)
    keep = (r | l) - (b - (r & l))
    return [n for n in remote if n in keep] + [n for n in local if n in keep and n not in remote]


def _by_id(catalog):
    return {p["id"]: p for p in catalog.get("products", []) if p.get("id")}


def _merge_catalog(base, remote, local):
    """Combina dois catálogos editados ao mesmo tempo em máquinas diferentes.

    Produtos são aditivos: o que cada máquina cadastrou é preservado. O que já
    existia e saiu de um dos lados conta como exclusão. Quando as duas mexeram
    no mesmo produto, vale a versão de quem está publicando agora.
    """
    b, r, l = _by_id(base), _by_id(remote), _by_id(local)

    order = [p["id"] for p in remote.get("products", []) if p.get("id")]
    order += [p["id"] for p in local.get("products", []) if p.get("id") and p["id"] not in order]

    products = []
    for pid in order:
        if pid in b and (pid not in r or pid not in l):
            continue  # apagado de um dos lados
        if pid in r and pid in l:
            products.append(l[pid] if l[pid] != b.get(pid) else r[pid])
        else:
            products.append(l[pid] if pid in l else r[pid])

    merged = dict(local)  # loja e contato: vale quem publica
    merged["products"] = products
    merged["categories"] = _merge_names(
        base.get("categories", []), remote.get("categories", []), local.get("categories", [])
    )
    return _normalize(merged)


def _catalog_stage(repo_dir, stage, rel_path):
    """Lê uma das versões do arquivo em conflito (1=base, 2=remoto, 3=local)."""
    out = _git(repo_dir, "show", f":{stage}:{rel_path}")
    if out.returncode != 0 or not out.stdout.strip():
        # Sem base: o arquivo foi criado nos dois lados. Catálogo vazio como base
        # faz a junção virar simples união, que é o desejado.
        return json.loads(json.dumps(DEFAULT_CATALOG))
    try:
        return _normalize(json.loads(out.stdout))
    except json.JSONDecodeError:
        return None


def _resolve_catalog_conflict(repo_dir, unmerged):
    """Resolve o conflito do products.json juntando os dois catálogos.

    Só age quando o products.json é o único arquivo em conflito: para qualquer
    outra coisa é mais seguro abortar e avisar do que adivinhar.
    """
    rel = PRODUCTS_JSON.relative_to(repo_dir).as_posix()
    if unmerged != [rel]:
        return False
    versions = [_catalog_stage(repo_dir, n, rel) for n in (1, 2, 3)]
    if any(v is None for v in versions):
        return False
    base, remote, local = versions
    with open(PRODUCTS_JSON, "w", encoding="utf-8") as f:
        json.dump(_merge_catalog(base, remote, local), f, ensure_ascii=False, indent=2)
    return _git(repo_dir, "add", rel).returncode == 0


def _sync_with_remote(repo_dir):
    """Traz o que a outra máquina publicou. Devolve (ok, pulled, merged, erro)."""
    fetch = _git(repo_dir, "fetch", "origin")
    if fetch.returncode != 0:
        return False, False, False, _explain_git_error(fetch.stderr)

    upstream = _git(repo_dir, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    ref = upstream.stdout.strip() if upstream.returncode == 0 else "origin/main"

    behind = _git(repo_dir, "rev-list", "--count", f"HEAD..{ref}")
    if behind.returncode != 0 or behind.stdout.strip() == "0":
        return True, False, False, None  # nada novo lá fora

    env = {"GIT_EDITOR": "true"}
    merged = False
    rebase = _git(repo_dir, "rebase", ref, env=env)
    for _ in range(20):
        if rebase.returncode == 0:
            return True, True, merged, None
        unmerged = _git(repo_dir, "diff", "--name-only", "--diff-filter=U").stdout.split()
        if not unmerged:
            # Parou sem conflito: a alteração já existe lá. Pula esse passo.
            rebase = _git(repo_dir, "rebase", "--skip", env=env)
        elif _resolve_catalog_conflict(repo_dir, unmerged):
            merged = True
            rebase = _git(repo_dir, "rebase", "--continue", env=env)
        else:
            break

    _git(repo_dir, "rebase", "--abort")
    return False, False, False, (
        "A outra máquina publicou alterações que batem de frente com as suas. "
        "Nada foi perdido: suas edições continuam salvas aqui. Para resolver, "
        "abra a pasta do projeto no terminal e rode: git status"
    )


# ─── Publicação no GitHub Pages ───────────────────────────────────────────────
def _repo_ready(repo_dir):
    inside = _git(repo_dir, "rev-parse", "--is-inside-work-tree")
    return inside.returncode == 0


@app.route("/api/sync", methods=["POST"])
def sync():
    """Baixa o que as outras máquinas publicaram, sem enviar nada."""
    repo_dir = SITE_DIR.parent
    if not _repo_ready(repo_dir):
        return jsonify({"ok": False, "error": "Não há repositório GitHub configurado."})
    try:
        # Guarda edições ainda não publicadas para o rebase poder rodar.
        _git(repo_dir, "add", "-A")
        if _git(repo_dir, "diff", "--cached", "--quiet").returncode != 0:
            _git(repo_dir, "commit", "-m", "Alterações locais antes de sincronizar")
        ok, pulled, merged, err = _sync_with_remote(repo_dir)
        if not ok:
            return jsonify({"ok": False, "error": err})
        if not pulled:
            return jsonify({"ok": True, "message": "Você já está com a versão mais recente."})
        return jsonify({
            "ok": True,
            "changed": True,
            "message": ("Alterações da outra máquina juntadas ao seu catálogo. "
                        if merged else "Catálogo atualizado com o que a outra máquina publicou. ")
                       + "Recarregue a página para ver.",
        })
    except FileNotFoundError:
        return jsonify({"ok": False, "error": "Git não encontrado. Rode: xcode-select --install"})


def _publicar(message):
    """Envia o catálogo para o site. Devolve o mesmo dicionário que a tela recebe."""
    repo_dir = SITE_DIR.parent

    # "Publicar" só faz sentido para enviar ao site online (GitHub Pages).
    # Localmente o catálogo já é atualizado ao salvar — não precisa publicar.
    if not _repo_ready(repo_dir):
        return {
            "ok": False,
            "local_only": True,
            "error": "Ainda não há um repositório GitHub configurado, então não há site online para atualizar. "
                     "As alterações já valem no site local automaticamente. "
                     "Para publicar na internet, siga o guia CONFIGURAR-GITHUB.md.",
        }

    try:
        _git(repo_dir, "add", "-A")
        nothing_new = _git(repo_dir, "diff", "--cached", "--quiet").returncode == 0
        if not nothing_new:
            commit = _git(repo_dir, "commit", "-m", message)
            if commit.returncode != 0:
                return {
                    "ok": False,
                    "error": commit.stderr.strip() or "Erro ao registrar as alterações.",
                }

        # Outra máquina pode ter publicado nesse meio-tempo: junta antes de enviar,
        # senão o push é recusado pelo GitHub.
        ok, pulled, merged, err = _sync_with_remote(repo_dir)
        if not ok:
            return {"ok": False, "error": err}

        ahead = _git(repo_dir, "rev-list", "--count", "@{u}..HEAD")
        if ahead.returncode == 0 and ahead.stdout.strip() == "0":
            if pulled:
                return {
                    "ok": True,
                    "changed": True,
                    "message": "Nada seu para enviar, mas trouxe o que a outra máquina publicou. "
                               "Recarregue a página para ver.",
                }
            return {"ok": True, "message": "Nenhuma alteração para publicar."}

        push = _git(repo_dir, "push")
        if push.returncode != 0:
            return {"ok": False, "error": _explain_git_error(push.stderr)}

        if merged:
            return {
                "ok": True,
                "changed": True,
                "message": "Publicado! As alterações da outra máquina foram juntadas ao seu "
                           "catálogo — recarregue a página para vê-las.",
            }
        return {"ok": True, "message": "Publicado com sucesso no GitHub Pages!"}
    except FileNotFoundError:
        return {"ok": False, "error": "Git não encontrado. Rode: xcode-select --install"}


def _auto_publicar(descricao):
    """No painel hospedado, salva já significa publicar.

    Esses serviços têm disco efêmero: o que ficasse só no servidor sumiria no
    próximo reinício. Devolve um aviso quando o envio falha — a peça continua
    salva, mas quem cadastrou precisa saber que o site não recebeu.
    """
    if not AUTO_PUBLISH:
        return None
    resultado = _publicar(descricao)
    if resultado.get("ok"):
        return None
    return resultado.get("error") or "A peça foi salva, mas o site não recebeu a alteração."


@app.route("/api/publish", methods=["POST"])
def publish():
    body = request.json or {}
    message = body.get("message", "Atualizar catálogo de produtos").strip() or "Atualizar catálogo"
    return jsonify(_publicar(message))


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

    # Escutar fora do 127.0.0.1 expõe o painel à rede. Sem senha, quem chegasse
    # nele apagaria o catálogo e publicaria no site — então melhor não subir.
    if host not in ("127.0.0.1", "localhost", "::1") and not AUTH_ENABLED:
        raise SystemExit(
            f"\nO painel está configurado para escutar em {host}, o que o deixa\n"
            "acessível a outros aparelhos, mas nenhuma senha foi definida.\n\n"
            "Defina uma senha antes de subir assim:\n"
            "    ADMIN_PASSWORD='sua-senha' python admin/app.py\n\n"
            "Ou volte a fonte para 127.0.0.1 na tela de Configurações.\n"
        )

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
