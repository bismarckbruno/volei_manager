import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
import time
import pytz

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Vôlei Manager", page_icon="🏐", layout="wide")
st.title("🏐 Vôlei Manager")

# --- CONSTANTES ---
K_FACTOR = 32
nome_padrao_caso_coluna_geral_inexistente = 'Vôleizin no Parque'

# --- CONEXÃO ---
conn = st.connection("gsheets", type=GSheetsConnection)

# --- INICIALIZAÇÃO DE ESTADO ---
def inicializar_session_state():
    chaves_padrao = {
        'fila_espera': [],
        'streak_vitorias': 0,
        'time_vencedor_anterior': None,
        'todos_presentes': [],
        'todos_levantadores': [],
        'grupo_atual': None
    }
    for chave, valor in chaves_padrao.items():
        if chave not in st.session_state:
            st.session_state[chave] = valor

inicializar_session_state()

# --- FUNÇÕES DE DADOS ---
def carregar_dados():
    if 'cache_jogadores' in st.session_state:
        return st.session_state['cache_jogadores']
    
    try:
        # ttl=0 garante que não cacheie no servidor do Streamlit, lendo sempre do Google
        df = conn.read(worksheet="Jogadores", ttl=0)
        df = df.dropna(how="all")
        
        cols_num = ['Elo', 'Partidas', 'Vitorias']
        for c in cols_num:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0 if c != 'Elo' else 1200)
        
        if 'Grupo' not in df.columns:
            df['Grupo'] = nome_padrao_caso_coluna_geral_inexistente
            conn.update(worksheet="Jogadores", data=df)
            
        st.session_state['cache_jogadores'] = df
        return df
    except Exception as e:
        st.error(f"⚠️ ERRO DETALHADO: {e}")
        st.code(str(e)) # Mostra o erro técnico
        st.stop()

# --- FUNÇÕES MATEMÁTICAS E LÓGICA ---
def calcular_novo_elo(rating_vencedor, rating_perdedor):
    expectativa_vencedor = 1 / (1 + 10 ** ((rating_perdedor - rating_vencedor) / 400))
    return rating_vencedor + K_FACTOR * (1 - expectativa_vencedor)

def distribuir_times_equilibrados(df_pool, levantadores_selecionados, tamanho_time):
    # Separa levantadores e outros
    levs = df_pool[df_pool['Nome'].isin(levantadores_selecionados)].sort_values(by='Elo', ascending=False).to_dict('records')
    outros = df_pool[~df_pool['Nome'].isin(levantadores_selecionados)].sort_values(by='Elo', ascending=False).to_dict('records')
    
    time_a = []
    time_b = []
    
    def alocar(jogador):
        # Tenta equilibrar primeiro por número de jogadores, depois por Elo
        if len(time_a) < tamanho_time and len(time_b) < tamanho_time:
            elo_a = sum(p['Elo'] for p in time_a)
            elo_b = sum(p['Elo'] for p in time_b)
            if elo_a <= elo_b: time_a.append(jogador)
            else: time_b.append(jogador)
        elif len(time_a) < tamanho_time: time_a.append(jogador)
        elif len(time_b) < tamanho_time: time_b.append(jogador)

    for p in levs: alocar(p)
    for p in outros: alocar(p)
    
    return pd.DataFrame(time_a), pd.DataFrame(time_b)

