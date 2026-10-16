import streamlit as st
import fitz  # PyMuPDF
from bs4 import BeautifulSoup
import asyncio
import edge_tts
import io
import re
import zipfile

st.set_page_config(page_title="Estúdio de Audiolivros IA", page_icon="🎧", layout="centered")

st.title("🎧 Estúdio Inteligente de Audiolivros")
st.markdown(
    "Interpretação automática de guiões: **ajusta o tom do narrador**, **injeta as pausas em segundos (`[P: Xs]`)** "
    "e **limpa comandos técnicos**, disponibilizando cada parte em tempo real."
)

# ---FRAME DE SILÊNCIO MP3 NATIVO (128kbps, 44.1kHz, ~26.12ms por frame) ---
# Permite injetar pausas exatas de [P: Xs] sem precisar de FFmpeg instalado no servidor
MP3_SILENCE_FRAME = bytes([
    0xFF, 0xFB, 0x90, 0x64, 0x00, 0x0F, 0xF0, 0x00, 0x00, 0x69, 0x00, 0x00, 0x00, 0x08, 0x00, 0x00,
    0x0D, 0x20, 0x00, 0x00, 0x01, 0x00, 0x00, 0x01, 0xA4, 0x00, 0x00, 0x00, 0x20, 0x00, 0x00, 0x34,
    0x80, 0x00, 0x00, 0x04, 0x00
]) + b'\x00' * 380

def gerar_silencio_mp3(segundos: float) -> bytes:
    num_frames = int((segundos * 1000) / 26.122)
    return MP3_SILENCE_FRAME * max(1, num_frames)

# --- BARRA LATERAL: CONFIGURAÇÕES ---
with st.sidebar:
    st.header("⚙️ Direção de Voz e Estúdio")
    
    vozes_disponiveis = {
        "🇵🇹 Duarte (PT - Masculina / Ideal para o Marco)": "pt-PT-DuarteNeural",
        "🇵🇹 Raquel (PT - Feminina / Natural)": "pt-PT-RaquelNeural",
        "🇧🇷 Antonio (BR - Masculina / Profunda)": "pt-BR-AntonioNeural",
        "🇧🇷 Francisca (BR - Feminina / Suave)": "pt-BR-FranciscaNeural"
    }
    
    voz_selecionada = st.selectbox("Escolhe o Narrador", list(vozes_disponiveis.keys()))
    voice_id = vozes_disponiveis[voz_selecionada]
    
    st.subheader("🎭 Interpretação do Guião")
    interpretar_pausas = st.checkbox("Respeitar pausas [P: Xs] com silêncio real", value=True)
    modular_tom = st.checkbox("Adaptar velocidade/tom às notas [NARRADOR]", value=True)
    ler_titulos_cap = st.checkbox("Anunciar títulos dos Capítulos e Partes", value=True)
    
    st.subheader("📦 Divisão do Audiolivro")
    modo_geracao = st.radio(
        "Formato de saída:",
        [
            "Vários Áudios (Por Partes)",
            "Ambos (Partes + Áudio Completo)",
            "Áudio Único (Livro Completo)"
        ]
    )
    
    chars_por_parte = st.slider(
        "Caracteres aproximados por Parte",
        min_value=3000,
        max_value=20000,
        value=8000,
        step=1000,
        help="Define a duração de cada faixa de áudio."
    )

