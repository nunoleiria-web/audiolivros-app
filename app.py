import streamlit as st
import asyncio
import edge_tts
import io
import re
import json
import zipfile

st.set_page_config(page_title="Estúdio Profissional de Audiolivros", page_icon="🎧", layout="centered")

st.title("🎧 Estúdio Profissional de Audiolivros")
st.markdown(
    "Processamento avançado de guiões com **captura otimizada por stream do edge-tts**, "
    "ritmo natural (-10%) e organização rigorosa por capítulos."
)

# --- FUNÇÃO PARA LIMPAR NOMES DE FICHEIROS ---
def limpar_nome_ficheiro(texto: str) -> str:
    texto = re.sub(r'\s*[—\-:]\s*', '_', texto.strip())
    texto = re.sub(r'\s+', '_', texto)
    texto = re.sub(r'[^\w_]', '', texto)
    return texto.lower()

# --- PARSER CÉNICO POR CAPÍTULOS ---
def analisar_guiao_por_capitulos(texto_bruto: str, anunciar_cap: bool = True) -> list[dict]:
    linhas = texto_bruto.split('\n')
    capitulos = []
    
    capitulo_atual = None
    parte_pendente = None

    rate_atual = "-10%"
    pitch_atual = "-1Hz"
    buffer_fala = []

    em_cabecalho_inicial = True
    em_creditos_finais = False

    re_separador = re.compile(r'^[=\-_*#]{3,}$')
    re_pausa = re.compile(r'^\[P:\s*(\d+(?:\.\d+)?)s\]$', re.IGNORECASE)
    re_musica = re.compile(r'^\[MÚSICA:.*?\]$', re.IGNORECASE)
    re_narrador = re.compile(r'^\[NARRADOR\s*[—\-:]\s*(.*?)\]$', re.IGNORECASE)
    re_fim = re.compile(r'^\[FIM.*?\]$', re.IGNORECASE)

    re_seccoes_ocultas = re.compile(
        r'^(\d+\.\s*)?(A HISTÓRIA|O CONCEITO.*|A CIÊNCIA.*|A FERRAMENTA.*|REFLEXÃO|A PONTE.*)$',
        re.IGNORECASE
    )

    re_parte = re.compile(r'^PARTE\s+[A-ZÀ-Ú0-9]+(?:\s*[—\-:]\s*.+)?$', re.IGNORECASE)
    re_capitulo = re.compile(
        r'^(CAPÍTULO\s+\d+[A-Z]?(?:\s*[—\-:].*)?|EPÍLOGO(?:\s*[—\-:].*)?|O SISTEMA MÍNIMO|NOTAS FINAIS|FONTES E FUNDAMENTOS)$',
        re.IGNORECASE
    )

    def descarregar_fala():
        if buffer_fala and capitulo_atual is not None:
            texto_bloco = " ".join(buffer_fala).strip()
            texto_bloco = re.sub(r'\s+', ' ', texto_bloco)
            if texto_bloco:
                capitulo_atual['segmentos'].append({
                    'tipo': 'fala',
                    'texto': texto_bloco,
                    'rate': rate_atual,
                    'pitch': pitch_atual
                })
            buffer_fala.clear()

    def iniciar_novo_capitulo(titulo_bruto: str):
        nonlocal capitulo_atual, parte_pendente, em_cabecalho_inicial
        descarregar_fala()
        em_cabecalho_inicial = False

        titulo_limpo_audio = re.sub(r'\s*[—\-]\s*', '. ', titulo_bruto).capitalize()
        titulo_limpo_audio = re.sub(r'\b17b\b', '17 B', titulo_limpo_audio, flags=re.IGNORECASE)

        capitulo_atual = {
            'titulo_exibicao': titulo_bruto,
            'slug': limpar_nome_ficheiro(titulo_bruto),
            'segmentos': []
        }
        capitulos.append(capitulo_atual)

        if parte_pendente:
            if anunciar_cap:
                parte_audio = re.sub(r'\s*[—\-]\s*', '. ', parte_pendente).capitalize()
                capitulo_atual['segmentos'].append({'tipo': 'pausa', 'segundos': 1.0})
                capitulo_atual['segmentos'].append({
                    'tipo': 'fala',
                    'texto': f"{parte_audio}.",
                    'rate': '-10%',
                    'pitch': '-1Hz'
                })
                capitulo_atual['segmentos'].append({'tipo': 'pausa', 'segundos': 1.5})
            parte_pendente = None

        if anunciar_cap:
            capitulo_atual['segmentos'].append({'tipo': 'pausa', 'segundos': 1.0})
            capitulo_atual['segmentos'].append({
                'tipo': 'fala',
                'texto': f"{titulo_limpo_audio}.",
                'rate': '-8%',
                'pitch': '-1Hz'
            })
            capitulo_atual['segmentos'].append({'tipo': 'pausa', 'segundos': 1.5})

    for linha in linhas:
        l = linha.strip()
        if not l:
            continue

        if re.match(r'^CRÉDITOS DO AUDIOBOOK$', l, re.IGNORECASE):
            descarregar_fala()
            em_creditos_finais = True
            continue

        if em_creditos_finais:
            if l.lower().startswith("obrigado por ouvires") and capitulo_atual is not None:
                capitulo_atual['segmentos'].append({'tipo': 'pausa', 'segundos': 1.5})
                capitulo_atual['segmentos'].append({
                    'tipo': 'fala',
                    'texto': l,
                    'rate': '-10%',
                    'pitch': '-1Hz'
                })
            continue

        if re_separador.match(l):
            continue

        if re_parte.match(l):
            descarregar_fala()
            parte_pendente = l
            em_cabecalho_inicial = False
            continue

        if re_capitulo.match(l):
            iniciar_novo_capitulo(l)
            continue

        if em_cabecalho_inicial:
            continue

        if re_seccoes_ocultas.match(l):
            descarregar_fala()
            if capitulo_atual is not None:
                capitulo_atual['segmentos'].append({'tipo': 'pausa', 'segundos': 1.0})
            continue

        if re_fim.match(l):
            descarregar_fala()
            if capitulo_atual is not None:
                capitulo_atual['segmentos'].append({'tipo': 'pausa', 'segundos': 1.5})
            continue

        if re_musica.match(l):
            descarregar_fala()
            continue

        m_pausa = re_pausa.match(l)
        if m_pausa:
            descarregar_fala()
            if capitulo_atual is not None:
                seg_original = float(m_pausa.group(1))
                seg_ajustado = min(seg_original, 2.5)
                capitulo_atual['segmentos'].append({'tipo': 'pausa', 'segundos': seg_ajustado})
            continue

        m_narrador = re_narrador.match(l)
        if m_narrador:
            descarregar_fala()
            instrucao_tom = m_narrador.group(1).lower()
            if "pausado" in instrucao_tom or "reflex" in instrucao_tom or "despedida" in instrucao_tom:
                rate_atual = "-12%"
                pitch_atual = "-2Hz"
            elif "sóbrio" in instrucao_tom or "grave" in instrucao_tom:
                rate_atual = "-10%"
                pitch_atual = "-2Hz"
            elif "íntimo" in instrucao_tom or "próximo" in instrucao_tom:
                rate_atual = "-10%"
                pitch_atual = "-1Hz"
            elif "informativo" in instrucao_tom or "claro" in instrucao_tom:
                rate_atual = "-6%"
                pitch_atual = "+0Hz"
            elif "prático" in instrucao_tom:
                rate_atual = "-8%"
                pitch_atual = "-1Hz"
            else:
                rate_atual = "-10%"
                pitch_atual = "-1Hz"
            continue

        l_limpa = re.sub(r'\[.*?\]', '', l)
        l_limpa = l_limpa.replace('→', ', ')
        l_limpa = re.sub(r'_{2,}', '...', l_limpa)
        if l_limpa.endswith('—'):
            l_limpa = l_limpa[:-1].strip() + ','
        else:
            l_limpa = l_limpa.replace(' — ', ', ')

        l_limpa = l_limpa.strip()
        if not l_limpa:
            continue

        buffer_fala.append(l_limpa)

    descarregar_fala()

    capitulos_validos = []
    for cap in capitulos:
        chars_cap = sum(len(s['texto']) for s in cap['segmentos'] if s['tipo'] == 'fala')
        if chars_cap > 0:
            cap['caracteres'] = chars_cap
            cap['num_falas'] = sum(1 for s in cap['segmentos'] if s['tipo'] == 'fala')
            cap['num_pausas'] = sum(1 for s in cap['segmentos'] if s['tipo'] == 'pausa')
            capitulos_validos.append(cap)

    for idx, cap in enumerate(capitulos_validos, 1):
        cap['indice'] = idx
        cap['nome_mp3'] = f"{idx:02d}_{cap['slug']}.mp3"

    return capitulos_validos

