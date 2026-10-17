import streamlit as st
import asyncio
import io
import re
import json
import zipfile
import subprocess
import tempfile
import unicodedata
import wave
from pathlib import Path
import numpy as np

# Tenta importar o chatterbox; se não estiver instalado no ambiente, avisa na interface
try:
    import torch
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    CHATTERBOX_DISPONIVEL = True
except ImportError:
    CHATTERBOX_DISPONIVEL = False

st.set_page_config(page_title="Estúdio Profissional de Audiolivros — Chatterbox", page_icon="🎧", layout="centered")

# --- NAVEGAÇÃO NA BARRA LATERAL ---
with st.sidebar:
    st.header("🌐 Navegação")
    st.page_link("pages/loja.py", label="Visitar a Loja (EPUB & Audiolivro)", icon="🛒")
    st.markdown("---")
    st.header("🎙️ Direção de Voz (Chatterbox)")
    
    exagero = st.slider("Expressividade", min_value=0.25, max_value=0.70, value=0.40, step=0.05)
    cfg_weight = st.slider("Ritmo (CFG)", min_value=0.10, max_value=0.60, value=0.30, step=0.05)
    seed = st.number_input("Seed de Aleatoriedade", value=1234, step=1)
    
    anunciar_capitulos = st.checkbox("Anunciar títulos de Partes e Capítulos", value=True)
    modo_teste = st.checkbox("Modo Teste (Apenas primeiros parágrafos)", value=False)

st.title("🎧 Estúdio Profissional de Audiolivros — Chatterbox")
st.markdown(
    "Processamento avançado integrado com o motor local **Chatterbox Multilingual** "
    "e masterização compatível com padrões de estúdio."
)

st.markdown("---")

# Constantes de Padrão ACX/Áudio
ALVO_RMS_DB = -20.5
RUIDO_SALA_DB = -80.0
MAX_CHARS = 240

PRONUNCIA = {
    'Kahneman': 'Câneman', 'Tversky': 'Tvérsqui', 'Deci': 'Dêci', 'Gollwitzer': 'Gólvitzer',
    'Csikszentmihalyi': 'Tchícsentmihái', 'Frankl': 'Frânkel', 'Baumeister': 'Báumaister',
    'Wansink': 'Uônsinc', 'Sinek': 'Sáinec', 'Ryan': 'Ráian', 'Clear': 'Clíar',
    'Hagger': 'Hâguer', 'Wood': 'Uúd',
}

# --- FUNÇÕES AUXILIARES DE TEXTO E ÁUDIO ---
def falar(t):
    t = t.replace('\u00a0', ' ')
    t = re.sub(r'^(Passo|Fundação|Estatuto)\s(\d+)\s*—\s', r'\1 \2. ', t)
    t = re.sub(r'\bParte (I{1,3}|IV)\b', lambda m: 'Parte ' + {'I': 'um', 'II': 'dois', 'III': 'três', 'IV': 'quatro'}[m.group(1)], t)
    t = t.replace(' & ', ' e ')
    t = re.sub(r'_{2,}', ' [[PL]] ', t)
    for k, v in PRONUNCIA.items():
        t = re.sub(r'\b' + k + r'\b', v, t)
    t = re.sub(r'[“”«»"]', '', t)
    t = t.replace(' — ', ', ').replace('—', ', ')
    t = t.replace('(', ', ').replace(')', ', ')
    t = re.sub(r'\s*,\s*,', ',', t)
    t = re.sub(r'\s+,', ',', t)
    t = re.sub(r'\s+', ' ', t).strip(' ,')
    return t

def dividir(texto):
    frases = re.split(r'(?<=[.!?…])\s+', texto)
    partes, atual = [], ''
    for f in frases:
        sub = re.split(r'(?<=[,;:])\s+', f) if len(f) > MAX_CHARS else [f]
        for s in sub:
            if atual and len(atual) + 1 + len(s) > MAX_CHARS:
                partes.append(atual)
                atual = s
            else:
                atual = (atual + ' ' + s).strip()
    if atual:
        partes.append(atual)
    return partes