# --- ANALISADOR PROFUNDO DO GUIÃO (PARSER CÉNICO) ---
def analisar_guiao_em_segmentos(texto_bruto: str, anunciar_cap: bool) -> list[dict]:
    """
    Transforma o guião numa sequência de eventos de áudio:
    - {'tipo': 'fala', 'texto': '...', 'rate': '-5%', 'pitch': '-2Hz'}
    - {'tipo': 'pausa', 'segundos': 3.0}
    Ignora cabeçalhos técnicos, metadados, créditos de texto e separadores.
    """
    linhas = texto_bruto.split('\n')
    segmentos = []
    
    # Estilo base ("conversa à beira da lareira: íntimo, sem pressa")
    rate_atual = "-6%"
    pitch_atual = "-1Hz"
    buffer_fala = []
    
    # Estado para ignorar o bloco inicial de especificações técnicas e créditos finais
    em_cabecalho_inicial = True
    em_creditos_finais = False

    def descarregar_fala():
        if buffer_fala:
            texto_bloco = " ".join(buffer_fala).strip()
            texto_bloco = re.sub(r'\s+', ' ', texto_bloco)
            if texto_bloco:
                segmentos.append({
                    'tipo': 'fala',
                    'texto': texto_bloco,
                    'rate': rate_atual,
                    'pitch': pitch_atual
                })
            buffer_fala.clear()

    # Expressões regulares de limpeza rigorosa baseadas na análise do ficheiro
    re_separador = re.compile(r'^[=\-_*#]{3,}$')
    re_pausa = re.compile(r'^\[P:\s*(\d+(?:\.\d+)?)s\]$', re.IGNORECASE)
    re_musica = re.compile(r'^\[MÚSICA:.*?\]$', re.IGNORECASE)
    re_narrador = re.compile(r'^\[NARRADOR\s*[—\-:]\s*(.*?)\]$', re.IGNORECASE)
    re_fim = re.compile(r'^\[FIM.*?\]$', re.IGNORECASE)
    
    # Cabeçalhos internos das 6 secções que NÃO devem ser lidos em voz alta
    re_seccoes_ocultas = re.compile(
        r'^(\d+\.\s*)?(O CONCEITO|A CIÊNCIA|A FERRAMENTA.*|REFLEXÃO|A PONTE.*)$',
        re.IGNORECASE
    )
    
    # Títulos de Capítulos e Partes (que definem o início real do livro)
    re_capitulo_ou_parte = re.compile(
        r'^(CAPÍTULO\s+\d+[A-Z]?\s*[—\-].+|PARTE\s+[A-ZÀ-Ú]+\s*[—\-].+|EPÍLOGO\s*[—\-].+|O SISTEMA MÍNIMO|NOTAS FINAIS)$',
        re.IGNORECASE
    )

    for linha in linhas:
        l = linha.strip()
        if not l:
            continue
            
        # 1. Detetar entrada nos Créditos Finais (para não ler "[Nome do adaptador]", etc.)
        if re.match(r'^CRÉDITOS DO AUDIOBOOK$', l, re.IGNORECASE):
            descarregar_fala()
            em_creditos_finais = True
            continue
            
        if em_creditos_finais:
            if l.lower().startswith("obrigado por ouvires"):
                segmentos.append({'tipo': 'pausa', 'segundos': 2.0})
                segmentos.append({'tipo': 'fala', 'texto': l, 'rate': '-10%', 'pitch': '-2Hz'})
            continue

        # 2. Ignorar linhas de separação visual (==========)
        if re_separador.match(l):
            continue

        # 3. Detetar Capítulos / Partes (Desbloqueia o início do livro após a ficha técnica)
        if re_capitulo_ou_parte.match(l):
            em_cabecalho_inicial = False
            descarregar_fala()
            segmentos.append({'tipo': 'pausa', 'segundos': 2.0})
            if anunciar_cap:
                # Substitui travessão por pausa de pontuação para leitura solene
                titulo_limpo = re.sub(r'\s*[—\-]\s*', '. ', l).capitalize()
                # Corrige numeração romana/específica se existir
                titulo_limpo = re.sub(r'17b', '17 B', titulo_limpo, flags=re.IGNORECASE)
                segmentos.append({
                    'tipo': 'fala',
                    'texto': f"{titulo_limpo}.",
                    'rate': '-10%',
                    'pitch': '-2Hz'
                })
                segmentos.append({'tipo': 'pausa', 'segundos': 2.5})
            continue

        # Se ainda estamos na ficha técnica antes do Capítulo 1, ignorar tudo
        if em_cabecalho_inicial:
            continue

        # 4. Ignorar cabeçalhos de subsecções ("2. O CONCEITO", "4. A FERRAMENTA...", etc.)
        if re_seccoes_ocultas.match(l):
            descarregar_fala()
            segmentos.append({'tipo': 'pausa', 'segundos': 1.5})
            continue

        # 5. Ignorar marcadores de fecho ([FIM DO CAPÍTULO 1], [FIM])
        if re_fim.match(l):
            descarregar_fala()
            segmentos.append({'tipo': 'pausa', 'segundos': 3.0})
            continue

        # 6. Interpretar indicações de Música ([MÚSICA: Piano suave...])
        if re_musica.match(l):
            descarregar_fala()
            # Insere uma pausa atmosférica de transição onde entraria a música
            segmentos.append({'tipo': 'pausa', 'segundos': 2.5})
            continue

        # 7. Interpretar Pausas explícitas ([P: 3s], [P: 8s])
        m_pausa = re_pausa.match(l)
        if m_pausa:
            descarregar_fala()
            seg = float(m_pausa.group(1))
            segmentos.append({'tipo': 'pausa', 'segundos': seg})
            continue

        # 8. Interpretar Mudanças de Tom do Narrador ([NARRADOR — tom íntimo...])
        m_narrador = re_narrador.match(l)
        if m_narrador:
            descarregar_fala()
            instrucao_tom = m_narrador.group(1).lower()
            if "pausado" in instrucao_tom or "reflex" in instrucao_tom or "despedida" in instrucao_tom:
                rate_atual = "-14%"
                pitch_atual = "-3Hz"
            elif "sóbrio" in instrucao_tom or "grave" in instrucao_tom:
                rate_atual = "-10%"
                pitch_atual = "-4Hz"
            elif "íntimo" in instrucao_tom or "próximo" in instrucao_tom:
                rate_atual = "-8%"
                pitch_atual = "-2Hz"
            elif "informativo" in instrucao_tom or "claro" in instrucao_tom:
                rate_atual = "-2%"
                pitch_atual = "+0Hz"
            elif "prático" in instrucao_tom:
                rate_atual = "-4%"
                pitch_atual = "+0Hz"
            else:
                rate_atual = "-6%"
                pitch_atual = "-1Hz"
            continue

        # 9. Limpeza de marcadores inline no meio das frases (ex: "sábado [deixa], o telefone...")
        l_limpa = re.sub(r'\[.*?\]', '', l)
        
        # 10. Tratamento de caracteres especiais do guião:
        # Substituir setas "→" por pontuação pausada
        l_limpa = l_limpa.replace('→', '... ')
        # Substituir linhas de espaço em branco "______" por reticências silenciosas
        l_limpa = re.sub(r'_{2,}', '...', l_limpa)
        # Melhorar pausas de travessões em finais de linha
        if l_limpa.endswith('—'):
            l_limpa = l_limpa[:-1].strip() + '...'
        else:
            l_limpa = l_limpa.replace(' — ', ', ')

        l_limpa = l_limpa.strip()
        if not l_limpa:
            continue

        # Garantir que linhas isoladas (estilo poético do guião) terminam com pontuação suave
        # para que o sintetizador respire entre linhas como pretendido pelo autor
        if l_limpa[-1] not in '.!?:;,…"\'”':
            l_limpa += '.'

        buffer_fala.append(l_limpa)

    descarregar_fala()
    return segmentos

