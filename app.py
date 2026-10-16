import streamlit as st
from google.cloud import texttospeech
import io
import re
import json
import zipfile

st.set_page_config(page_title="Estúdio Profissional de Audiolivros (Google Cloud TTS)", page_icon="🎧", layout="centered")

st.title("🎧 Estúdio Profissional de Audiolivros — Google Cloud TTS")
st.markdown(
    "Processamento avançado integrado com as vozes neurais de alta fidelidade da **Google Cloud**, "
    "garantindo qualidade de estúdio profissional e suporte nativo a pausas calibradas."
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
                seg_ajustado = min(seg_original, 2.5)
                capitulo_atual['segmentos'].append({'tipo': 'pausa', 'segundos': seg_ajustado})
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

# --- MOTOR DE GRAVAÇÃO GOOGLE CLOUD TTS ---
def gravar_audio_google(segmentos_cap: list[dict], voz_nome: str, velocidade: float) -> bytes:
    client = texttospeech.TextToSpeechClient()
    buffer_final = io.BytesIO()

    for b in segmentos_cap:
        if b['tipo'] == 'pausa':
            segundos = b['segundos']
            ssml_pausa = f'<speak><break time="{int(segundos * 1000)}ms"/></speak>'
            input_ssml = texttospeech.SynthesisInput(ssml=ssml_pausa)
            voice = texttospeech.VoiceSelectionParams(
                language_code="pt-PT",
                name=voz_nome,
                ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL
            )
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3,
                sample_rate_hertz=44100
            )
            try:
                res = client.synthesize_speech(input=input_ssml, voice=voice, audio_config=audio_config)
                buffer_final.write(res.audio_content)
            except Exception:
                pass
        elif b['tipo'] == 'fala':
            input_text = texttospeech.SynthesisInput(text=b['texto'])
            voice = texttospeech.VoiceSelectionParams(
                language_code="pt-PT",
                name=voz_nome,
                ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL
            )
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3,
                speaking_rate=velocidade,
                sample_rate_hertz=44100
            )
            res = client.synthesize_speech(input=input_text, voice=voice, audio_config=audio_config)
            buffer_final.write(res.audio_content)

    return buffer_final.getvalue()

# --- BARRA LATERAL ---
with st.sidebar:
    st.header("🎙️ Google Cloud TTS")
    
    vozes_disponiveis = {
        "🇵🇹 Neural2-B (Masculina - PT)": "pt-PT-Neural2-B",
        "🇵🇹 Neural2-A (Feminina - PT)": "pt-PT-Neural2-A",
        "🇵🇹 Neural2-C (Masculina Alternativa - PT)": "pt-PT-Neural2-C",
        "🇵🇹 Neural2-D (Feminina Alternativa - PT)": "pt-PT-Neural2-D"
    }
    
    voz_selecionada = st.selectbox("Voz Neural Google", list(vozes_disponiveis.keys()))
    voice_id = vozes_disponiveis[voz_selecionada]
    
    velocidade_narracao = st.slider("Velocidade da Fala", min_value=0.80, max_value=1.00, value=0.92, step=0.01)
    anunciar_capitulos = st.checkbox("Anunciar títulos de Partes e Capítulos", value=True)

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

    if st.button("🚀 Gerar Audiolivro com Google Cloud TTS", type="primary", use_container_width=True):
        st.session_state.arquivos_gerados = []
        indices = list(range(c_ini - 1, c_fim))

        status = st.empty()
        prog = st.progress(0)
        area_tempo_real = st.container()

        for step, idx in enumerate(indices):
            cap = capitulos[idx]
            status.info(f"🎙️ A processar {cap['nome_mp3']} via Google Cloud [{step + 1}/{len(indices)}]...")

            segs_a_gravar = list(cap['segmentos'])
            audio_mp3 = gravar_audio_google(segs_a_gravar, voice_id, velocidade_narracao)
            resumo_txt = next((s['texto'] for s in cap['segmentos'] if s['tipo'] == 'fala'), "")[:100]

            st.session_state.arquivos_gerados.append((cap['nome_mp3'], audio_mp3, resumo_txt))

            with area_tempo_real:
                with st.container(border=True):
                    st.markdown(f"✅ **{cap['nome_mp3']}** *(Google Cloud Neural2 | ~{cap['caracteres']:,} caracteres)*")
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
        st.success("🎉 Todos os capítulos selecionados foram gerados com o Google Cloud TTS com sucesso!")

if len(st.session_state.arquivos_gerados) > 1:
    st.markdown("---")
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for n_m, d_m, _ in st.session_state.arquivos_gerados:
            zf.writestr(n_m, d_m)
    st.download_button(
        "📦 Descarregar Audiolivro Completo em ZIP (Google Cloud)",
        data=zip_buf.getvalue(),
        file_name=f"{st.session_state.livro_nome.rsplit('.', 1)[0]}_Google_Cloud_TTS.zip",
        mime="application/zip",
        type="primary",
        use_container_width=True
    )