def processar_vitoria(time_venc, time_perd, nome_venc_str, grupo_selecionado, t_a_nomes, t_b_nomes):
    """Executa toda a lógica de atualização de Elo, Histórico e Streak"""
    
    mv, mp = time_venc['Elo'].mean(), time_perd['Elo'].mean()
    delta = calcular_novo_elo(mv, mp) - mv
    
    df_ram = st.session_state['cache_jogadores']
    
    # Atualiza Vencedores
    for n in time_venc['Nome']:
        idx = df_ram.index[(df_ram['Nome'] == n) & (df_ram['Grupo'] == grupo_selecionado)]
        if not idx.empty:
            df_ram.loc[idx, 'Elo'] += delta
            df_ram.loc[idx, 'Partidas'] += 1
            df_ram.loc[idx, 'Vitorias'] += 1
            
    # Atualiza Perdedores
    for n in time_perd['Nome']:
        idx = df_ram.index[(df_ram['Nome'] == n) & (df_ram['Grupo'] == grupo_selecionado)]
        if not idx.empty:
            df_ram.loc[idx, 'Elo'] -= delta
            df_ram.loc[idx, 'Partidas'] += 1
    
    # Salva no Google Sheets
    conn.update(worksheet="Jogadores", data=df_ram)
    st.session_state['cache_jogadores'] = df_ram

    # Atualiza Histórico
    try:
        fuso_br = pytz.timezone('America/Sao_Paulo')
        data_hora_atual = datetime.now(fuso_br).strftime("%d/%m %H:%M")
        
        df_h = conn.read(worksheet="Historico", ttl=0).dropna(how="all")
        novo_registro = pd.DataFrame([{
            "Data": data_hora_atual,
            "Time A": ", ".join(t_a_nomes), 
            "Time B": ", ".join(t_b_nomes), 
            "Vencedor": nome_venc_str,
            "Grupo": grupo_selecionado
        }])
        conn.update(worksheet="Historico", data=pd.concat([df_h, novo_registro], ignore_index=True))
    except Exception as e:
        print(f"Erro ao salvar histórico: {e}") # Log simples para não travar o app
        pass 
    
    # Lógica de Streak (Rei da Quadra)
    venc_nomes = time_venc['Nome'].tolist()
    anteriores = st.session_state.get('time_vencedor_anterior', [])
    
    # Se o time vencedor é exatamente o mesmo da rodada anterior
    if anteriores and set(venc_nomes) == set(anteriores):
        st.session_state['streak_vitorias'] += 1
    else:
        st.session_state['streak_vitorias'] = 1
        st.session_state['time_vencedor_anterior'] = venc_nomes
    
    st.toast(f"✅ Resultado salvo! +{delta:.1f} pontos Elo para cada integrante do time vencedor!")
    
    # Limpa o jogo atual para forçar nova organização
    if 'jogo_atual' in st.session_state:
        del st.session_state['jogo_atual']
    
    time.sleep(1)
    st.rerun()

# --- CARREGAMENTO INICIAL ---
df_geral = carregar_dados()

# --- SIDEBAR: SELEÇÃO DE GRUPO ---
with st.sidebar:
    st.header("👥 Grupos")
    
    grupos_opcoes = df_geral['Grupo'].unique().tolist()
    
    # Lógica para manter o grupo selecionado ou recém-criado na lista
    if st.session_state['grupo_atual'] and st.session_state['grupo_atual'] not in grupos_opcoes and st.session_state['grupo_atual'] != "➕ Criar novo...":
        grupos_opcoes.append(st.session_state['grupo_atual'])
            
    opcoes_finais = grupos_opcoes + ["➕ Criar novo..."]
    
    # Define índice padrão
    idx = 0
    if st.session_state['grupo_atual'] in opcoes_finais:
        idx = opcoes_finais.index(st.session_state['grupo_atual'])
        
    grupo_selecionado = st.selectbox("Selecionar grupo:", opcoes_finais, index=idx)
    
    # Criação de Novo Grupo
    if grupo_selecionado == "➕ Criar novo...":
        st.markdown("---")
        with st.form("form_cria_grupo"):
            st.subheader("Novo Grupo")
            novo_nome = st.text_input("Nome (ex: Vôlei Terça)")
            btn_criar = st.form_submit_button("Criar")
            
            if btn_criar and novo_nome:
                st.session_state['grupo_atual'] = novo_nome
                st.success(f"Grupo '{novo_nome}' criado!")
                time.sleep(0.5)
                st.rerun()
        st.info("Crie um nome para o grupo para liberar as outras funções.")
        st.stop()
    else:
        st.session_state['grupo_atual'] = grupo_selecionado

    st.divider()

