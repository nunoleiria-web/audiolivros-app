import streamlit as st
import asyncio
import edge_tts
import io
import re
import json
import zipfile
from pathlib import Path

st.set_page_config(page_title="Estúdio Profissional de Audiolivros", page_icon="🎧", layout="centered")

st.title("🎧 Estúdio Profissional de Audiolivros")
st.markdown(
    "Processamento avançado de guiões com **continuidade entre partes** (o ficheiro seguinte começa na última frase do anterior), "
    "pausas exatas e vozes em Português de alta qualidade."
)

# --- FUNÇÃO DE ANÁLISE DE GUIÃO (PARSER CÉNICO STANDALONE) ---
def analisar_guiao_completo(texto_bruto: str, anunciar_cap: bool = True) -> list[dict]:
    linhas = texto_bruto.split('\n')
    segmentos = []

    rate_atual = "-6%"
    pitch_atual = "-1Hz"
    buffer_fala = []

    em_cabecalho_inicial = True
    em_creditos_finais = False
    linhas_processadas = 0
    MAX_CABECALHO = 100

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

    re_separador = re.compile(r'^[=\-_*#]{3,}$')
    re_pausa = re.compile(r'^\[P:\s*(\d+(?:\.\d+)?)s\]$', re.IGNORECASE)
    re_musica = re.compile(r'^\[MÚSICA:.*?\]$', re.IGNORECASE)
    re_narrador = re.compile(r'^\[NARRADOR\s*[—\-:]\s*(.*?)\]$', re.IGNORECASE)
    re_fim = re.compile(r'^\[FIM.*?\]$', re.IGNORECASE)

    re_seccoes_ocultas = re.compile(
        r'^(\d+\.\s*)?(O CONCEITO|A CIÊNCIA|A FERRAMENTA.*|REFLEXÃO|A PONTE.*)$',
        re.IGNORECASE
    )

    re_capitulo_ou_parte = re.compile(
        r'^(CAPÍTULO\s+\d+[A-Z]?\s*[—\-].+|PARTE\s+[A-ZÀ-Ú]+\s*[—\-].+|EPÍLOGO\s*[—\-].+|O SISTEMA MÍNIMO|NOTAS FINAIS)$',
        re.IGNORECASE
    )

    for linha in linhas:
        l = linha.strip()
        if not l:
            continue

        linhas_processadas += 1
        if em_cabecalho_inicial and linhas_processadas > MAX_CABECALHO:
            em_cabecalho_inicial = False

        if re.match(r'^CRÉDITOS DO AUDIOBOOK$', l, re.IGNORECASE):
            descarregar_fala()
            em_creditos_finais = True
            continue

        if em_creditos_finais:
            if l.lower().startswith("obrigado por ouvires"):
                segmentos.append({'tipo': 'pausa', 'segundos': 2.0})
                segmentos.append({'tipo': 'fala', 'texto': l, 'rate': '-10%', 'pitch': '-2Hz'})
            continue

        if re_separador.match(l):
            continue

        if re_capitulo_ou_parte.match(l):
            em_cabecalho_inicial = False
            descarregar_fala()
            segmentos.append({'tipo': 'pausa', 'segundos': 2.0})
            if anunciar_cap:
                titulo_limpo = re.sub(r'\s*[—\-]\s*', '. ', l).capitalize()
                titulo_limpo = re.sub(r'17b', '17 B', titulo_limpo, flags=re.IGNORECASE)
                segmentos.append({
                    'tipo': 'fala',
                    'texto': f"{titulo_limpo}.",
                    'rate': '-10%',
                    'pitch': '-2Hz'
                })
                segmentos.append({'tipo': 'pausa', 'segundos': 2.5})
            continue

        if em_cabecalho_inicial:
            continue

        if re_seccoes_ocultas.match(l):
            descarregar_fala()
            segmentos.append({'tipo': 'pausa', 'segundos': 1.5})
            continue

        if re_fim.match(l):
            descarregar_fala()
            segmentos.append({'tipo': 'pausa', 'segundos': 3.0})
            continue

        if re_musica.match(l):
            descarregar_fala()
            segmentos.append({'tipo': 'pausa', 'segundos': 2.5})
            continue

        m_pausa = re_pausa.match(l)
        if m_pausa:
            descarregar_fala()
            seg = float(m_pausa.group(1))
            segmentos.append({'tipo': 'pausa', 'segundos': seg})
            continue

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

        l_limpa = re.sub(r'\[.*?\]', '', l)
        l_limpa = l_limpa.replace('→', '... ')
        l_limpa = re.sub(r'_{2,}', '...', l_limpa)
        if l_limpa.endswith('—'):
            l_limpa = l_limpa[:-1].strip() + '...'
        else:
            l_limpa = l_limpa.replace(' — ', ', ')

        l_limpa = l_limpa.strip()
        if not l_limpa:
            continue

        if l_limpa[-1] not in '.!?:;,…"\'”':
            l_limpa += '.'

        buffer_fala.append(l_limpa)

    descarregar_fala()
    return segmentos

