import streamlit as st
import pandas as pd
import datetime
import time
import pytz
import random
import json
import os
import re

# --- TENTATIVA DE IMPORTAÇÃO DE BIBLIOTECAS EXTERNAS ---
try:
    from streamlit_gsheets import GSheetsConnection
    import plotly.graph_objects as go
except ImportError as e:
    st.error(f"❌ Erro Crítico de Instalação: {e}")
    st.info("Verifique se o arquivo 'requirements.txt' contém: st-gsheets-connection e plotly")
    st.stop()

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Vôlei Manager", page_icon="🏐", layout="wide")
st.title("🏐 Vôlei Manager")

# --- CONSTANTES ---
K_FACTOR = 32

# --- CONEXÃO DEFENSIVA ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error("🚨 ERRO DE CONEXÃO COM O GOOGLE SHEETS")
    st.markdown(f"**Detalhe do erro:** `{e}`")
    st.stop()

# --- GERENCIAMENTO DE ARQUIVOS DE ESTADO (PERSISTÊNCIA) ---
def get_arquivo_estado(nome_grupo):
    if not nome_grupo: return None
    nome_seguro = re.sub(r'[^\w\s-]', '', nome_grupo).strip().replace(' ', '_')
    return f"state_{nome_seguro}.json"

def salvar_estado_disco():
    grupo = st.session_state.get('grupo_atual')
    arquivo = get_arquivo_estado(grupo)
    if not arquivo: return

    estado = {
        'fila_espera': st.session_state.get('fila_espera', []),
        'streak_vitorias': st.session_state.get('streak_vitorias', 0),
        'time_vencedor_anterior': st.session_state.get('time_vencedor_anterior', None),
        'todos_presentes': st.session_state.get('todos_presentes', []),
        'todos_levantadores': st.session_state.get('todos_levantadores', []),
        'config_tamanho_time': st.session_state.get('config_tamanho_time', 6),
        'config_limite_vitorias': st.session_state.get('config_limite_vitorias', 3),
        'jogo_atual_serializado': None
    }
    
    if 'jogo_atual' in st.session_state:
        estado['jogo_atual_serializado'] = {
            'A': st.session_state['jogo_atual']['A'].to_dict('records'),
            'B': st.session_state['jogo_atual']['B'].to_dict('records')
        }
        
    try:
        with open(arquivo, 'w') as f:
            json.dump(estado, f)
    except Exception as e:
        print(f"Erro ao salvar cache local: {e}")

def carregar_estado_disco(grupo_alvo):
    arquivo = get_arquivo_estado(grupo_alvo)
    if arquivo and os.path.exists(arquivo):
        try:
            with open(arquivo, 'r') as f:
                estado = json.load(f)
                
            st.session_state['fila_espera'] = estado.get('fila_espera', [])
            st.session_state['streak_vitorias'] = estado.get('streak_vitorias', 0)
            st.session_state['time_vencedor_anterior'] = estado.get('time_vencedor_anterior', None)
            st.session_state['todos_presentes'] = estado.get('todos_presentes', [])
            st.session_state['todos_levantadores'] = estado.get('todos_levantadores', [])
            
            # Converte para int para garantir compatibilidade
            st.session_state['config_tamanho_time'] = int(estado.get('config_tamanho_time', 6))
            st.session_state['config_limite_vitorias'] = int(estado.get('config_limite_vitorias', 3))
            
            if estado.get('jogo_atual_serializado'):
                st.session_state['jogo_atual'] = {
                    'A': pd.DataFrame(estado['jogo_atual_serializado']['A']),
                    'B': pd.DataFrame(estado['jogo_atual_serializado']['B'])
                }
            return True
        except Exception as e:
            st.warning(f"Não foi possível restaurar sessão anterior: {e}")
            return False
    return False