# --- FUNÇÃO DE SILÊNCIO NATIVO ---
async def obter_frame_silencio_nativo(voice: str) -> bytes:
    try:
        communicate = edge_tts.Communicate("ponto", voice)
        chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
        if chunks:
            ultimo = chunks[-1]
            return ultimo[-288:] if len(ultimo) >= 288 else ultimo
    except Exception:
        pass
    return b'\x00' * 320

# --- MOTOR DE GRAVAÇÃO OTIMIZADO (PADRÃO RECOMENDADO) ---
async def gravar_audio_otimizado(segmentos_cap: list[dict], voice: str) -> bytes:
    buffer_audio = io.BytesIO()
    silencio_base = None

    for b in segmentos_cap:
        if b['tipo'] == 'pausa':
            if silencio_base is None:
                silencio_base = await obter_frame_silencio_nativo(voice)
            if silencio_base:
                repeticoes = int(b['segundos'] * 18)
                buffer_audio.write(silencio_base * max(1, repeticoes))
        elif b['tipo'] == 'fala':
            communicate = edge_tts.Communicate(
                b['texto'], voice, rate=b['rate'], 
                pitch=b['pitch'], volume="+0%"
            )
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    buffer_audio.write(chunk["data"])

    return buffer_audio.getvalue()

