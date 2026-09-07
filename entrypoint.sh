#!/bin/sh
# Prepara o painel hospedado e sobe o servidor.
#
# Cada boot: grava a credencial vinda do ambiente, deixa o clone do repositório
# igual ao GitHub e entrega o processo ao gunicorn.
set -eu

falta() {
  echo "ERRO: a variável $1 não foi definida." >&2
  echo "$2" >&2
  exit 1
}

[ -n "${ADMIN_PASSWORD:-}" ] || falta ADMIN_PASSWORD \
  "Sem senha o painel ficaria aberto na internet: qualquer pessoa com o endereço
poderia apagar o catálogo e publicar no site. Defina uma senha e suba de novo."

[ -n "${PUBLISH_KEY_B64:-}" ] || falta PUBLISH_KEY_B64 \
  "É a credencial que publica no GitHub, em base64. Gere com:
  base64 -i chave/publicar | tr -d '\n'"

REPO_URL="${REPO_URL:-git@github.com:rafaelcsouza1/divina-lolla.git}"

mkdir -p "$(dirname "$PUBLISH_KEY_PATH")" "$(dirname "$REPO_DIR")"

# A chave viaja em base64 porque variável de ambiente não preserva as quebras
# de linha do formato original, e o ssh recusa a chave sem elas.
echo "$PUBLISH_KEY_B64" | base64 -d > "$PUBLISH_KEY_PATH"
chmod 600 "$PUBLISH_KEY_PATH"

export GIT_SSH_COMMAND="ssh -i $PUBLISH_KEY_PATH -o IdentitiesOnly=yes -o IdentityAgent=none -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/data/known_hosts"

if [ -d "$REPO_DIR/.git" ]; then
  echo "Atualizando o catálogo a partir do GitHub..."
  git -C "$REPO_DIR" fetch origin
  git -C "$REPO_DIR" reset --hard origin/main
else
  echo "Baixando o catálogo do GitHub..."
  # Clone completo de propósito: push a partir de clone raso é recusado por
  # alguns servidores, e o repositório é pequeno.
  git clone "$REPO_URL" "$REPO_DIR"
fi

git -C "$REPO_DIR" config user.name "Painel Divina Lolla"
git -C "$REPO_DIR" config user.email "painel@divinalolla.local"

echo "Painel pronto na porta ${PORT:-8080}."

# Um worker só, de propósito: o controle de tentativas de senha vive na memória
# do processo, e dois workers mexendo no mesmo clone git disputariam o índice.
exec gunicorn \
  --chdir /app/admin \
  --bind "0.0.0.0:${PORT:-8080}" \
  --workers 1 \
  --threads 4 \
  --timeout 180 \
  --access-logfile - \
  app:app