# --- INICIALIZAÇÃO DE ESTADO ---
def inicializar_session_state():
    chaves_padrao = {
        'fila_espera': [],
        'streak_vitorias': 0,
        'time_vencedor_anterior': None,
        'todos_presentes': [],
        'todos_levantadores': [],
        'grupo_atual': None,
        'modo_substituicao': False,
        'config_tamanho_time': 6,
        'config_limite_vitorias': 3
    }
    for chave, valor in chaves_padrao.items():
        if chave not in st.session_state:
            st.session_state[chave] = valor

inicializar_session_state()

# --- FUNÇÕES DE DADOS E VISUALIZAÇÃO ---
def carregar_dados():
    if 'cache_jogadores' in st.session_state:
        return st.session_state['cache_jogadores']
    try:
        df = conn.read(worksheet="Jogadores", ttl=60) 
        df = df.dropna(how="all")
        cols_num = ['Elo', 'Partidas', 'Vitorias']
        for c in cols_num:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0 if c != 'Elo' else 1200)
        st.session_state['cache_jogadores'] = df
        return df
    except Exception as e:
        st.error(f"Erro ao ler a aba 'Jogadores': {e}")
        st.stop()

def exibir_tabela_plotly(df, colunas_mostrar, destacar_vencedor=False):
    """Gera uma tabela Plotly com formatação condicional."""
    if df.empty: return
    
    # Matrizes para armazenar cores de CADA célula (Coluna x Linha)
    fill_colors = []
    font_colors = []
    
    # Itera sobre as colunas para construir a lista de cores coluna por coluna
    for col in colunas_mostrar:
        col_fill = []
        col_font = []
        
        for _, row in df.iterrows():
            c = "white" # Cor padrão
            t = "black" # Texto padrão
            
            # Lógica 1: Cores por Patente (Ranking)
            if 'Patente' in row:
                if "Iniciante" in row['Patente']: c, t = "#f1c40f", "black"
                elif "Amador" in row['Patente']: c, t = "#d4ac0d", "black"
                elif "Intermediário" in row['Patente']: c, t = "#1abc9c", "black"
                elif "Avançado" in row['Patente']: c, t = "#3498db", "black"
                elif "Lenda" in row['Patente']: c, t = "#2c3e50", "white"
            
            # Lógica 2: Destaque de Vencedor (Histórico) - Sobrescreve Patente se necessário
            if destacar_vencedor:
                venc = str(row.get('Vencedor', ''))
                # Se a coluna atual é Time A e o vencedor foi Time A
                if col == "Time A" and ("Time A" in venc or "Time_A" in venc):
                    c = "#d1e7dd" # Verde Claro
                    t = "black"
                # Se a coluna atual é Time B e o vencedor foi Time B
                elif col == "Time B" and ("Time B" in venc or "Time_B" in venc):
                    c = "#fff3cd" # Amarelo/Laranja Claro
                    t = "black"

            col_fill.append(c)
            col_font.append(t)
        
        fill_colors.append(col_fill)
        font_colors.append(col_font)

    fig = go.Figure(data=[go.Table(
        header=dict(
            values=list(colunas_mostrar),
            fill_color='#444',
            font=dict(color='white', size=12),
            align='left'
        ),
        cells=dict(
            values=[df[k].tolist() for k in colunas_mostrar],
            fill_color=fill_colors, # Matriz de cores corrigida
            font=dict(color=font_colors, size=11),
            align='left',
            height=30
        )
    )])
    
    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=400)
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': True, 'displaylogo': False})


# --- FUNÇÕES LÓGICAS ---
def realizar_substituicao(jogador_saindo, time_alvo_str):
    if not st.session_state['fila_espera']:
        st.toast("⚠️ A fila de espera está vazia!")
        return

    jogador_entrando = st.session_state['fila_espera'].pop(0) 
    st.session_state['fila_espera'].append(jogador_saindo)
    
    time_df = st.session_state['jogo_atual'][time_alvo_str]
    df_geral = st.session_state['cache_jogadores']
    
    dados_novo_lista = df_geral[(df_geral['Nome'] == jogador_entrando) & (df_geral['Grupo'] == st.session_state['grupo_atual'])]
    if dados_novo_lista.empty:
        st.error(f"Erro: Jogador {jogador_entrando} não encontrado no grupo atual.")
        return
        
    dados_novo = dados_novo_lista.iloc[0]
    idx_sair = time_df[time_df['Nome'] == jogador_saindo].index
    time_df = time_df.drop(idx_sair)
    novo_df = pd.DataFrame([dados_novo])
    time_df = pd.concat([time_df, novo_df], ignore_index=True)
    
    st.session_state['jogo_atual'][time_alvo_str] = time_df
    salvar_estado_disco()
    st.rerun()

