#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
#  Divina Lolla — instalador para Mac
#  Dê dois cliques neste arquivo. Ele baixa o painel, prepara tudo e avisa
#  se ainda falta liberar o acesso para publicar.
# ─────────────────────────────────────────────────────────────────────────────
set -u

REPO_HTTPS="https://github.com/rafaelcsouza1/divina-lolla.git"
REPO_SSH="git@github.com:rafaelcsouza1/divina-lolla.git"
DEST="${DIVINA_DEST:-$HOME/DivinaLolla}"
CHAVE="$HOME/.ssh/id_ed25519"

titulo() { printf '\n\033[1m%s\033[0m\n' "$1"; }
erro()   { printf '\n\033[31mERRO: %s\033[0m\n' "$1"; }
pausa()  { printf '\n'; read -n 1 -s -r -p "Pressione qualquer tecla para fechar..."; printf '\n'; }

titulo "Divina Lolla — instalacao"

# ── 1. Git ───────────────────────────────────────────────────────────────────
if ! command -v git >/dev/null 2>&1; then
  erro "O Git nao esta instalado."
  echo "Uma janela vai abrir pedindo para instalar as ferramentas de linha de"
  echo "comando. Clique em \"Instalar\", espere terminar e rode este arquivo de novo."
  xcode-select --install >/dev/null 2>&1
  pausa; exit 1
fi

# ── 2. Python ────────────────────────────────────────────────────────────────
if ! command -v python3 >/dev/null 2>&1; then
  erro "O Python 3 nao esta instalado."
  echo "Baixe em https://python.org (botao \"Download Python\"), instale e rode"
  echo "este arquivo de novo."
  pausa; exit 1
fi

# ── 3. Baixar o painel ───────────────────────────────────────────────────────
if [ -d "$DEST/.git" ]; then
  titulo "Painel ja instalado em $DEST — atualizando"
  git -C "$DEST" pull --rebase --autostash || erro "Nao foi possivel atualizar. Seguindo com a versao local."
else
  titulo "Baixando o painel para $DEST"
  # Clone por HTTPS: o repositorio e publico, entao isso funciona sem
  # nenhuma configuracao de acesso. O envio (push) usa SSH, configurado abaixo.
  if ! git clone -q "$REPO_HTTPS" "$DEST"; then
    erro "Nao foi possivel baixar. Confira a conexao com a internet."
    pausa; exit 1
  fi
fi

# ── 4. Identidade dos commits ────────────────────────────────────────────────
if [ -z "$(git -C "$DEST" config user.name || true)" ]; then
  NOME="$(id -F 2>/dev/null || echo "Divina Lolla")"
  git -C "$DEST" config user.name "$NOME"
  git -C "$DEST" config user.email "divina-lolla@local"
fi

# ── 5. Ambiente Python ───────────────────────────────────────────────────────
titulo "Preparando o ambiente Python"
if [ ! -d "$DEST/venv" ]; then
  python3 -m venv "$DEST/venv" || { erro "Falha ao criar o ambiente."; pausa; exit 1; }
fi
"$DEST/venv/bin/pip" install -r "$DEST/requirements.txt" --quiet --disable-pip-version-check \
  || { erro "Falha ao instalar as dependencias."; pausa; exit 1; }

# ── 6. Chave de acesso para publicar ─────────────────────────────────────────
if [ ! -f "$CHAVE" ]; then
  titulo "Criando a chave de acesso deste Mac"
  mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
  ssh-keygen -t ed25519 -N "" -C "divina-lolla-$(hostname -s)" -f "$CHAVE" -q
fi
git -C "$DEST" remote set-url origin "$REPO_SSH"

titulo "Testando o acesso para publicar"
# Testa exatamente a chave deste Mac, ignorando qualquer agente SSH: e ela
# que o git vai usar para publicar.
ssh -T -i "$CHAVE" -o IdentitiesOnly=yes -o IdentityAgent=none \
    -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 \
    git@github.com 2>&1 | grep -q "successfully authenticated"
ACESSO=$?

if [ $ACESSO -ne 0 ]; then
  printf '\n\033[33m─────────────────────────────────────────────────────────────\033[0m\n'
  printf '\033[1mFALTA UM PASSO: liberar este Mac para publicar\033[0m\n'
  printf '\033[33m─────────────────────────────────────────────────────────────\033[0m\n\n'
  echo "Copie o texto abaixo INTEIRO e mande para o Rafael."
  echo "Ele libera o acesso e ai voce pode publicar."
  echo
  printf '\033[36m%s\033[0m\n' "$(cat "$CHAVE.pub")"
  echo
  echo "Enquanto isso o painel ja funciona: voce pode cadastrar produtos"
  echo "e ver o site local. So o botao Publicar fica esperando a liberacao."
else
  printf '\n\033[32mAcesso para publicar: OK\033[0m\n'
fi

titulo "Instalacao concluida"
echo "O painel esta em:  $DEST"
echo "Para abrir, de dois cliques em:  $DEST/iniciar.command"
echo
read -n 1 -s -r -p "Quer abrir o painel agora? (s = sim, qualquer outra tecla = nao) " R
printf '\n'
if [ "$R" = "s" ] || [ "$R" = "S" ]; then
  exec "$DEST/iniciar.command"
fi
pausa