# --- AGRUPADOR DE SEGMENTOS EM PARTES ---
def agrupar_segmentos_em_partes(segmentos: list[dict], max_chars: int) -> list[list[dict]]:
    partes = []
    parte_atual = []
    chars_atuais = 0

    for seg in segmentos:
        if seg['tipo'] == 'fala':
            tam = len(seg['texto'])
            if chars_atuais + tam > max_chars and parte_atual:
                partes.append(parte_atual)
                parte_atual = [seg]
                chars_atuais = tam
            else:
                parte_atual.append(seg)
                chars_atuais += tam
        else:
            parte_atual.append(seg)

    if parte_atual:
        partes.append(parte_atual)
    return partes

# --- SINTETIZADOR DE UMA PARTE COMPLETA (COM PAUSAS E PROSÓDIA) ---
async def sintetizar_parte(lista_segmentos: list[dict], voice: str, usar_pausas: bool, usar_tom: bool) -> bytes:
    buffer_parte = io.BytesIO()
    
    for seg in lista_segmentos:
        if seg['tipo'] == 'pausa':
            if usar_pausas:
                # Limita pausas muito longas a um máximo razoável (ex: 8s intactos)
                duracao = min(seg['segundos'], 10.0)
                buffer_parte.write(gerar_silencio_mp3(duracao))
        elif seg['tipo'] == 'fala':
            texto = seg['texto']
            if not texto:
                continue
            rate = seg['rate'] if usar_tom else "+0%"
            pitch = seg['pitch'] if usar_tom else "+0Hz"
            
            communicate = edge_tts.Communicate(texto, voice, rate=rate, pitch=pitch)
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    buffer_parte.write(chunk["data"])
                    
    return buffer_parte.getvalue()