def ruido_sala(seg, sr):
    n = int(seg * sr)
    return (np.random.randn(n) * (10 ** (RUIDO_SALA_DB / 20))).astype(np.float32)

def aparar_fim(x, sr, limiar_db=-50, deixar=0.05):
    lim = 10 ** (limiar_db / 20)
    idx = np.where(np.abs(x) > lim)[0]
    if len(idx) == 0:
        return x
    return x[:min(len(x), idx[-1] + int(deixar * sr))]

def pausa_depois(tp, t):
    return {'rotulo': 0.5, 'h1': 1.6, 'h2': 1.2, 'pergunta': 3.0, 'item': 1.0, 'key': 2.0, 'fonte': 0.8}.get(
        tp, 1.4 if len(t.split()) <= 12 else 0.7)

def pausa_antes(tp):
    return {'h2': 0.6, 'key': 1.5}.get(tp, 0.0)

# --- CARREGAMENTO DO MODELO CHATTERBOX ---
@st.cache_resource
def carregar_modelo_chatterbox():
    if not CHATTERBOX_DISPONIVEL:
        return None, 24000
    dispositivo = 'cuda' if torch.cuda.is_available() else 'cpu'
    modelo = ChatterboxMultilingualTTS.from_pretrained(device=dispositivo)
    return modelo, modelo.sr

# --- PARSER DE GUIÃO / TXT ---
def analisar_guiao_texto(texto_bruto: str, anunciar_cap: bool = True) -> list[dict]:
    linhas = texto_bruto.split('\n')
    capitulos = []
    capitulo_atual = None
    buffer_fala = []

    def descarregar_fala():
        if buffer_fala and capitulo_atual is not None:
            texto_bloco = " ".join(buffer_fala).strip()
            if texto_bloco:
                capitulo_atual['segmentos'].append({'tipo': 'fala', 'texto': texto_bloco})
            buffer_fala.clear()

    # Cria uma estrutura padrão baseada em blocos se for um ficheiro de texto corrido ou guião
    capitulo_atual = {'titulo_exibicao': 'Audiolivro Completo', 'slug': 'audiolivro', 'segmentos': []}
    capitulos.append(capitulo_atual)

    for linha in linhas:
        l = linha.strip()
        if not l:
            continue
        if l.startswith("CAPÍTULO") or l.startswith("PARTE"):
            descarregar_fala()
            capitulo_atual = {'titulo_exibicao': l, 'slug': unicodedata.normalize('NFKD', l).encode('ascii', 'ignore').decode().lower().replace(' ', '_'), 'segmentos': []}
            capitulos.append(capitulo_atual)
            if anunciar_cap:
                capitulo_atual['segmentos'].append({'tipo': 'pausa', 'segundos': 1.0})
                capitulo_atual['segmentos'].append({'tipo': 'fala', 'texto': f"{l}."})
            continue
        
        buffer_fala.append(l)

    descarregar_fala()
    
    # Se não detetou capítulos estruturados, agrupa tudo num bloco único válido
    if len(capitulos) > 1 and len(capitulos[0]['segmentos']) == 0:
        capitulos.pop(0)

    for idx, cap in enumerate(capitulos, 1):
        cap['indice'] = idx
        cap['nome_mp3'] = f"{idx:02d}_{cap['slug']}.mp3"
        cap['caracteres'] = sum(len(s['texto']) for s in cap['segmentos'] if s['tipo'] == 'fala')

    return [c for c in capitulos if c['caracteres'] > 0]