def agrupar_em_partes(segmentos: list[dict], max_chars: int = 8000) -> list[list[dict]]:
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

# --- FUNÇÃO DE SILÊNCIO NATIVO ROBUSTA ---
async def obter_frame_silencio_nativo(voice: str) -> bytes:
    try:
        communicate = edge_tts.Communicate(" ", voice)
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

async def gravar_parte_audio(blocos_parte: list[dict], voice: str) -> bytes:
    buffer_final = io.BytesIO()
    silencio_base = None

    for b in blocos_parte:
        if b['tipo'] == 'pausa':
            if silencio_base is None:
                silencio_base = await obter_frame_silencio_nativo(voice)
            if silencio_base:
                repeticoes = int(b['segundos'] * 18)
                buffer_final.write(silencio_base * max(1, repeticoes))
        elif b['tipo'] == 'fala':
            communicate = edge_tts.Communicate(
                b['texto'], 
                voice, 
                rate=b['rate'], 
                pitch=b['pitch']
            )
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    buffer_final.write(chunk["data"])

    return buffer_final.getvalue()

# --- BARRA LATERAL: CONFIGURAÇÕES DE ESTÚDIO ---
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
    
    anunciar_capitulos = st.checkbox("Anunciar títulos de Capítulos e Partes", value=True)
    fazer_overlap = st.checkbox("Repetir última frase na parte seguinte (Continuidade)", value=True)
    
    st.subheader("📦 Organização de Ficheiros")
    chars_por_parte = st.slider(
        "Caracteres aproximados por Parte",
        min_value=3000,
        max_value=20000,
        value=8000,
        step=1000
    )

# --- MEMÓRIA DA SESSÃO ---
if "arquivos_partes" not in st.session_state:
    st.session_state.arquivos_partes = []
if "livro_nome" not in st.session_state:
    st.session_state.livro_nome = ""
if "segmentos_cache" not in st.session_state:
    st.session_state.segmentos_cache = None

# --- INTERFACE PRINCIPAL ---
uploaded_file = st.file_uploader("Carrega o guião do audiolivro (.txt)", type=["txt"])