def calcular_novo_elo(rating_vencedor, rating_perdedor):
    expectativa_vencedor = 1 / (1 + 10 ** ((rating_perdedor - rating_vencedor) / 400))
    return rating_vencedor + K_FACTOR * (1 - expectativa_vencedor)

def distribuir_times_equilibrados(pool_nomes, levantadores_selecionados, tamanho_time, df_jogadores):
    df_pool = df_jogadores[df_jogadores['Nome'].isin(pool_nomes)].copy()
    levs = df_pool[df_pool['Nome'].isin(levantadores_selecionados)].sort_values(by='Elo', ascending=False).to_dict('records')
    outros = df_pool[~df_pool['Nome'].isin(levantadores_selecionados)].sort_values(by='Elo', ascending=False).to_dict('records')
    
    time_a, time_b = [], []
    def alocar(jogador):
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
    mv, mp = time_venc['Elo'].mean(), time_perd['Elo'].mean()
    delta = calcular_novo_elo(mv, mp) - mv
    df_ram = st.session_state['cache_jogadores']
    
    for n in time_venc['Nome']:
        idx = df_ram.index[(df_ram['Nome'] == n) & (df_ram['Grupo'] == grupo_selecionado)]
        if not idx.empty:
            df_ram.loc[idx, 'Elo'] += delta
            df_ram.loc[idx, 'Partidas'] += 1
            df_ram.loc[idx, 'Vitorias'] += 1
    for n in time_perd['Nome']:
        idx = df_ram.index[(df_ram['Nome'] == n) & (df_ram['Grupo'] == grupo_selecionado)]
        if not idx.empty:
            df_ram.loc[idx, 'Elo'] -= delta
            df_ram.loc[idx, 'Partidas'] += 1
    
    conn.update(worksheet="Jogadores", data=df_ram)
    st.session_state['cache_jogadores'] = df_ram
    
    try:
        fuso_br = pytz.timezone('America/Sao_Paulo')
        data_hora_atual = datetime.datetime.now(fuso_br).strftime("%d/%m %H:%M")
        novo_registro = pd.DataFrame([{
            "Data": data_hora_atual,
            "Time A": ", ".join(t_a_nomes), 
            "Time B": ", ".join(t_b_nomes), 
            "Vencedor": nome_venc_str,
            "Pontos_Elo": f"+{delta:.1f}", 
            "Grupo": grupo_selecionado
        }])
        df_h = conn.read(worksheet="Historico", ttl=0).dropna(how="all")
        if df_h.empty: conn.update(worksheet="Historico", data=novo_registro)
        else: conn.update(worksheet="Historico", data=pd.concat([df_h, novo_registro], ignore_index=True))
    except Exception as e: print(f"Erro ao salvar histórico: {e}")
    
    venc_nomes = time_venc['Nome'].tolist()
    anteriores = st.session_state.get('time_vencedor_anterior', [])
    if anteriores and set(venc_nomes) == set(anteriores): st.session_state['streak_vitorias'] += 1
    else:
        st.session_state['streak_vitorias'] = 1
        st.session_state['time_vencedor_anterior'] = venc_nomes
    
    perdedores = time_perd['Nome'].tolist()
    st.session_state['fila_espera'] = [p for p in st.session_state['fila_espera'] if p not in perdedores] + perdedores
    st.toast(f"✅ Salvo! +{delta:.1f} pontos Elo!")
    if 'jogo_atual' in st.session_state: del st.session_state['jogo_atual']
    salvar_estado_disco()
    time.sleep(1)
    st.rerun()

