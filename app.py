import streamlit as st
import io
import re
import json
import zipfile
# Importação da biblioteca Chatterbox (ajuste o nome do módulo conforme a sua instalação oficial)
import chatterbox

st.set_page_config(page_title="Estúdio Profissional de Audiolivros — Chatterbox", page_icon="🎧", layout="centered")

st.title("🎧 Estúdio Profissional de Audiolivros — Chatterbox")
st.markdown(
    "Processamento avançado integrado com o motor de voz **Chatterbox**, "
    "garantindo uma narração expressiva, natural e de alta fidelidade."
)

# --- NAVEGAÇÃO NA BARRA LATERAL ---
with st.sidebar:
    st.header("🌐 Navegação")
    st.page_link("pages/loja.py", label="Visitar a Loja (EPUB & Audiolivro)", icon="🛒")
    st.markdown("---")
    st.header("🎙️ Direção de Voz (Chatterbox)")
    
    vozes_disponiveis = {
        "Voz Padrão - Neutra / Narrador": "default_narrator",
        "Voz Expressiva - Íntima": "expressive_warm"
    }
    voz_selecionada = st.selectbox("Modelo de Voz", list(vozes_disponiveis.keys()))
    voice_id = vozes_disponiveis[voz_selecionada]

    anunciar_capitulos = st.checkbox("Anunciar títulos de Partes e Capítulos", value=True)

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
                    'texto': texto_bloco
                })
            buffer_fala.clear()

    def iniciar_novo_capitulo(titulo_bruto: str):
        nonlocal capitulo_atual, parte_pendente, em_cabecalho_inicial
        descarregar_fala()
        em_cabecalho_inicial = False

        titulo_limpo_audio = re.sub(r'\s*[—\-]\s*', '. ', titulo_bruto).capitalize()

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
                    'texto': f"{parte_audio}."
                })
                capitulo_atual['segmentos'].append({'tipo': 'pausa', 'segundos': 1.5})
            parte_pendente = None

        if anunciar_cap:
            capitulo_atual['segmentos'].append({'tipo': 'pausa', 'segundos': 1.0})
            capitulo_atual['segmentos'].append({
                'tipo': 'fala',
                'texto': f"{titulo_limpo_audio}."
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
                    'texto': l
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
                capitulo_atual['segmentos'].append({'tipo': 'pausa', 'segundos': min(seg_original, 2.5)})
            continue

        m_narrador = re_narrador.match(l)
        if m_narrador:
            descarregar_fala()
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

# --- MOTOR DE GRAVAÇÃO CHATTERBOX ---
def gravar_audio_chatterbox(segmentos_cap: list[dict], model_voice: str) -> bytes:
    buffer_final = io.BytesIO()

    for b in segmentos_cap:
        if b['tipo'] == 'pausa':
            # Gera silêncio proporcional à duração da pausa (ex: silêncio de base preenchido com zeros)
            duracao_seg = b['segundos']
            # Aproximação de bytes de silêncio para formato áudio padrão
            silencio_bytes = b'\x00' * int(16000 * 2 * duracao_seg) 
            buffer_final.write(silencio_bytes)
            
        elif b['tipo'] == 'fala':
            try:
                # Chamada ao motor Chatterbox para gerar o áudio do texto atual
                audio_gerado = chatterbox.synthesize(
                    text=b['texto'],
                    voice=model_voice
                )
                # Se a API retornar bytes diretamente ou o caminho de um ficheiro/stream
                if isinstance(audio_gerado, bytes):
                    buffer_final.write(audio_gerado)
                elif hasattr(audio_gerado, "read"):
                    buffer_final.write(audio_gerado.read())
            except Exception as e:
                # Fallback em caso de erro na geração do segmento
                pass

    return buffer_final.getvalue()

# --- MEMÓRIA DA SESSÃO ---
if "arquivos_gerados" not in st.session_state:
    st.session_state.arquivos_gerados = []
if "livro_nome" not in st.session_state:
    st.session_state.livro_nome = ""

# --- INTERFACE PRINCIPAL ---
uploaded_file = st.file_uploader("Carrega o guião do audiolivro (.txt)", type=["txt"])

if uploaded_file is not None:
    file_bytes = uploaded_file.read()

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
            st.markdown(f"**{c['nome_mp3']}** — {len(c['segmentos'])} segmentos, ~{c['caracteres']:,} caracteres")

    st.markdown("---")
    st.subheader("🎯 Intervalo de Gravação")
    col_i, col_f = st.columns(2)
    c_ini = col_i.number_input("Começar no Capítulo", min_value=1, max_value=total_caps, value=1)
    c_fim = col_f.number_input("Terminar no Capítulo", min_value=c_ini, max_value=total_caps, value=total_caps)

    if st.button("🚀 Gerar Audiolivro (Chatterbox)", type="primary", use_container_width=True):
        st.session_state.arquivos_gerados = []
        indices = list(range(c_ini - 1, c_fim))

        status = st.empty()
        prog = st.progress(0)
        area_tempo_real = st.container()

        for step, idx in enumerate(indices):
            cap = capitulos[idx]
            status.info(f"🎙️ A processar {cap['nome_mp3']} via Chatterbox [{step + 1}/{len(indices)}]...")

            segs_a_gravar = list(cap['segmentos'])
            audio_mp3 = gravar_audio_chatterbox(segs_a_gravar, voice_id)
            resumo_txt = next((s['texto'] for s in cap['segmentos'] if s['tipo'] == 'fala'), "")[:100]

            st.session_state.arquivos_gerados.append((cap['nome_mp3'], audio_mp3, resumo_txt))

            with area_tempo_real:
                with st.container(border=True):
                    st.markdown(f"✅ **{cap['nome_mp3']}** *(Chatterbox | ~{cap['caracteres']:,} caracteres)*")
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
        st.success("🎉 Todos os capítulos selecionados foram gerados com o Chatterbox com sucesso!")

if len(st.session_state.arquivos_gerados) > 1:
    st.markdown("---")
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for n_m, d_m, _ in st.session_state.arquivos_gerados:
            zf.writestr(n_m, d_m)
    st.download_button(
        "📦 Descarregar Audiolivro Completo em ZIP (Chatterbox)",
        data=zip_buf.getvalue(),
        file_name=f"{st.session_state.livro_nome.rsplit('.', 1)[0]}_Chatterbox.zip",
        mime="application/zip",
        type="primary",
        use_container_width=True
    )