if uploaded_file is not None:
    file_bytes = uploaded_file.read()
    nome_base = uploaded_file.name.rsplit(".", 1)[0]
    
    if st.session_state.livro_nome != uploaded_file.name:
        st.session_state.livro_nome = uploaded_file.name
        st.session_state.arquivos_partes = []
        texto_bruto = file_bytes.decode("utf-8", errors="ignore")
        st.session_state.segmentos_cache = analisar_guiao_completo(texto_bruto, anunciar_capitulos)

    segmentos = st.session_state.segmentos_cache
    partes = agrupar_em_partes(segmentos, chars_por_parte)
    
    total_partes = len(partes)
    total_falas = sum(1 for s in segmentos if s['tipo'] == 'fala')
    total_pausas = sum(1 for s in segmentos if s['tipo'] == 'pausa')
    total_chars = sum(len(s['texto']) for s in segmentos if s['tipo'] == 'fala')

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Caracteres", f"{total_chars:,}")
    col2.metric("Blocos de Fala", f"{total_falas:,}")
    col3.metric("Pausas", f"{total_pausas:,}")
    col4.metric("Total Partes", total_partes)

    with st.expander("🔍 Inspecionar Análise Cénica (Excertos)"):
        amostra = []
        for s in segmentos[:20]:
            if s['tipo'] == 'pausa':
                amostra.append(f"⏸️ *[Silêncio: {s['segundos']}s]*")
            else:
                amostra.append(f"🎙️ **(Vel: {s['rate']} | Tom: {s['pitch']})**: {s['texto']}")
        st.markdown("\n\n".join(amostra))

    col_dl1, col_dl2 = st.columns(2)
    with col_dl1:
        json_data = json.dumps({'segmentos': segmentos, 'partes': partes}, ensure_ascii=False, indent=2)
        st.download_button(
            "📥 Descarregar Estrutura JSON",
            data=json_data,
            file_name=f"{nome_base}_segmentos.json",
            mime="application/json",
            use_container_width=True
        )
    with col_dl2:
        relatorio_txt = f"Relatório de Gravação — {nome_base}\nTotal de Partes: {total_partes}\nTotal de Caracteres: {total_chars:,}"
        st.download_button(
            "📄 Descarregar Relatório TXT",
            data=relatorio_txt,
            file_name=f"{nome_base}_relatorio.txt",
            mime="text/plain",
            use_container_width=True
        )

    st.markdown("---")
    st.subheader("🎯 Intervalo de Gravação")
    col_i, col_f = st.columns(2)
    p_ini = col_i.number_input("Começar na Parte", min_value=1, max_value=total_partes, value=1)
    p_fim = col_f.number_input("Terminar na Parte", min_value=p_ini, max_value=total_partes, value=min(p_ini, total_partes))

    if st.button("🚀 Iniciar Síntese de Áudio com Direção Cénica", type="primary", use_container_width=True):
        st.session_state.arquivos_partes = []
        indices = list(range(p_ini - 1, p_fim))
        
        status = st.empty()
        prog = st.progress(0)
        area_tempo_real = st.container()

        for step, idx in enumerate(indices):
            num_p = idx + 1
            status.info(f"🎙️ A processar Parte {num_p} de {p_fim}...")
            
            # Preparar blocos da parte atual
            blocos_a_processar = list(partes[idx])
            
            # Se for Parte > 1 e o overlap estiver ativo, prepend a última frase da parte anterior
            if idx > 0 and fazer_overlap:
                bloco_anterior_fala = None
                for b in reversed(partes[idx - 1]):
                    if b['tipo'] == 'fala':
                        bloco_anterior_fala = b
                        break
                if bloco_anterior_fala:
                    frases = re.split(r'(?<=[.!?])\s+', bloco_anterior_fala['texto'])
                    if frases and frases[-1].strip():
                        ultima_frase = frases[-1].strip()
                        blocos_a_processar.insert(0, {
                            'tipo': 'fala',
                            'texto': ultima_frase,
                            'rate': bloco_anterior_fala.get('rate', '-6%'),
                            'pitch': bloco_anterior_fala.get('pitch', '-1Hz')
                        })

            audio_mp3 = asyncio.run(gravar_parte_audio(blocos_a_processar, voice_id))
            resumo_txt = next((b['texto'] for b in partes[idx] if b['tipo'] == 'fala'), "")[:100]
            nome_arq = f"{nome_base}_Parte_{num_p:02d}.mp3"
            
            st.session_state.arquivos_partes.append((nome_arq, audio_mp3, resumo_txt))
            
            with area_tempo_real:
                with st.container(border=True):
                    st.markdown(f"✅ **{nome_arq}**")
                    st.caption(f"\"{resumo_txt}...\"")
                    st.audio(audio_mp3, format="audio/mp3")
                    st.download_button(
                        f"📥 Descarregar {nome_arq}",
                        data=audio_mp3,
                        file_name=nome_arq,
                        mime="audio/mp3",
                        key=f"dl_rt_{num_p}"
                    )
            
            prog.progress((step + 1) / len(indices))

        status.empty()
        prog.empty()
        st.success("🎉 Síntese concluída com sucesso!")

if len(st.session_state.arquivos_partes) > 1:
    st.markdown("---")
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for n_m, d_m, _ in st.session_state.arquivos_partes:
            zf.writestr(n_m, d_m)
    st.download_button(
        "📦 Descarregar Todas as Partes em ZIP",
        data=zip_buf.getvalue(),
        file_name=f"{st.session_state.livro_nome.rsplit('.', 1)[0]}_Audiolivro_Completo.zip",
        mime="application/zip",
        type="primary",
        use_container_width=True
    )