# --- FILTRAGEM DO DATAFRAME PELO GRUPO ---
df_jogadores = df_geral[df_geral['Grupo'] == grupo_selecionado].copy()

# --- SIDEBAR: CONFIGURAÇÕES DA PARTIDA ---
with st.sidebar:
    st.header("⚙️ Configurações")
    tamanho_time = st.radio("Jogadores por time:", [2, 3, 4, 5, 6], index=4, horizontal=True)
    limite_vitorias = st.radio("Limite de vitórias:", [2, 3, 4, 5, 6], index=1, horizontal=True)
    
    st.divider()
    st.subheader("⏳ Fila de espera")
    placeholder_fila = st.empty() 
    
    st.divider()
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("🔄 Atualizar"):
            if 'cache_jogadores' in st.session_state: del st.session_state['cache_jogadores']
            st.rerun()
    with col_btn2:
        if st.button("⚠️ Resetar"):
            for key in ['jogo_atual', 'fila_espera', 'streak_vitorias', 'time_vencedor_anterior', 'todos_presentes']:
                if key in st.session_state: del st.session_state[key]
            st.rerun()

# --- ABAS ---
tab1, tab2, tab3 = st.tabs(["Quadra (Jogo)", "Ranking", "Histórico"])

# --- ABA 2: RANKING ---
with tab2:
    col_titulo, col_filtro = st.columns([1, 1])
    
    with col_titulo:
        st.markdown(f"### 🏆 Ranking: {grupo_selecionado}")
    
    with col_filtro:
        # Botão para escolher o tipo de visualização
        tipo_ranking = st.radio(
            "Visualização:", 
            ["Ranking Geral (Todos)", "Apenas quem jogou no último dia"], 
            horizontal=True,
            label_visibility="collapsed" # Esconde o rótulo para ficar mais limpo
        )

    if df_jogadores.empty:
        st.info(f"O grupo '{grupo_selecionado}' ainda não tem jogadores. Cadastre abaixo.")
    else:
        # Cria uma cópia para manipulação visual
        df_visual = df_jogadores.copy()
        
        # --- LÓGICA DE FILTRO (QUEM JOGOU RECENTEMENTE) ---
        if tipo_ranking == "Apenas quem jogou no último dia":
            try:
                # Lê o histórico para descobrir a última data
                df_h = conn.read(worksheet="Historico", ttl=0).dropna(how="all")
                
                # Garante coluna de grupo
                if 'Grupo' not in df_h.columns: df_h['Grupo'] = nome_padrao_caso_coluna_geral_inexistente
                
                # Filtra pelo grupo atual
                df_h_grupo = df_h[df_h['Grupo'] == grupo_selecionado]
                
                if not df_h_grupo.empty:
                    # Pega a data da última partida registrada (assumindo ordem de inserção)
                    ultima_data_completa = df_h_grupo.iloc[-1]['Data'] 
                    # Extrai apenas o dia/mês (ex: "16/01") para pegar todas partidas do dia
                    dia_referencia = ultima_data_completa.split(" ")[0] 
                    
                    st.caption(f"📅 Exibindo jogadores presentes em: **{dia_referencia}**")
                    
                    # Filtra linhas do histórico que contém essa data
                    jogos_do_dia = df_h_grupo[df_h_grupo['Data'].str.contains(dia_referencia, na=False)]
                    
                    # Extrai todos os nomes dos times A e B desses jogos
                    nomes_presentes = set()
                    for _, row in jogos_do_dia.iterrows():
                        nomes_presentes.update(row['Time A'].split(", "))
                        nomes_presentes.update(row['Time B'].split(", "))
                    
                    # Filtra o DataFrame principal de jogadores
                    df_visual = df_visual[df_visual['Nome'].isin(nomes_presentes)]
                    
                    if df_visual.empty:
                        st.warning("Nenhum jogador encontrado para a data filtrada.")
                else:
                    st.warning("Sem histórico para filtrar recentes. Mostrando geral.")
            except Exception as e:
                st.error(f"Erro ao filtrar histórico: {e}")

        # --- LÓGICA DE ORDENAÇÃO E MEDALHAS ---
        # Ordena por Elo (Do maior para o menor)
        df_visual = df_visual.sort_values(by="Elo", ascending=False).reset_index(drop=True)
        
        # Função para gerar as medalhas
        def gerar_posicao(index):
            pos = index + 1
            if pos == 1: return "🥇 1º"
            if pos == 2: return "🥈 2º"
            if pos == 3: return "🥉 3º"
            return f"{pos}º" # Retorna ordinal normal (4º, 5º...)

        # Cria a coluna de Posição como a primeira coluna
        if not df_visual.empty:
            df_visual.insert(0, 'Pos.', [gerar_posicao(i) for i in range(len(df_visual))])

        # Exibe a tabela bonitona
        st.dataframe(
            df_visual.style.format({"Elo": "{:.0f}", "Partidas": "{:.0f}", "Vitorias": "{:.0f}"}), 
            use_container_width=True,
            hide_index=True, # Esconde o índice numérico padrão do pandas (0, 1, 2)
            height=500 # Altura fixa para scrollar se a lista for grande
        )
    
    st.markdown("---")
    with st.expander("➕ Cadastrar Novo Jogador neste Grupo", expanded=False):
        with st.form("novo_jogador"):
            nome_input = st.text_input("Nome")
            elo_input = st.number_input("Elo Inicial", 1200, step=50)
            if st.form_submit_button("Salvar") and nome_input:
                novo = pd.DataFrame([{
                    "Nome": nome_input, "Elo": elo_input, "Partidas": 0, "Vitorias": 0, "Grupo": grupo_selecionado 
                }])
                df_atualizado = pd.concat([df_geral, novo], ignore_index=True)
                conn.update(worksheet="Jogadores", data=df_atualizado)
                if 'cache_jogadores' in st.session_state: del st.session_state['cache_jogadores']
                st.success(f"{nome_input} adicionado ao grupo {grupo_selecionado}!")
                time.sleep(1)
                st.rerun()