# --- BARRA LATERAL ---
with st.sidebar:
    st.header("🎙️ Direção de Voz")
    vozes_disponiveis = {
        "🇵🇹 Duarte (PT - Masculina / Íntima)": "pt-PT-DuarteNeural",
        "🇵🇹 Raquel (PT - Feminina / Natural)": "pt-PT-RaquelNeural",
        "🇧🇷 Antonio (BR - Masculina / Profunda)": "pt-BR-AntonioNeural",
        "🇧🇷 Francisca (BR - Feminina / Suave)": "pt-BR-FranciscaNeural"
    }
    voz_selecionada = st.selectbox("Narrador", list(vozes_disponiveis.keys()))
    voice_id = vozes_disponiveis[voz_selecionada]

    anunciar_capitulos = st.checkbox("Anunciar títulos de Partes e Capítulos", value=True)
    fazer_overlap = st.checkbox("Repetir última frase da faixa anterior no início da seguinte", value=False)

# --- MEMÓRIA DA SESSÃO ---
if "arquivos_gerados" not in st.session_state:
    st.session_state.arquivos_gerados = []
if "livro_nome" not in st.session_state:
    st.session_state.livro_nome = ""

# --- INTERFACE PRINCIPAL ---
uploaded_file = st.file_uploader("Carrega o guião do audiolivro (.txt)", type=["txt"])

