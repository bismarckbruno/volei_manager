import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
import time
import pytz
import random
import json
import os

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Vôlei Manager", page_icon="🏐", layout="wide")
st.title("🏐 Vôlei Manager")

# --- CONSTANTES ---
K_FACTOR = 32
STATE_FILE = "voley_state.json" # Arquivo local para salvar estado (Cache)

# --- CONEXÃO ---
conn = st.connection("gsheets", type=GSheetsConnection)

# --- PERSISTÊNCIA LOCAL (CACHE) ---
def salvar_estado_disco():
    """Salva o estado crítico em um JSON local para sobreviver ao F5 sem gastar cota do Google."""
    estado = {
        'fila_espera': st.session_state.get('fila_espera', []),
        'streak_vitorias': st.session_state.get('streak_vitorias', 0),
        'time_vencedor_anterior': st.session_state.get('time_vencedor_anterior', None),
        'jogo_atual_serializado': None,
        'grupo_atual': st.session_state.get('grupo_atual', None)
    }
    
    # Precisamos serializar os DataFrames do jogo atual para JSON
    if 'jogo_atual' in st.session_state:
        estado['jogo_atual_serializado'] = {
            'A': st.session_state['jogo_atual']['A'].to_dict('records'),
            'B': st.session_state['jogo_atual']['B'].to_dict('records')
        }
        
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(estado, f)
    except Exception as e:
        print(f"Erro ao salvar cache local: {e}")

