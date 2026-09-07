#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
#  Divina Lolla — monta o pacote para entregar a outra pessoa
#
#  Gera DivinaLolla.zip na Área de Trabalho, contendo o painel, o histórico
#  do repositório e a credencial de publicação. Quem recebe descompacta e dá
#  dois cliques em iniciar.command — sem configurar nada.
#
#  O .zip carrega uma credencial de escrita neste repositório: trate como
#  senha e entregue por canal privado.
# ─────────────────────────────────────────────────────────────────────────────
set -u
cd "$(dirname "$0")"

PROJETO="$(pwd)"
DESTINO="${DIVINA_ZIP:-$HOME/Desktop/DivinaLolla.zip}"
STAGE="$(mktemp -d)/DivinaLolla"

trap 'rm -rf "$(dirname "$STAGE")"' EXIT

titulo() { printf '\n\033[1m%s\033[0m\n' "$1"; }
erro()   { printf '\n\033[31mERRO: %s\033[0m\n' "$1"; }

titulo "Montando o pacote"

if [ ! -f "$PROJETO/chave/publicar" ]; then
  erro "A credencial de publicação não está em chave/publicar."
  echo "Sem ela o pacote não consegue publicar. Veja CONFIGURAR-GITHUB.md."
  read -n 1 -s -r -p "Pressione qualquer tecla para sair..."; exit 1
fi

# Cópia limpa: o ambiente Python é recriado na máquina de destino, e os
# arquivos de sistema do macOS não têm por que viajar.
mkdir -p "$STAGE"
rsync -a \
  --exclude 'venv/' \
  --exclude '__pycache__/' \
  --exclude '.DS_Store' \
  --exclude 'DivinaLolla.zip' \
  "$PROJETO"/ "$STAGE"/ || { erro "Falha ao copiar os arquivos."; exit 1; }

# Identidade neutra: os commits feitos de outra máquina aparecem como vindos
# do painel, não com o nome de quem montou o pacote.
git -C "$STAGE" config user.name "Painel Divina Lolla"
git -C "$STAGE" config user.email "painel@divinalolla.local"

# Deixa o histórico enxuto e garante que o clone aponta para o repositório
# certo por SSH, que é o que a credencial atende.
git -C "$STAGE" remote set-url origin git@github.com:rafaelcsouza1/divina-lolla.git

chmod 700 "$STAGE/chave"
chmod 600 "$STAGE/chave/publicar"
chmod +x "$STAGE/iniciar.command" "$STAGE/empacotar.command"

titulo "Compactando"
rm -f "$DESTINO"
# -X descarta os metadados extras do macOS, que só incham o arquivo.
( cd "$(dirname "$STAGE")" && zip -qrX "$DESTINO" "DivinaLolla" ) \
  || { erro "Falha ao compactar."; exit 1; }

TAMANHO="$(du -h "$DESTINO" | cut -f1 | tr -d ' ')"

titulo "Pacote pronto"
echo "  $DESTINO  ($TAMANHO)"
echo
echo "Entregue por canal privado (não poste em grupo nem em nuvem pública):"
echo "o pacote contém a credencial que publica no catálogo."
echo
read -n 1 -s -r -p "Pressione qualquer tecla para fechar..."
printf '\n'