# --- ABA 3: HISTÓRICO --- 
with tab3:
    st.markdown(f"### 📜 Histórico ({grupo_selecionado})")
    try:
        df_hist = conn.read(worksheet="Historico", ttl=0).dropna(how="all")
        if 'Grupo' not in df_hist.columns:
            df_hist['Grupo'] = nome_padrao_caso_coluna_geral_inexistente
        
        df_hist_filtrado = df_hist[df_hist['Grupo'] == grupo_selecionado]
        
        if df_hist_filtrado.empty:
             st.info("Nenhuma partida encontrada para este grupo.")
        else:
            # --- LÓGICA DE CORES ---
            def destacar_vencedor(valor):
                if valor == 'Time A':
                    return 'background-color: #dbeafe; color: #1e3a8a; font-weight: bold' # Azul Claro
                elif valor == 'Time B':
                    return 'background-color: #ffedd5; color: #9a3412; font-weight: bold' # Laranja Claro
                return ''

            # Aplica o estilo apenas na coluna 'Vencedor'
            st.dataframe(
                df_hist_filtrado.iloc[::-1].style.map(destacar_vencedor, subset=['Vencedor']),
                use_container_width=True,
                hide_index=True
            )
    except Exception as e: 
        st.warning("Aguardando dados ou conexão...")