if uploaded_file is not None:
    file_bytes = uploaded_file.read()
    nome_base = uploaded_file.name.rsplit(".", 1)[0]

    if st.session_state.livro_nome != uploaded_file.name:
        st.session_state.livro_nome = uploaded_file.name
        st.session_state.arquivos_gerados = []

    texto_bruto = file_bytes.decode("utf-8", errors="ignore")
    capitulos = analisar_guiao_por_capitulos(texto_bruto, anunciar_capitulos)

    total_caps = len(capitulos)
    total_chars = sum(c['caracteres'] for c in capitulos)
    total_falas = sum(c['num_falas'] for c in capitulos)
    total_pausas = sum(c['num_pausas'] for c in capitulos)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Caracteres", f"{total_chars:,}")
    col2.metric("Blocos de Fala", f"{total_falas:,}")
    col3.metric("Pausas", f"{total_pausas:,}")
    col4.metric("Capítulos Totais", total_caps)

    with st.expander("📋 Capítulos Identificados", expanded=True):
        for c in capitulos:
            total_segs = len(c['segmentos'])
            st.markdown(f"**{c['nome_mp3']}** — {total_segs} segmentos, ~{c['caracteres']:,} caracteres")

    st.markdown("---")
    st.subheader("🎯 Intervalo de Gravação")
    col_i, col_f = st.columns(2)
    c_ini = col_i.number_input("Começar no Capítulo", min_value=1, max_value=total_caps, value=1)
    c_fim = col_f.number_input("Terminar no Capítulo", min_value=c_ini, max_value=total_caps, value=total_caps)

    if st.button("🚀 Gerar Audiolivro", type="primary", use_container_width=True):
        st.session_state.arquivos_gerados = []
        indices = list(range(c_ini - 1, c_fim))

        status = st.empty()
        prog = st.progress(0)
        area_tempo_real = st.container()

        for step, idx in enumerate(indices):
            cap = capitulos[idx]
            status.info(f"🎙️ A processar {cap['nome_mp3']} [{step + 1}/{len(indices)}]...")

            segs_a_gravar = list(cap['segmentos'])

            if idx > 0 and fazer_overlap:
                falas_ant = [s for s in capitulos[idx - 1]['segmentos'] if s['tipo'] == 'fala']
                if falas_ant:
                    ult_bloco = falas_ant[-1]
                    frases_ant = re.split(r'(?<=[.!?])\s+', ult_bloco['texto'])
                    if frases_ant and frases_ant[-1].strip():
                        segs_a_gravar.insert(0, {
                            'tipo': 'fala',
                            'texto': frases_ant[-1].strip(),
                            'rate': ult_bloco['rate'],
                            'pitch': ult_bloco['pitch']
                        })
                        segs_a_gravar.insert(1, {'tipo': 'pausa', 'segundos': 1.0})

            audio_mp3 = asyncio.run(gravar_audio_otimizado(segs_a_gravar, voice_id))
            resumo_txt = next((s['texto'] for s in cap['segmentos'] if s['tipo'] == 'fala'), "")[:100]

            st.session_state.arquivos_gerados.append((cap['nome_mp3'], audio_mp3, resumo_txt))

            with area_tempo_real:
                with st.container(border=True):
                    st.markdown(f"✅ **{cap['nome_mp3']}** *(~{cap['caracteres']:,} caracteres)*")
                    st.caption(f"\"{resumo_txt}...\"")
                    st.audio(audio_mp3, format="audio/mp3")
                    st.download_button(
                        f"📥 Descarregar {cap['nome_mp3']}",
                        data=audio_mp3,
                        file_name=cap['nome_mp3'],
                        mime="audio/mp3",
                        key=f"dl_cap_{cap['indice']}"
                    )

            prog.progress((step + 1) / len(indices))

        status.empty()
        prog.empty()
        st.success("🎉 Todos os capítulos selecionados foram gerados com sucesso!")

if len(st.session_state.arquivos_gerados) > 1:
    st.markdown("---")
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for n_m, d_m, _ in st.session_state.arquivos_gerados:
            zf.writestr(n_m, d_m)
    st.download_button(
        "📦 Descarregar Audiolivro Completo em ZIP",
        data=zip_buf.getvalue(),
        file_name=f"{st.session_state.livro_nome.rsplit('.', 1)[0]}_Capítulos_Completos.zip",
        mime="application/zip",
        type="primary",
        use_container_width=True
    )