# --- MEMÓRIA DA SESSÃO ---
if "arquivos_partes" not in st.session_state:
    st.session_state.arquivos_partes = []
if "audio_completo" not in st.session_state:
    st.session_state.audio_completo = None
if "livro_nome" not in st.session_state:
    st.session_state.livro_nome = ""

# --- INTERFACE PRINCIPAL ---
uploaded_file = st.file_uploader("Carrega o guião do audiolivro (.txt, .pdf, .epub)", type=["txt", "pdf", "epub"])

if uploaded_file is not None:
    file_bytes = uploaded_file.read()
    nome_base = uploaded_file.name.rsplit(".", 1)[0]
    
    if st.session_state.livro_nome != uploaded_file.name:
        st.session_state.livro_nome = uploaded_file.name
        st.session_state.arquivos_partes = []
        st.session_state.audio_completo = None

    texto_bruto = file_bytes.decode("utf-8", errors="ignore")
    
    with st.spinner("A fazer análise cénica do guião (pausas, tons e estrutura)..."):
        segmentos = analisar_guiao_em_segmentos(texto_bruto, ler_titulos_cap)
        partes_segmentadas = agrupar_segmentos_em_partes(segmentos, chars_por_parte)
        
    total_partes = len(partes_segmentadas)
    total_falas = sum(1 for s in segmentos if s['tipo'] == 'fala')
    total_pausas = sum(1 for s in segmentos if s['tipo'] == 'pausa')
    total_chars = sum(len(s['texto']) for s in segmentos if s['tipo'] == 'fala')

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Caracteres de Locução", f"{total_chars:,}")
    col2.metric("Blocos de Entoação", f"{total_falas:,}")
    col3.metric("Pausas [P: Xs] Ativas", f"{total_pausas:,}")
    col4.metric("Partes Calculadas", total_partes)

    with st.expander("🔍 Inspecionar Guião Interpretado (Como o Narrador vai ler)"):
        amostra = []
        for s in segmentos[:25]:
            if s['tipo'] == 'pausa':
                amostra.append(f"⏸️ *[Silêncio de {s['segundos']}s]*")
            else:
                amostra.append(f"🎙️ **(Vel: {s['rate']} | Tom: {s['pitch']})**: {s['texto']}")
        st.markdown("\n\n".join(amostra))

    st.subheader("🎯 Intervalo de Gravação")
    col_ini, col_fim = st.columns(2)
    parte_inicial = col_ini.number_input("Começar na Parte", min_value=1, max_value=total_partes, value=1)
    parte_final = col_fim.number_input("Terminar na Parte", min_value=parte_inicial, max_value=total_partes, value=total_partes)

    if st.button("🚀 Iniciar Gravação com Direção de Voz", type="primary", use_container_width=True):
        st.session_state.arquivos_partes = []
        st.session_state.audio_completo = None
        
        indices = list(range(parte_inicial - 1, parte_final))
        total_a_gerar = len(indices)
        
        gerar_partes = modo_geracao in ["Vários Áudios (Por Partes)", "Ambos (Partes + Áudio Completo)"]
        gerar_completo = modo_geracao in ["Áudio Único (Livro Completo)", "Ambos (Partes + Áudio Completo)"]
        
        buffer_completo = io.BytesIO()
        status_box = st.empty()
        progresso = st.progress(0)
        
        st.markdown("---")
        st.subheader("⚡ Ficheiros Gerados em Tempo Real")
        container_tempo_real = st.container()

        for step, idx in enumerate(indices):
            num_parte = idx + 1
            status_box.info(f"🎙️ A gravar Parte {num_parte} de {parte_final} (A aplicar pausas e entoação)...")
            
            segs_parte = partes_segmentadas[idx]
            audio_bytes = asyncio.run(sintetizar_parte(segs_parte, voice_id, interpretar_pausas, modular_tom))
            
            if gerar_completo and audio_bytes:
                buffer_completo.write(audio_bytes)
                
            primeira_fala = next((s['texto'] for s in segs_parte if s['tipo'] == 'fala'), "Início da parte...")
            nome_mp3 = f"{nome_base}_Parte_{num_parte:02d}.mp3"
            
            if gerar_partes and audio_bytes:
                st.session_state.arquivos_partes.append((nome_mp3, audio_bytes, primeira_fala))
                # Mostra imediatamente a parte acabada de criar no ecrã!
                with container_tempo_real:
                    with st.container(border=True):
                        st.markdown(f"✅ **{nome_mp3}** *(Pronto!)*")
                        st.caption(f"Excerto: \"{primeira_fala[:110]}...\"")
                        st.audio(audio_bytes, format="audio/mp3")
                        st.download_button(
                            label=f"📥 Descarregar {nome_mp3}",
                            data=audio_bytes,
                            file_name=nome_mp3,
                            mime="audio/mp3",
                            key=f"realtime_dl_{num_parte}"
                        )
            
            progresso.progress((step + 1) / total_a_gerar)

        status_box.empty()
        progresso.empty()
        
        if gerar_completo:
            nome_comp = f"{nome_base}_Audiolivro_Completo.mp3"
            st.session_state.audio_completo = (nome_comp, buffer_completo.getvalue())
            
        st.success("🎉 Gravação concluída com sucesso!")