# --- CARREGAMENTO INICIAL ---
df_geral = carregar_dados()

# --- SIDEBAR: SELEÇÃO DE GRUPO ---
with st.sidebar:
    st.header("👥 Grupos")
    if df_geral is not None and not df_geral.empty:
        grupos_opcoes = df_geral['Grupo'].unique().tolist()
    else:
        grupos_opcoes = []
    
    if st.session_state['grupo_atual'] and st.session_state['grupo_atual'] not in grupos_opcoes and st.session_state['grupo_atual'] != "➕ Criar novo...":
        grupos_opcoes.append(st.session_state['grupo_atual'])
            
    opcoes_finais = grupos_opcoes + ["➕ Criar novo..."]
    idx = 0
    if st.session_state['grupo_atual'] in opcoes_finais:
        idx = opcoes_finais.index(st.session_state['grupo_atual'])
        
    grupo_selecionado = st.selectbox("Selecionar grupo:", opcoes_finais, index=idx)
    
    if grupo_selecionado == "➕ Criar novo...":
        with st.form("form_cria_grupo"):
            st.subheader("Novo Grupo")
            novo_nome = st.text_input("Nome")
            if st.form_submit_button("Criar") and novo_nome:
                st.session_state['grupo_atual'] = novo_nome
                for k in ['jogo_atual', 'fila_espera', 'streak_vitorias', 'time_vencedor_anterior']:
                    if k in st.session_state: del st.session_state[k]
                salvar_estado_disco()
                st.rerun()
        st.stop()
    else:
        if st.session_state['grupo_atual'] != grupo_selecionado:
            st.session_state['grupo_atual'] = grupo_selecionado
            if not carregar_estado_disco(grupo_selecionado):
                for k in ['jogo_atual', 'fila_espera', 'streak_vitorias', 'time_vencedor_anterior']:
                    if k in st.session_state: del st.session_state[k]
            st.rerun()

    st.divider()

if df_geral is not None:
    df_jogadores = df_geral[df_geral['Grupo'] == grupo_selecionado].copy()
else:
    df_jogadores = pd.DataFrame()

# --- SIDEBAR: CONFIGURAÇÕES E FILA ---
with st.sidebar:
    st.header("⚙️ Configurações")
    
    def on_config_change():
        salvar_estado_disco()

    # REMOVIDO: parâmetro 'index' que causava o erro
    # O Streamlit usará automaticamente o valor da 'key' do session_state
    t_time = st.radio(
        "Jogadores por time:", 
        [2, 3, 4, 5, 6], 
        horizontal=True,
        key='config_tamanho_time',
        on_change=on_config_change
    )
    
    l_vitorias = st.radio(
        "Limite de vitórias:", 
        [2, 3, 4, 5, 6], 
        horizontal=True,
        key='config_limite_vitorias',
        on_change=on_config_change
    )
    
    st.divider()
    st.subheader("⏳ Fila de espera")
    placeholder_fila = st.empty() 
    
    st.divider()
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("🔄 Atualizar"):
            carregar_estado_disco(grupo_selecionado)
            st.cache_data.clear()
            if 'cache_jogadores' in st.session_state: del st.session_state['cache_jogadores']
            st.rerun()
    with col_btn2:
        if st.button("⚠️ Hard Reset", help="Use se o app travar ou ficar carregando infinitamente"):
            st.cache_data.clear()
            st.session_state.clear()
            st.rerun()

# --- ABAS ---
tab1, tab2, tab3 = st.tabs(["Quadra (Jogo)", "Ranking", "Histórico"])