def carregar_estado_disco():
    """Recupera o estado do arquivo JSON se existir."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                estado = json.load(f)
                
            st.session_state['fila_espera'] = estado.get('fila_espera', [])
            st.session_state['streak_vitorias'] = estado.get('streak_vitorias', 0)
            st.session_state['time_vencedor_anterior'] = estado.get('time_vencedor_anterior', None)
            st.session_state['grupo_atual'] = estado.get('grupo_atual', None)
            
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
    # Tenta carregar do disco primeiro se não houver estado na memória
    if 'iniciado' not in st.session_state:
        carregou = carregar_estado_disco()
        st.session_state['iniciado'] = True
    
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
        df = conn.read(worksheet="Jogadores", ttl=0)
        df = df.dropna(how="all")
        
        cols_num = ['Elo', 'Partidas', 'Vitorias']
        for c in cols_num:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0 if c != 'Elo' else 1200)
            
        st.session_state['cache_jogadores'] = df
        return df
    except Exception as e:
        st.error(f"⚠️ ERRO DETALHADO: {e}")
        st.stop()

# --- FUNÇÕES LÓGICAS E UTILITÁRIAS ---
def realizar_substituicao(jogador_saindo, time_alvo_str):
    """
    Remove jogador da quadra, coloca no fim da fila.
    Pega o 1º da fila e coloca em quadra.
    """
    if not st.session_state['fila_espera']:
        st.toast("⚠️ A fila de espera está vazia! Não há quem colocar no lugar.")
        return

    # 1. Identificar quem entra e quem sai
    jogador_entrando = st.session_state['fila_espera'].pop(0) # Tira o primeiro da fila
    
    # 2. Atualizar a Fila (Quem sai vai pro fim)
    st.session_state['fila_espera'].append(jogador_saindo)
    
    # 3. Atualizar DataFrames do Jogo
    time_df = st.session_state['jogo_atual'][time_alvo_str]
    
    # Pega os dados completos de quem está entrando (do cache geral)
    df_geral = st.session_state['cache_jogadores']
    dados_novo = df_geral[(df_geral['Nome'] == jogador_entrando) & (df_geral['Grupo'] == st.session_state['grupo_atual'])].iloc[0]
    
    # Remove quem sai e adiciona quem entra no DataFrame do time
    idx_sair = time_df[time_df['Nome'] == jogador_saindo].index
    time_df = time_df.drop(idx_sair)
    
    # Adiciona o novo jogador (convertendo Series para DF para concatenar)
    novo_df = pd.DataFrame([dados_novo])
    time_df = pd.concat([time_df, novo_df], ignore_index=True)
    
    # Salva no estado
    st.session_state['jogo_atual'][time_alvo_str] = time_df
    
    salvar_estado_disco() # Salva mudança
    st.rerun()

def calcular_novo_elo(rating_vencedor, rating_perdedor):
    expectativa_vencedor = 1 / (1 + 10 ** ((rating_perdedor - rating_vencedor) / 400))
    return rating_vencedor + K_FACTOR * (1 - expectativa_vencedor)

def distribuir_times_equilibrados(df_pool, levantadores_selecionados, tamanho_time):
    levs = df_pool[df_pool['Nome'].isin(levantadores_selecionados)].sort_values(by='Elo', ascending=False).to_dict('records')
    outros = df_pool[~df_pool['Nome'].isin(levantadores_selecionados)].sort_values(by='Elo', ascending=False).to_dict('records')
    
    time_a = []
    time_b = []
    
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
        
        if df_h.empty:
            conn.update(worksheet="Historico", data=novo_registro)
        else:
            conn.update(worksheet="Historico", data=pd.concat([df_h, novo_registro], ignore_index=True))
            
    except Exception as e:
        print(f"Erro ao salvar histórico: {e}")
    
    # Lógica de Streak
    venc_nomes = time_venc['Nome'].tolist()
    anteriores = st.session_state.get('time_vencedor_anterior', [])
    
    if anteriores and set(venc_nomes) == set(anteriores):
        st.session_state['streak_vitorias'] += 1
    else:
        st.session_state['streak_vitorias'] = 1
        st.session_state['time_vencedor_anterior'] = venc_nomes
    
    st.toast(f"✅ Resultado salvo! +{delta:.1f} pontos Elo!")
    
    if 'jogo_atual' in st.session_state:
        del st.session_state['jogo_atual']
    
    salvar_estado_disco() # Atualiza o cache local
    time.sleep(1)
    st.rerun()

# --- CARREGAMENTO INICIAL ---
df_geral = carregar_dados()

# --- SIDEBAR: SELEÇÃO DE GRUPO ---
with st.sidebar:
    st.header("👥 Grupos")
    grupos_opcoes = df_geral['Grupo'].unique().tolist()
    if st.session_state['grupo_atual'] and st.session_state['grupo_atual'] not in grupos_opcoes and st.session_state['grupo_atual'] != "➕ Criar novo...":
        grupos_opcoes.append(st.session_state['grupo_atual'])
            
    opcoes_finais = grupos_opcoes + ["➕ Criar novo..."]
    idx = 0
    if st.session_state['grupo_atual'] in opcoes_finais:
        idx = opcoes_finais.index(st.session_state['grupo_atual'])
        
    grupo_selecionado = st.selectbox("Selecionar grupo:", opcoes_finais, index=idx)
    
    if grupo_selecionado == "➕ Criar novo...":
        st.markdown("---")
        with st.form("form_cria_grupo"):
            st.subheader("Novo Grupo")
            novo_nome = st.text_input("Nome")
            if st.form_submit_button("Criar") and novo_nome:
                st.session_state['grupo_atual'] = novo_nome
                salvar_estado_disco()
                st.rerun()
        st.stop()
    else:
        if st.session_state['grupo_atual'] != grupo_selecionado:
            st.session_state['grupo_atual'] = grupo_selecionado
            salvar_estado_disco()

    st.divider()

df_jogadores = df_geral[df_geral['Grupo'] == grupo_selecionado].copy()

# --- SIDEBAR: CONFIGURAÇÕES E FILA ---
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
            if os.path.exists(STATE_FILE): os.remove(STATE_FILE) # Limpa cache local
            st.rerun()

# --- ABA 2: RANKING (MELHORADO) ---
tab1, tab2, tab3 = st.tabs(["Quadra (Jogo)", "Ranking", "Histórico"])

with tab2:
    col_titulo, col_filtro = st.columns([1, 1])
    with col_titulo: st.markdown(f"### 🏆 Ranking: {grupo_selecionado}")
    with col_filtro:
        tipo_ranking = st.radio("Visualização:", ["Geral", "Último dia"], horizontal=True, label_visibility="collapsed", key="rank_view")

    if not df_jogadores.empty:
        df_visual = df_jogadores.copy()
        
        # Filtro de último dia (Lógica mantida do original)
        if tipo_ranking == "Último dia":
            try:
                df_h = conn.read(worksheet="Historico", ttl=0).dropna(how="all")
                df_h_grupo = df_h[df_h['Grupo'] == grupo_selecionado]
                if not df_h_grupo.empty:
                    cols = df_h_grupo.columns
                    col_ta = next((c for c in ['Time_A', 'Time A'] if c in cols), None)
                    col_tb = next((c for c in ['Time_B', 'Time B'] if c in cols), None)
                    if col_ta:
                        ultima_data = df_h_grupo.iloc[-1]['Data'].split(" ")[0]
                        st.caption(f"📅 Data base: **{ultima_data}**")
                        jogos = df_h_grupo[df_h_grupo['Data'].str.contains(ultima_data, na=False)]
                        nomes = set()
                        for _, row in jogos.iterrows():
                            nomes.update(str(row[col_ta]).split(", "))
                            nomes.update(str(row[col_tb]).split(", "))
                        df_visual = df_visual[df_visual['Nome'].isin(nomes)]
            except: pass

        df_visual = df_visual.sort_values(by="Elo", ascending=False).reset_index(drop=True)

        # --- NOVA LÓGICA DE CORES E PATENTES ---
        def get_patente_info(elo):
            if elo < 1000: return "🐣 Iniciante", "#f1c40f", "#000000" # Amarelo
            elif elo < 1100: return "🏐 Amador", "#d4ac0d", "#000000" # Amarelo Escuro
            elif elo < 1200: return "🥉 Intermediário", "#1abc9c", "#ffffff" # Verde-Azul
            elif elo < 1300: return "🥈 Avançado", "#3498db", "#ffffff" # Azul
            else: return "💎 Lenda", "#2c3e50", "#ffffff" # Azul Escuro

        if not df_visual.empty:
            patentes = [get_patente_info(e) for e in df_visual['Elo']]
            df_visual.insert(1, 'Patente', [p[0] for p in patentes])
            df_visual.insert(0, 'Pos.', [f"{i+1}º" for i in range(len(df_visual))])

            # Estilização
            def colorir_tabela(row):
                elo = row['Elo']
                _, bg_color, text_color = get_patente_info(elo)
                # Pinta Patente e Elo
                estilo = [f'background-color: {bg_color}; color: {text_color}' if col in ['Patente', 'Elo'] else '' for col in row.index]
                return estilo

            st.dataframe(
                df_visual.style.apply(colorir_tabela, axis=1)
                .format({"Elo": "{:.0f}", "Partidas": "{:.0f}", "Vitorias": "{:.0f}"}),
                use_container_width=True, hide_index=True, height=500
            )

    # Cadastro (Mantido igual)
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
    
    try:
        df_hist = conn.read(worksheet="Historico", ttl=0).dropna(how="all")
        df_hf = df_hist[df_hist['Grupo'] == grupo_selecionado].copy()
        
        if not df_hf.empty:
            def highlight_winner(row):
                styles = pd.Series('', index=row.index)
                if row['Vencedor'] == 'Time A' and 'Time A' in row: styles['Time A'] = 'background-color: #3d9df3; font-weight: bold'
                if row['Vencedor'] == 'Time B' and 'Time B' in row: styles['Time B'] = 'background-color: #f3ce60; font-weight: bold'
                return styles
            
            st.dataframe(df_hf.iloc[::-1].style.apply(highlight_winner, axis=1), use_container_width=True, hide_index=True)
        else: st.info("Sem histórico.")
    except Exception as e: st.warning("Carregando histórico...")

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
                salvar_estado_disco() # Salva configuração
                st.rerun()

        pres_final = st.session_state['todos_presentes']
        lev_final = st.session_state['todos_levantadores']
        nec = tamanho_time * 2
        
        if len(pres_final) >= nec:
            col_act, _ = st.columns([1, 2])
            txt_btn = "🔄 Próxima rodada" if 'jogo_atual' in st.session_state else "🏐 Iniciar Jogo"
            
            if col_act.button(txt_btn, type="primary"):
                # Garante lista limpa se não existir
                if 'fila_espera' not in st.session_state: st.session_state['fila_espera'] = []
                
                venc_garantidos = []
                streak = st.session_state.get('streak_vitorias', 0)
                
                # 1. Lógica Rei da Quadra
                if st.session_state['time_vencedor_anterior'] and streak < limite_vitorias:
                    venc_garantidos = [p for p in st.session_state['time_vencedor_anterior'] if p in pres_final]
                    if len(venc_garantidos) != tamanho_time: # Se time quebrou, reseta
                        venc_garantidos = []
                        st.session_state['streak_vitorias'] = 0
                        st.session_state['time_vencedor_anterior'] = None
                else:
                    st.session_state['streak_vitorias'] = 0
                    st.session_state['time_vencedor_anterior'] = None

                # 2. Definição de Vagas e Fila
                vagas = nec - len(venc_garantidos)
                candidatos = [p for p in pres_final if p not in venc_garantidos]
                
                novos_jogar = []
                
                # Prioridade: Quem já está na fila
                fila_real = [p for p in st.session_state['fila_espera'] if p in candidatos]
                
                # Remove da fila quem vai jogar agora
                for p in fila_real[:vagas]:
                    novos_jogar.append(p)
                    st.session_state['fila_espera'].remove(p) # Remove da fila
                
                # Se ainda faltam vagas, pega do resto
                faltam = vagas - len(novos_jogar)
                if faltam > 0:
                    resto = [p for p in candidatos if p not in novos_jogar and p not in st.session_state['fila_espera']]
                    random.shuffle(resto) # Sorteia a ordem de entrada do resto
                    
                    novos_jogar.extend(resto[:faltam])
                    
                    # Quem sobrou (não jogou e não estava na fila) vai pro fim da fila
                    # E aqui está o TRUQUE: Embaralhar antes de colocar na fila
                    sobra = resto[faltam:]
                    random.shuffle(sobra) 
                    st.session_state['fila_espera'].extend(sobra)
                
                # 3. Montar Times
                pool = venc_garantidos + novos_jogar
                if st.session_state['time_vencedor_anterior'] and streak > 0:
                    t_a = df_jogadores[df_jogadores['Nome'].isin(venc_garantidos)]
                    t_b = df_jogadores[df_jogadores['Nome'].isin(novos_jogar)]
                else:
                    df_p = df_jogadores[df_jogadores['Nome'].isin(pool)]
                    t_a, t_b = distribuir_times_equilibrados(df_p, lev_final, tamanho_time)
                
                st.session_state['jogo_atual'] = {'A': t_a, 'B': t_b}
                salvar_estado_disco()
                st.rerun()

            # --- EXIBIÇÃO DO JOGO ---
            if 'jogo_atual' in st.session_state:
                t_a = st.session_state['jogo_atual']['A']
                t_b = st.session_state['jogo_atual']['B']
                
                st.divider()
                cA, cM, cB = st.columns([4, 1, 4])
                
                # Função auxiliar para renderizar time com botão de troca
                def render_team(team_df, team_name, container):
                    with container:
                        st.markdown(f"### {('🛡️' if team_name == 'A' else '⚔️')} Time {team_name} ({team_df['Elo'].mean():.0f})")
                        for _, row in team_df.iterrows():
                            c_nome, c_btn = st.columns([4, 1])
                            icon = "🤲" if row['Nome'] in lev_final else "👤"
                            c_nome.write(f"**{icon} {row['Nome']}** ({row['Elo']:.0f})")
                            if c_btn.button("🔄", key=f"sub_{team_name}_{row['Nome']}", help="Substituir jogador"):
                                realizar_substituicao(row['Nome'], team_name)
                                
                        st.markdown("---")
                        if st.button(f"VITÓRIA TIME {team_name} 🏆", use_container_width=True, key=f"win_{team_name}"):
                            other = t_b if team_name == 'A' else t_a
                            other_n = "Time B" if team_name == 'A' else "Time A"
                            processar_vitoria(team_df, other, f"Time {team_name}", grupo_selecionado, t_a['Nome'], t_b['Nome'])

                render_team(t_a, 'A', cA)
                with cM: st.markdown("<br><br><h2 style='text-align: center;'>VS</h2>", unsafe_allow_html=True)
                render_team(t_b, 'B', cB)

# --- ATUALIZAÇÃO FINAL DA FILA (Sempre visível) ---
if 'fila_espera' in st.session_state and st.session_state['fila_espera']:
    txt = "\n".join([f"**{i+1}º** {n}" for i, n in enumerate(st.session_state['fila_espera'])])
    placeholder_fila.markdown(txt)
else:
    placeholder_fila.caption("Fila vazia.")