# --- SECÇÃO FIXA PARA DOWNLOADS E PACOTE ZIP ---
if st.session_state.audio_completo or st.session_state.arquivos_partes:
    st.markdown("---")
    st.subheader("📦 Pacote Final Concluído")
    
    if st.session_state.audio_completo:
        nome_comp, bytes_comp = st.session_state.audio_completo
        with st.container(border=True):
            st.markdown("### 🏆 Áudio Único (Obra Completa)")
            st.audio(bytes_comp, format="audio/mp3")
            st.download_button(
                label=f"📥 Descarregar Obra Completa ({nome_comp})",
                data=bytes_comp,
                file_name=nome_comp,
                mime="audio/mp3",
                type="primary",
                use_container_width=True,
                key="dl_comp_final"
            )

    if st.session_state.arquivos_partes:
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for nome_mp3, dados_mp3, _ in st.session_state.arquivos_partes:
                zf.writestr(nome_mp3, dados_mp3)
            if st.session_state.audio_completo:
                n_c, b_c = st.session_state.audio_completo
                zf.writestr(n_c, b_c)
                
        st.download_button(
            label="📦 Descarregar Todas as Partes num Ficheiro ZIP",
            data=zip_buffer.getvalue(),
            file_name=f"{st.session_state.livro_nome.rsplit('.', 1)[0]}_Audiolivro_VIP.zip",
            mime="application/zip",
            type="primary",
            use_container_width=True,
            key="dl_zip_final"
        )