# --- CONSTRUÇÃO DE ÁUDIO COM CHATTERBOX ---
def construir_audio_sessao(segs, modelo, sr, teste=False):
    if teste:
        segs = segs[:7]
    partes = [ruido_sala(1.0, sr)]
    
    for tp, t in segs:
        if not t:
            continue
        partes.append(ruido_sala(pausa_antes(tp), sr))
        fala = falar(t)
        pedacos = re.split(r'\[\[(PL)\]\]', fala)
        for i, pedaco in enumerate(pedacos):
            if i % 2 == 1:
                partes.append(ruido_sala(1.5, sr))
                continue
            for c in dividir(pedaco.strip()):
                if not re.search(r'\w', c):
                    continue
                if modelo is not None:
                    if seed is not None:
                        torch.manual_seed(seed)
                    res = modelo.generate(c, language_id='pt', exaggeration=exagero, cfg_weight=cfg_weight)
                    audio_arr = res.squeeze().cpu().numpy()
                else:
                    # Simulação caso o chatterbox não esteja instalado localmente
                    audio_arr = ruido_sala(0.5, sr)
                
                partes.append(aparar_fim(audio_arr, sr))
                partes.append(ruido_sala(0.18, sr))
        partes.append(ruido_sala(pausa_depois(tp, t), sr))
    
    partes.append(ruido_sala(3.0, sr))
    audio = np.concatenate(partes)
    pico = np.max(np.abs(audio)) or 1.0
    return (audio * (0.89 / pico)).astype(np.float32)

def guardar_wav_temp(caminho, x, sr):
    y = np.clip(x, -1, 1)
    with wave.open(str(caminho), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((y * 32767).astype('<i2').tobytes())

# --- MEMÓRIA DE SESSÃO ---
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
    capitulos = analisar_guiao_texto(texto_bruto, anunciar_capitulos)

    total_caps = len(capitulos)
    total_chars = sum(c['caracteres'] for c in capitulos)

    col1, col2, col3 = st.columns(3)
    col1.metric("Caracteres Totais", f"{total_chars:,}")
    col2.metric("Capítulos Identificados", total_caps)
    col3.metric("Motor Ativo", "Chatterbox (Local)" if CHATTERBOX_DISPONIVEL else "Modo Simulação")

    with st.expander("📋 Capítulos Identificados", expanded=True):
        for c in capitulos:
            st.markdown(f"**{c['nome_mp3']}** — *{c['titulo_exibicao']}* (~{c['caracteres']:,} caracteres)")

    st.markdown("---")
    
    if st.button("🚀 Gerar Audiolivro com Chatterbox", type="primary", use_container_width=True):
        modelo, sr = carregar_modelo_chatterbox()
        st.session_state.arquivos_gerados = []

        status = st.empty()
        prog = st.progress(0)
        area_tempo_real = st.container()

        for step, cap in enumerate(capitulos):
            status.info(f"🎙️ A processar {cap['nome_mp3']} [{step + 1}/{total_caps}]...")

            # Converte os segmentos para o formato esperado pelo construtor
           segs_formatados = []
for s in cap['segmentos']:
    if s.get('tipo') == 'fala' and 'texto' in s:
        segs_formatados.append(('fala', s['texto']))
    elif s.get('tipo') == 'pausa' and 'segundos' in s:
        segs_formatados.append(('pausa', s['segundos']))
    else:
        st.warning(f"Segmento inválido ignorado: {s}")
            
            audio_gerado = construir_audio_sessao(segs_formatados, modelo, sr, modo_teste)
            
            # Converte para bytes de MP3 utilizando stream em memória ou wav temporário
            tmp_wav = Path(tempfile.mktemp(suffix=".wav"))
            guardar_wav_temp(tmp_wav, audio_gerado, sr)
            
            with open(tmp_wav, "rb") as f_wav:
                audio_bytes = f_wav.read()
            tmp_wav.unlink(missing_ok=True)

            resumo_txt = cap['segmentos'][0]['texto'][:100] if cap['segmentos'] else ""
            st.session_state.arquivos_gerados.append((cap['nome_mp3'], audio_bytes, resumo_txt))

            with area_tempo_real:
                with st.container(border=True):
                    st.markdown(f"✅ **{cap['nome_mp3']}** *(Chatterbox | ~{cap['caracteres']:,} caracteres)*")
                    st.audio(audio_bytes, format="audio/mp3")
                    st.download_button(
                        f"📥 Descarregar {cap['nome_mp3']}",
                        data=audio_bytes,
                        file_name=cap['nome_mp3'],
                        mime="audio/mp3",
                        key=f"dl_cap_{cap['indice']}"
                    )

            prog.progress((step + 1) / total_caps)

        status.empty()
        prog.empty()
        st.success("🎉 Processamento concluído com sucesso!")

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
