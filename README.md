# 🏐 Vôlei Manager & Elo System

Um sistema web interativo para gerenciar partidas de vôlei recreativo, equilibrar times automaticamente e manter um ranking competitivo baseado no algoritmo **Elo Rating** (o mesmo usado no Xadrez e E-Sports).

## 📋 Funcionalidades

* **Algoritmo de Equilíbrio:** Sorteia times equilibrados baseados na pontuação (Elo) dos jogadores presentes, garantindo partidas disputadas.
* **Ranking Elo Dinâmico:** Atualiza a pontuação dos jogadores após cada partida (K-Factor = 32).
* **Gestão de Fila de Espera:** Gerencia automaticamente quem está fora, dando prioridade para quem esperou mais.
* **Modo "Rei da Quadra" Configurável:** Permite definir um limite de vitórias consecutivas (2 a 6). Ao atingir o limite, o time vencedor é dissolvido e misturado para garantir rotatividade.
* **Multi-Grupos:** Suporte para gerenciar diferentes grupos de amigos (ex: "Vôlei de Terça", "Parque da Cidade") no mesmo sistema, mantendo rankings e históricos separados.
* **Histórico de Partidas:** Registro completo de todas os jogos com data, times e vencedor.
* **Integração com Google Sheets:** Banco de dados gratuito, acessível e fácil de editar manualmente se necessário.

## 🛠️ Tecnologias Utilizadas

* **Python:** Linguagem principal.
* **Streamlit:** Framework para criação da interface web.
* **Pandas:** Manipulação de dados e lógica de balanceamento.
* **Google Sheets API:** Persistência de dados.

## 🚀 Como Rodar Localmente

### Pré-requisitos

* Python instalado.
* Uma conta no Google Cloud Platform (para configurar a API do Google Sheets).

### 1. Clonar o repositório

```bash
git clone https://github.com/seu-usuario/volei-manager.git
cd volei-manager

```

### 2. Instalar dependências

Crie um arquivo `requirements.txt` (se não houver) e instale:

```bash
pip install -r requirements.txt

```

*Conteúdo do requirements.txt:*

```text
streamlit
streamlit-gsheets
pandas
st-gsheets-connection

```

### 3. Configurar o Google Sheets

1. Crie uma planilha no Google Sheets.
2. Crie duas abas na planilha: `Jogadores` e `Historico`.
* **Jogadores:** Deve ter as colunas `Nome`, `Elo`, `Partidas`, `Vitorias`, `Grupo`.
* **Historico:** Pode começar vazia (o sistema cria as colunas).


3. Obtenha o link de compartilhamento da planilha (certifique-se de que está público para leitura/escrita ou configure as credenciais de serviço).

### 4. Configurar Segredos (.toml)

Crie uma pasta `.streamlit` na raiz do projeto e um arquivo `secrets.toml` dentro dela:

```toml
[connections.gsheets]
spreadsheet = "https://docs.google.com/spreadsheets/d/SEU_ID_DA_PLANILHA/edit"

```

### 5. Executar o App

```bash
streamlit run app.py

```

## ☁️ Deploy no Streamlit Cloud

Este projeto é otimizado para rodar gratuitamente no **Streamlit Cloud**:

1. Suba seu código para o **GitHub**.
2. Acesse [share.streamlit.io](https://share.streamlit.io).
3. Conecte seu repositório e selecione o arquivo `app.py`.
4. Nas **Advanced Settings** do Streamlit Cloud, adicione o conteúdo do seu `secrets.toml` na área de "Secrets".
5. Clique em **Deploy**.

## 🧠 Como Funciona o Cálculo Elo

O sistema utiliza a fórmula padrão do Elo Rating:

1. **Expectativa:** O sistema calcula a probabilidade de vitória do Time A contra o Time B baseada na média de Elo dos jogadores.
2. **Resultado:**
* Se o time favorito ganha, eles ganham poucos pontos (pois já era esperado).
* Se o time "zebra" (menor Elo) ganha, eles ganham muitos pontos.


3. **K-Factor (32):** Determina a volatilidade do ranking. Usamos 32 para permitir que novatos cheguem ao seu nível real rapidamente.

## 📂 Estrutura de Arquivos

```
/
├── app.py                # Código fonte principal
├── requirements.txt      # Dependências do Python
├── .streamlit/
│   └── secrets.toml      # Credenciais (NÃO COMMITAR NO GITHUB)
└── README.md             # Documentação

```

## 🤝 Contribuição

Sinta-se à vontade para abrir **Issues** ou enviar **Pull Requests** com melhorias na lógica de balanceamento ou novas funcionalidades.

---

**Desenvolvido por Bruno Bismarck** - 2026
