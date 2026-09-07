#!/bin/bash
# Divina Lolla — iniciar painel admin no macOS/Linux
# Dê dois cliques neste arquivo (ou rode: ./iniciar.command)
cd "$(dirname "$0")"

echo "Verificando o que o painel precisa..."
# Num Mac sem as Ferramentas de Linha de Comando, /usr/bin/python3 e /usr/bin/git
# existem como atalhos que não rodam. Por isso o teste executa cada um em vez de
# só procurar o caminho.
if ! python3 --version >/dev/null 2>&1; then
  echo ""
  echo "ERRO: o Python não está disponível neste Mac."
  echo ""
  echo "Ele vem nas Ferramentas de Linha de Comando da Apple, junto com o Git,"
  echo "que o painel também usa para publicar. Uma janela vai abrir pedindo"
  echo "para instalar: clique em \"Instalar\", espere terminar (leva alguns"
  echo "minutos) e dê dois cliques neste arquivo de novo."
  xcode-select --install >/dev/null 2>&1
  echo ""
  read -n 1 -s -r -p "Pressione qualquer tecla para sair..."
  exit 1
fi

if ! git --version >/dev/null 2>&1; then
  echo ""
  echo "AVISO: o Git não está disponível, então o botão Publicar não vai funcionar."
  echo "O painel abre normalmente e suas peças ficam salvas. Para publicar,"
  echo "instale as Ferramentas de Linha de Comando da Apple com o comando:"
  echo "  xcode-select --install"
  echo ""
fi

if [ ! -d "venv" ]; then
  echo "Criando ambiente virtual..."
  python3 -m venv venv
fi

echo "Ativando ambiente virtual..."
source venv/bin/activate

echo "Instalando dependências..."
pip install -r requirements.txt --quiet --disable-pip-version-check

echo ""
echo "Iniciando Divina Lolla Admin..."
echo "Pressione Ctrl+C para parar."
echo ""

python admin/app.py
