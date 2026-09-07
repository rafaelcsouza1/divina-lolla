#!/bin/bash
# Divina Lolla — iniciar painel admin no macOS/Linux
# Dê dois cliques neste arquivo (ou rode: ./iniciar.command)
cd "$(dirname "$0")"

echo "Verificando Python..."
if ! command -v python3 >/dev/null 2>&1; then
  echo "ERRO: Python 3 não encontrado. Instale em https://python.org"
  read -n 1 -s -r -p "Pressione qualquer tecla para sair..."
  exit 1
fi

if [ ! -d "venv" ]; then
  echo "Criando ambiente virtual..."
  python3 -m venv venv
fi

echo "Ativando ambiente virtual..."
source venv/bin/activate

echo "Instalando dependências..."
pip install -r requirements.txt --quiet

echo ""
echo "Iniciando Divina Lolla Admin..."
echo "Acesse: http://localhost:5000"
echo "Pressione Ctrl+C para parar."
echo ""

python admin/app.py