# --- ABA 2: RANKING ---
with tab2:
    col_titulo, col_filtro = st.columns([1, 1])
    with col_titulo: st.markdown(f"### 🏆 Ranking: {grupo_selecionado}")
    with col_filtro:
        tipo_ranking = st.radio("Visualização:", ["Geral", "Último dia"], horizontal=True, label_visibility="collapsed", key="rank_view")

    if not df_jogadores.empty:
        df_visual = df_jogadores.copy()
        if tipo_ranking == "Último dia":
            try:
                df_h = conn.read(worksheet="Historico", ttl=0).dropna(how="all")
                df_h_grupo = df_h[df_h['Grupo'] == grupo_selecionado]
                if not df_h_grupo.empty:
                    ultima_data = df_h_grupo.iloc[-1]['Data'].split(" ")[0]
                    st.caption(f"📅 Data base: **{ultima_data}**")
                    jogos = df_h_grupo[df_h_grupo['Data'].str.contains(ultima_data, na=False)]
                    nomes = set()
                    for _, row in jogos.iterrows():
                        ta = str(row.get('Time A', row.get('Time_A', '')))
                        tb = str(row.get('Time B', row.get('Time_B', '')))
                        nomes.update(ta.split(", "))
                        nomes.update(tb.split(", "))
                    df_visual = df_visual[df_visual['Nome'].isin(nomes)]
            except: pass

        df_visual = df_visual.sort_values(by="Elo", ascending=False).reset_index(drop=True)

        def get_patente_info(elo):
            if elo < 1000: return "🐣 Iniciante"
            elif elo < 1100: return "🏐 Amador"
            elif elo < 1200: return "🥉 Intermediário"
            elif elo < 1300: return "🥈 Avançado"
            else: return "💎 Lenda"

        if not df_visual.empty:
            patentes = [get_patente_info(e) for e in df_visual['Elo']]
            if 'Patente' in df_visual.columns: df_visual.drop(columns=['Patente'], inplace=True)
            if 'Pos.' in df_visual.columns: df_visual.drop(columns=['Pos.'], inplace=True)
            
            df_visual.insert(1, 'Patente', patentes)
            df_visual.insert(0, 'Pos.', [f"{i+1}º" for i in range(len(df_visual))])

            exibir_tabela_plotly(df_visual[["Pos.", "Nome", "Patente", "Elo", "Partidas", "Vitorias"]], df_visual.columns, destacar_vencedor=False)
            st.caption("💡 Clique no ícone de câmera no canto superior direito da tabela para baixar como imagem.")

    with st.expander("➕ Cadastrar Novo Jogador"):
        with st.form("novo_jogador"):
            nome_input = st.text_input("Nome")
            elo_input = st.number_input("Elo Inicial", 1200, step=50)
            if st.form_submit_button("Salvar") and nome_input:
                novo = pd.DataFrame([{"Nome": nome_input, "Elo": elo_input, "Partidas": 0, "Vitorias": 0, "Grupo": grupo_selecionado}])
                conn.update(worksheet="Jogadores", data=pd.concat([df_geral, novo], ignore_index=True))
                if 'cache_jogadores' in st.session_state: del st.session_state['cache_jogadores']
                st.rerun()

# --- ABA 3: HISTÓRICO ---
with tab3:
    col_h_t, col_h_f = st.columns([1, 1])
    with col_h_t: st.markdown(f"### 📜 Histórico: {grupo_selecionado}")
    with col_h_f:
        tipo_historico = st.radio("Visualização Histórico:", ["Geral", "Último dia"], horizontal=True, label_visibility="collapsed", key="hist_view")

    try:
        df_hist = conn.read(worksheet="Historico", ttl=0).dropna(how="all")
        if "Pontos_Elo" not in df_hist.columns:
            df_hist["Pontos_Elo"] = ""

        df_hf = df_hist[df_hist['Grupo'] == grupo_selecionado].copy()
        
        if not df_hf.empty:
            if tipo_historico == "Último dia":
                ultima_data_hist = df_hf.iloc[-1]['Data'].split(" ")[0]
                st.caption(f"📅 Exibindo partidas do dia: **{ultima_data_hist}**")
                df_hf = df_hf[df_hf['Data'].str.contains(ultima_data_hist, na=False)]
            
            df_hf = df_hf.iloc[::-1]
            cols_show = ["Data", "Time A", "Time B", "Vencedor", "Pontos_Elo"]
            # AQUI: Ativamos o destaque do vencedor
            exibir_tabela_plotly(df_hf[cols_show], cols_show, destacar_vencedor=True)
        else: st.info("Sem histórico.")
    except Exception as e: st.warning(f"Aguardando dados... {e}")