# --- ABA 1: A QUADRA ---
with tab1:
    if df_jogadores.empty:
        st.warning("Cadastre jogadores na aba 'Ranking' para começar.")
    else:
        nomes_disponiveis = df_jogadores['Nome'].tolist()
        
        st.info(f"Grupo atual: **{grupo_selecionado}**")
        
        # Seleção de Jogadores (Form para evitar reload constante)
        with st.form("selecao_jogadores"):
            st.markdown("#### 📋 Chamada")
            # Filtra defaults para garantir que pertençam ao grupo atual
            defaults_presentes = [p for p in st.session_state['todos_presentes'] if p in nomes_disponiveis]
            
            presentes = st.multiselect("Quem está na quadra hoje?", nomes_disponiveis, default=defaults_presentes)
            
            defaults_levs = [p for p in st.session_state['todos_levantadores'] if p in presentes]
            levantadores = st.multiselect("Quem são os levantadores?", presentes, default=defaults_levs)
            
            confirmar = st.form_submit_button("✅ Confirmar presença")
        
        if confirmar:
            st.session_state['todos_presentes'] = presentes
            st.session_state['todos_levantadores'] = levantadores
            st.rerun()

        presentes_final = st.session_state['todos_presentes']
        levantadores_final = st.session_state['todos_levantadores']
        
        total_necessario = tamanho_time * 2
        
        if len(presentes_final) < total_necessario:
            st.warning(f"Selecione pelo menos {total_necessario} jogadores.")
        else:
            col_action, col_info = st.columns([1, 2])
            texto_botao = "🏐 Iniciar novo jogo"
            if 'jogo_atual' in st.session_state: texto_botao = "🔄 Próxima rodada"

            # --- LÓGICA DE GERAR OS TIMES ---
            if col_action.button(texto_botao, type="primary"):
                # Garante limpeza de estados antigos
                if 'streak_vitorias' not in st.session_state: st.session_state['streak_vitorias'] = 0
                if 'fila_espera' not in st.session_state: st.session_state['fila_espera'] = []
                
                vencedores_garantidos = []
                
                # 1. Checa se mantém os vencedores (Rei da Quadra)
                if st.session_state['time_vencedor_anterior'] and st.session_state['streak_vitorias'] < limite_vitorias:
                    v_nomes = st.session_state['time_vencedor_anterior']
                    vencedores_garantidos = [p for p in v_nomes if p in presentes_final]
                    
                    # Se o time vencedor for MAIOR que o novo tamanho permitido, corta o excesso.
                    if len(vencedores_garantidos) > tamanho_time:
                        st.toast(f"⚠️ Time vencedor reduzido para {tamanho_time} jogadores.")
                        vencedores_garantidos = vencedores_garantidos[:tamanho_time]
                    
                    # Se o time vencedor for MENOR que o necessário (falta gente), reseta.
                    if len(vencedores_garantidos) < tamanho_time:
                        st.warning("Time vencedor incompleto. Resetando.")
                        vencedores_garantidos = []
                        st.session_state['streak_vitorias'] = 0
                        st.session_state['time_vencedor_anterior'] = None
                
                elif st.session_state['streak_vitorias'] >= limite_vitorias:
                    st.toast(f"🔥 Limite de {limite_vitorias} vitórias atingido! Misturando.")
                    v_nomes = st.session_state['time_vencedor_anterior'] or []
                    vencedores_garantidos = [p for p in v_nomes if p in presentes_final]
                    st.session_state['streak_vitorias'] = 0
                    st.session_state['time_vencedor_anterior'] = None
                
                # 2. Preenche vagas
                vagas_abertas = total_necessario - len(vencedores_garantidos)
                candidatos = [p for p in presentes_final if p not in vencedores_garantidos]
                
                novos_entrantes = []
                sobra_para_fila = []
                
                # Prioridade: Fila de espera
                fila_atual = [p for p in st.session_state['fila_espera'] if p in candidatos]
                
                if len(fila_atual) <= vagas_abertas:
                    novos_entrantes.extend(fila_atual)
                else:
                    novos_entrantes.extend(fila_atual[:vagas_abertas])
                    sobra_para_fila.extend(fila_atual[vagas_abertas:])
                
                # Completa com o resto (Melhores Elos primeiro)
                vagas_restantes = vagas_abertas - len(novos_entrantes)
                quem_nao_entrou_pela_fila = [p for p in candidatos if p not in novos_entrantes and p not in sobra_para_fila]
                
                if vagas_restantes > 0:
                    df_resto = df_jogadores[df_jogadores['Nome'].isin(quem_nao_entrou_pela_fila)].sort_values(by='Elo', ascending=False)
                    melhores_resto = df_resto.head(vagas_restantes)['Nome'].tolist()
                    piores_resto = df_resto.tail(len(df_resto) - vagas_restantes)['Nome'].tolist()
                    novos_entrantes.extend(melhores_resto)
                    sobra_para_fila.extend(piores_resto)
                else:
                    sobra_para_fila.extend(quem_nao_entrou_pela_fila)

                # Atualiza Fila
                st.session_state['fila_espera'] = sobra_para_fila
                
                # 3. Monta os Times (A e B)
                pool_jogo = vencedores_garantidos + novos_entrantes
                
                if st.session_state['time_vencedor_anterior'] and st.session_state['streak_vitorias'] > 0:
                    # Se tem Rei da Quadra ativo, Time A é fixo
                    t_a = df_jogadores[df_jogadores['Nome'].isin(vencedores_garantidos)]
                    t_b = df_jogadores[df_jogadores['Nome'].isin(novos_entrantes)]
                else:
                    # Se não, balanceia tudo
                    df_pool = df_jogadores[df_jogadores['Nome'].isin(pool_jogo)]
                    t_a, t_b = distribuir_times_equilibrados(df_pool, levantadores_final, tamanho_time)
                
                st.session_state['jogo_atual'] = {'A': t_a, 'B': t_b}
                st.rerun()

            # --- EXIBIÇÃO DO JOGO ATUAL ---
            if 'jogo_atual' in st.session_state:
                t_a = st.session_state['jogo_atual']['A']
                t_b = st.session_state['jogo_atual']['B']
                streak = st.session_state.get('streak_vitorias', 0)
                
                st.divider()
                colA, colVs, colB = st.columns([4, 1, 4])
                
                with colA:
                    st.markdown(f"### 🛡️ Time A ({t_a['Elo'].mean():.0f})")
                    if streak > 0 and st.session_state.get('time_vencedor_anterior') and set(t_a['Nome']) == set(st.session_state['time_vencedor_anterior']):
                         st.caption(f"👑 Reis da Quadra ({streak}/{limite_vitorias})")
                    
                    for _, row in t_a.iterrows():
                        icon = "🤲" if row['Nome'] in levantadores_final else "👤"
                        st.write(f"{icon} {row['Nome']} ({row['Elo']:.0f})")
                    if st.button("VITÓRIA TIME A 🏆", use_container_width=True): 
                        processar_vitoria(t_a, t_b, "Time A", grupo_selecionado, t_a['Nome'], t_b['Nome'])

                with colVs: st.markdown("<br><h2 style='text-align: center;'>VS</h2>", unsafe_allow_html=True)

                with colB:
                    st.markdown(f"### ⚔️ Time B ({t_b['Elo'].mean():.0f})")
                    if streak > 0 and st.session_state.get('time_vencedor_anterior') and set(t_b['Nome']) == set(st.session_state['time_vencedor_anterior']):
                         st.caption(f"👑 Reis da Quadra ({streak}/{limite_vitorias})")
                         
                    for _, row in t_b.iterrows():
                        icon = "🤲" if row['Nome'] in levantadores_final else "👤"
                        st.write(f"{icon} {row['Nome']} ({row['Elo']:.0f})")
                    if st.button("VITÓRIA TIME B 🏆", use_container_width=True): 
                        processar_vitoria(t_b, t_a, "Time B", grupo_selecionado, t_a['Nome'], t_b['Nome'])

# --- ATUALIZAÇÃO FINAL DA FILA VISUAL ---
# Isso garante que a fila mostrada na barra lateral esteja sempre sincronizada
if 'fila_espera' in st.session_state and st.session_state['fila_espera']:
    texto_fila = ""
    for i, nome in enumerate(st.session_state['fila_espera']):
        texto_fila += f"**{i+1}º** {nome}\n\n"
    placeholder_fila.markdown(texto_fila)
else:

    placeholder_fila.caption("Fila vazia.")