# --- ABA 1: QUADRA (JOGO) ---
with tab1:
    if df_jogadores.empty:
        st.warning("Cadastre jogadores primeiro.")
    else:
        nomes_disp = df_jogadores['Nome'].tolist()
        
        with st.form("chamada"):
            st.markdown("#### 📋 Chamada")
            defs_p = [p for p in st.session_state['todos_presentes'] if p in nomes_disp]
            pres = st.multiselect("Presentes", nomes_disp, default=defs_p)
            defs_l = [p for p in st.session_state['todos_levantadores'] if p in pres]
            levs = st.multiselect("Levantadores", pres, default=defs_l)
            if st.form_submit_button("Confirmar"):
                st.session_state['todos_presentes'] = pres
                st.session_state['todos_levantadores'] = levs
                salvar_estado_disco() 
                st.rerun()

        pres_final = st.session_state['todos_presentes']
        lev_final = st.session_state['todos_levantadores']
        tamanho_atual = st.session_state['config_tamanho_time']
        limite_atual = st.session_state['config_limite_vitorias']
        nec = tamanho_atual * 2
        
        if len(pres_final) < nec:
            st.warning(f"⚠️ Selecione pelo menos {nec} jogadores para iniciar uma partida equilibrada (Config atual: {tamanho_atual}x{tamanho_atual}).")
        
        if len(pres_final) >= 2: 
            st.divider()
            col_act, col_subs = st.columns([2, 1])
            
            with col_act:
                txt_btn = "🔄 Próxima rodada" if 'jogo_atual' in st.session_state else "🏐 Iniciar Jogo"
                
                if st.button(txt_btn, type="primary"):
                    if 'fila_espera' not in st.session_state: st.session_state['fila_espera'] = []
                    
                    streak = st.session_state.get('streak_vitorias', 0)
                    anteriores = st.session_state.get('time_vencedor_anterior', [])
                    vencedores_em_quadra = [p for p in anteriores if p in pres_final] if anteriores else []
                    
                    if streak >= limite_atual and vencedores_em_quadra:
                        st.toast("🏆 Limite atingido! Redistribuindo vencedores e fila.")
                        pool_para_jogar = list(vencedores_em_quadra)
                        vagas_restantes = nec - len(pool_para_jogar)
                        fila_limpa = [p for p in st.session_state['fila_espera'] if p in pres_final and p not in pool_para_jogar]
                        if vagas_restantes > 0:
                            entram_da_fila = fila_limpa[:vagas_restantes]
                            pool_para_jogar.extend(entram_da_fila)
                            fila_limpa = fila_limpa[vagas_restantes:]
                        st.session_state['fila_espera'] = fila_limpa
                        st.session_state['streak_vitorias'] = 0
                        st.session_state['time_vencedor_anterior'] = None
                        t_a, t_b = distribuir_times_equilibrados(pool_para_jogar, lev_final, tamanho_atual, df_jogadores)
                        st.session_state['jogo_atual'] = {'A': t_a, 'B': t_b}
                        salvar_estado_disco()
                        st.rerun()
                    else:
                        time_a_nomes = []
                        if vencedores_em_quadra: time_a_nomes = vencedores_em_quadra
                        candidatos = [p for p in pres_final if p not in time_a_nomes]
                        fila_real = [p for p in st.session_state['fila_espera'] if p in candidatos]
                        resto = [p for p in candidatos if p not in fila_real]
                        random.shuffle(resto)
                        pool_ordenado = fila_real + resto
                        
                        vagas_a = tamanho_atual - len(time_a_nomes)
                        if vagas_a > 0:
                            time_a_nomes.extend(pool_ordenado[:vagas_a])
                            pool_ordenado = pool_ordenado[vagas_a:]
                            
                        novos_b = pool_ordenado[:tamanho_atual]
                        time_b_nomes = novos_b
                        pool_ordenado = pool_ordenado[tamanho_atual:]
                        
                        st.session_state['fila_espera'] = pool_ordenado
                        
                        if vencedores_em_quadra and streak > 0:
                            t_a = df_jogadores[df_jogadores['Nome'].isin(time_a_nomes)]
                            t_b = df_jogadores[df_jogadores['Nome'].isin(time_b_nomes)]
                        else:
                            todos = time_a_nomes + time_b_nomes
                            t_a, t_b = distribuir_times_equilibrados(todos, lev_final, tamanho_atual, df_jogadores)
                        
                        st.session_state['jogo_atual'] = {'A': t_a, 'B': t_b}
                        salvar_estado_disco()
                        st.rerun()

            with col_subs:
                if st.toggle("Modo Substituição", value=st.session_state.get('modo_substituicao', False)):
                    st.session_state['modo_substituicao'] = True
                else:
                    st.session_state['modo_substituicao'] = False

            if 'jogo_atual' in st.session_state:
                t_a = st.session_state['jogo_atual']['A']
                t_b = st.session_state['jogo_atual']['B']
                streak = st.session_state.get('streak_vitorias', 0)
                
                st.divider()
                cA, cM, cB = st.columns([4, 1, 4])
                
                def render_team(team_df, team_name, container):
                    with container:
                        is_streak = streak > 0 and \
                                    st.session_state.get('time_vencedor_anterior') and \
                                    set(team_df['Nome']).issubset(set(st.session_state['time_vencedor_anterior']))
                        
                        titulo = f"🛡️ Time {team_name}" if team_name == 'A' else f"⚔️ Time {team_name}"
                        st.markdown(f"### {titulo} ({team_df['Elo'].mean():.0f})")
                        
                        if is_streak: 
                            if streak >= limite_atual:
                                st.caption(f"🚨 Limite Atingido ({streak}/{limite_atual}) - Serão redistribuídos na próxima!")
                            else:
                                st.caption(f"👑 Reis da Quadra ({streak}/{limite_atual} vitórias)")
                        
                        for _, row in team_df.iterrows():
                            if st.session_state['modo_substituicao']:
                                c_nome, c_btn = st.columns([4, 1])
                            else:
                                c_nome = st.container()
                                c_btn = None
                                
                            icon = "🤲" if row['Nome'] in lev_final else "👤"
                            c_nome.write(f"**{icon} {row['Nome']}** ({row['Elo']:.0f})")
                            if c_btn:
                                if c_btn.button("🔄", key=f"sub_{team_name}_{row['Nome']}", help="Substituir jogador"):
                                    realizar_substituicao(row['Nome'], team_name)
                        st.markdown("---")
                        if st.button(f"VITÓRIA TIME {team_name} 🏆", use_container_width=True, key=f"win_{team_name}"):
                            other = t_b if team_name == 'A' else t_a
                            processar_vitoria(team_df, other, f"Time {team_name}", grupo_selecionado, t_a['Nome'], t_b['Nome'])

                render_team(t_a, 'A', cA)
                with cM: st.markdown("<br><br><h2 style='text-align: center;'>VS</h2>", unsafe_allow_html=True)
                render_team(t_b, 'B', cB)

if 'fila_espera' in st.session_state and st.session_state['fila_espera']:
    fila_visivel = [p for p in st.session_state['fila_espera'] if p in st.session_state.get('todos_presentes', [])]
    if fila_visivel:
        txt = "\n".join([f"**{i+1}º** {n}" for i, n in enumerate(fila_visivel)])
        placeholder_fila.markdown(txt)
    else: placeholder_fila.caption("Fila vazia (todos presentes jogando).")
else: placeholder_fila.caption("Fila vazia.")
