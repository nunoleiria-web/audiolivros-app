import streamlit as st
import fitz  # PyMuPDF
from bs4 import BeautifulSoup
import asyncio
import edge_tts
import io
import re
import zipfile

# Tentar importar o Kokoro para alta qualidade de IA
KOKORO_DISPONIVEL = False
try:
    from kokoro import KPipeline
    import soundfile as sf
    import torch
    KOKORO_DISPONIVEL = True
except Exception:
    KOKORO_DISPONIVEL = False

st.set_page_config(page_title="Gerador de Audiolivros com IA", page_icon="🎧", layout="centered")

st.title("🎧 Conversor de Livros para Audiolivro (IA Avançada)")
st.markdown("Converte o teu livro em partes, limpa automaticamente instruções de guião e separadores, e usa **vozes em Português**.")

# --- BARRA LATERAL: CONFIGURAÇÕES ---
with st.sidebar:
    st.header("⚙️ Configurações de Voz e IA")
    
    motores_disponiveis = ["Edge-TTS (Rápido e Estável)"]
    if KOKORO_DISPONIVEL:
        motores_disponiveis.insert(0, "Kokoro-82M (IA Hiper-Realista)")
        
    motor_escolhido = st.selectbox("Motor de Voz", motores_disponiveis)
    
    # Definição correta das vozes consoante o motor escolhido
    if "Kokoro" in motor_escolhido:
        vozes_disponiveis = {
            "🇧🇷 Dora (IA / Feminina - PT-BR)": "pf_dora",
            "🇧🇷 Alex (IA / Masculino - PT-BR)": "pm_alex",
            "🇧🇷 Santa (IA / Masculino - PT-BR)": "pm_santa",
            "🇺🇸 Heart (IA Premium / Feminina - Alternativa)": "af_heart"
        }
        lang_code = 'p'  # Código para português no pipeline do Kokoro
    else:
        vozes_disponiveis = {
            "🇵🇹 Raquel (PT - Natural / Feminina)": "pt-PT-RaquelNeural",
            "🇵🇹 Duarte (PT - Natural / Masculina)": "pt-PT-DuarteNeural",
            "🇧🇷 Francisca (BR - Natural / Feminina)": "pt-BR-FranciscaNeural",
            "🇧🇷 Antonio (BR - Natural / Masculino)": "pt-BR-AntonioNeural"
        }
    
    voz_selecionada = st.selectbox("Escolhe a Voz", list(vozes_disponiveis.keys()))
    voice_id = vozes_disponiveis[voz_selecionada]
    
    st.subheader("📦 Modo de Geração")
    modo_geracao = st.radio(
        "Como queres gerar o audiolivro?",
        [
            "Vários Áudios (Por Partes)",
            "Áudio Único (Livro Completo)",
            "Ambos (Partes + Áudio Completo)"
        ]
    )
    
    st.subheader("Tamanho de cada Parte")
    chars_por_parte = st.slider(
        "Caracteres por Parte",
        min_value=3000,
        max_value=25000,
        value=10000,
        step=1000,
        help="Define o tamanho de cada bloco de áudio."
    )
    
    frases_repetidas = st.number_input(
        "Frases a repetir no início de cada Parte",
        min_value=0,
        max_value=3,
        value=1,
        help="Garante a continuidade entre as partes individuais."
    )

# --- FUNÇÃO DE LIMPEZA AVANÇADA DE GUIÕES E SEPARADORES ---
def limpar_instrucoes_guiom(texto: str) -> str:
    texto_limpo = re.sub(r'\[.*?\]', '', texto)
    linhas = texto_limpo.split('\n')
    linhas_filtradas = []
    
    padroes_ignorar = re.compile(
        r'^(CAPÍTULO\s+\d+|PARTE\s+[A-ZÀ-Ú]+|O CONCEITO|A CIÊNCIA|A FERRAMENTA|REFLEXÃO|A PONTE|FIM DO CAPÍTULO|DURAÇÃO ESTIMADA|FORMATO|MÚSICA|PAUSAS|ESTRUTURA POR CAPÍTULO|TOM GERAL)',
        re.IGNORECASE
    )
    
    for linha in linhas:
        linha_strip = linha.strip()
        if re.match(r'^[=\-_*#]{3,}$', linha_strip):
            continue
        if padroes_ignorar.match(linha_strip):
            continue
        linhas_filtradas.append(linha)
        
    texto_final = "\n".join(linhas_filtradas)
    texto_final = re.sub(r'[=\-_*#]{3,}', '', texto_final)
    return texto_final

# --- FUNÇÃO DE EXTRAÇÃO UNIVERSAL BLINDADA ---
def extrair_documento_universal(file_bytes: bytes, extensao: str) -> str:
    try:
        doc = fitz.open(stream=file_bytes, filetype=extensao)
        texto = []
        for pagina in doc:
            t = pagina.get_text("text").replace("\n", " ").strip()
            if t:
                texto.append(t)
        doc.close()
        resultado = " ".join(texto).strip()
        if resultado:
            return limpar_instrucoes_guiom(resultado)
    except Exception:
        pass

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        texto = []
        for pagina in doc:
            t = pagina.get_text("text").replace("\n", " ").strip()
            if t:
                texto.append(t)
        doc.close()
        resultado = " ".join(texto).strip()
        if resultado:
            return limpar_instrucoes_guiom(resultado)
    except Exception:
        pass

    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
            textos_html = []
            for nome in sorted(z.namelist()):
                if nome.lower().endswith(('.xhtml', '.html', '.htm', '.xml')):
                    if 'toc' in nome.lower() or 'meta' in nome.lower() or 'container' in nome.lower():
                        continue
                    conteudo = z.read(nome)
                    soup = BeautifulSoup(conteudo, "html.parser")
                    for tag in soup(["script", "style"]):
                        tag.decompose()
                    t = soup.get_text(separator=" ").strip()
                    if t:
                        textos_html.append(t)
            resultado = " ".join(textos_html).strip()
            if resultado:
                return limpar_instrucoes_guiom(resultado)
    except Exception:
        pass

    texto_bruto = file_bytes.decode("utf-8", errors="ignore").strip()
    return limpar_instrucoes_guiom(texto_bruto)

def separar_em_frases(texto: str) -> list[str]:
    texto_limpo = re.sub(r'\s+', ' ', texto).strip()
    frases = re.split(r'(?<=[.!?])\s+', texto_limpo)
    return [f.strip() for f in frases if f.strip()]

def dividir_partes_base(frases: list[str], max_chars_parte: int) -> list[list[str]]:
    partes = []
    parte_atual = []
    tamanho_atual = 0
    
    for frase in frases:
        if tamanho_atual + len(frase) + 1 <= max_chars_parte or not parte_atual:
            parte_atual.append(frase)
            tamanho_atual += len(frase) + 1
        else:
            partes.append(parte_atual)
            parte_atual = [frase]
            tamanho_atual = len(frase) + 1
            
    if parte_atual:
        partes.append(parte_atual)
    return partes

# --- FUNÇÃO DE SÍNTESE DE ÁUDIO (HÍBRIDA) ---
async def gerar_audio_texto_edge(texto: str, voice: str) -> bytes:
    communicate = edge_tts.Communicate(texto, voice)
    mp3_buffer = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            mp3_buffer.write(chunk["data"])
    return mp3_buffer.getvalue()

def gerar_audio_kokoro(texto: str, voice: str) -> bytes:
    try:
        pipeline = KPipeline(lang_code=lang_code)
        generator = pipeline(texto, voice=voice, speed=1.0)
        audio_chunks = []
        for _, _, audio in generator:
            audio_chunks.append(audio)
        
        if audio_chunks:
            import numpy as np
            combined_audio = np.concatenate(audio_chunks)
            wav_buffer = io.BytesIO()
            sf.write(wav_buffer, combined_audio, 24000, format='WAV')
            return wav_buffer.getvalue()
    except Exception:
        pass
    return b""

# --- INICIALIZAR MEMÓRIA DA SESSÃO ---
if "arquivos_partes" not in st.session_state:
    st.session_state.arquivos_partes = []
if "audio_completo" not in st.session_state:
    st.session_state.audio_completo = None
if "livro_nome" not in st.session_state:
    st.session_state.livro_nome = ""

# --- INTERFACE PRINCIPAL ---
uploaded_file = st.file_uploader("Escolhe o ficheiro do livro ou guião", type=["pdf", "epub", "txt"])

if uploaded_file is not None:
    file_bytes = uploaded_file.read()
    extensao = uploaded_file.name.split(".")[-1].lower()
    nome_base = uploaded_file.name.rsplit(".", 1)[0]
    
    if st.session_state.livro_nome != uploaded_file.name:
        st.session_state.livro_nome = uploaded_file.name
        st.session_state.arquivos_partes = []
        st.session_state.audio_completo = None

    with st.spinner("A analisar e a limpar instruções e separadores do guião..."):
        texto_extraido = extrair_documento_universal(file_bytes, extensao)
        todas_as_frases = separar_em_frases(texto_extraido)
        partes_limpas = dividir_partes_base(todas_as_frases, chars_por_parte)
        
    total_partes = len(partes_limpas)
    
    if total_partes == 0 or len(texto_extraido) < 10:
        st.error("❌ Não foi possível extrair texto legível deste ficheiro.")
    else:
        col1, col2, col3 = st.columns(3)
        col1.metric("Total de Caracteres", f"{len(texto_extraido):,}")
        col2.metric("Total de Frases", f"{len(todas_as_frases):,}")
        col3.metric("Partes Calculadas", total_partes)
        
        with st.expander("🔍 Pré-visualizar Texto Limpo (Sem Separadores nem Instruções)"):
            st.write(texto_extraido[:1000] + "...")
        
        st.subheader("🎯 Intervalo a Processar")
        col_inicio, col_fim = st.columns(2)
        parte_inicial = col_inicio.number_input("Começar na Parte", min_value=1, max_value=total_partes, value=1)
        parte_final = col_fim.number_input("Terminar na Parte", min_value=parte_inicial, max_value=total_partes, value=total_partes)
        
        if st.button(f"🚀 Gerar Áudios com {motor_escolhido.split()[0]}", type="primary", use_container_width=True):
            st.session_state.arquivos_partes = []
            st.session_state.audio_completo = None
            
            indices_selecionados = list(range(parte_inicial - 1, parte_final))
            total_selecionadas = len(indices_selecionados)
            
            gerar_partes = modo_geracao in ["Vários Áudios (Por Partes)", "Ambos (Partes + Áudio Completo)"]
            gerar_completo = modo_geracao in ["Áudio Único (Livro Completo)", "Ambos (Partes + Áudio Completo)"]
            
            lista_partes_temp = []
            buffer_completo = io.BytesIO()
            
            status_container = st.empty()
            barra_progresso = st.progress(0)
            
            usar_kokoro = "Kokoro" in motor_escolhido and KOKORO_DISPONIVEL
            
            for step, idx_real in enumerate(indices_selecionados):
                num_parte_humana = idx_real + 1
                status_container.info(f"🔄 A gerar Parte {num_parte_humana} de {parte_final}...")
                barra_progresso.progress((step + 1) / total_selecionadas)
                
                frases_atuais = partes_limpas[idx_real]
                texto_limpo_bloco = " ".join(frases_atuais)
                
                if usar_kokoro:
                    audio_limpo_bytes = gerar_audio_kokoro(texto_limpo_bloco, voice_id)
                    ext_formato = "wav"
                else:
                    audio_limpo_bytes = asyncio.run(gerar_audio_texto_edge(texto_limpo_bloco, voice_id))
                    ext_formato = "mp3"
                
                if gerar_completo and audio_limpo_bytes:
                    buffer_completo.write(audio_limpo_bytes)
                    
                if gerar_partes and audio_limpo_bytes:
                    if idx_real > 0 and frases_repetidas > 0:
                        frases_overlap = partes_limpas[idx_real - 1][-frases_repetidas:]
                        texto_overlap = " ".join(frases_overlap)
                        if usar_kokoro:
                            audio_overlap_bytes = gerar_audio_kokoro(texto_overlap, voice_id)
                        else:
                            audio_overlap_bytes = asyncio.run(gerar_audio_texto_edge(texto_overlap, voice_id))
                        audio_final_parte = audio_overlap_bytes + audio_limpo_bytes
                        primeira_frase_mostrar = frases_overlap[0]
                    else:
                        audio_final_parte = audio_limpo_bytes
                        primeira_frase_mostrar = frases_atuais[0]
                        
                    nome_ficheiro_audio = f"{nome_base}_Parte_{num_parte_humana:02d}.{ext_formato}"
                    lista_partes_temp.append((nome_ficheiro_audio, audio_final_parte, primeira_frase_mostrar, ext_formato))
            
            status_container.empty()
            barra_progresso.empty()
            
            if gerar_partes:
                st.session_state.arquivos_partes = lista_partes_temp
            if gerar_completo:
                nome_completo = f"{nome_base}_Audiolivro_Completo.{ext_formato}"
                st.session_state.audio_completo = (nome_completo, buffer_completo.getvalue(), ext_formato)
                
            st.success("🎉 Processamento concluído com sucesso! Podes ouvir e descarregar abaixo.")

# --- MOSTRAR RESULTADOS GUARDADOS NA SESSÃO ---
if st.session_state.audio_completo or st.session_state.arquivos_partes:
    st.markdown("---")
    st.subheader("📥 Áudios Prontos para Ouvir e Descarregar")
    
    if st.session_state.audio_completo:
        nome_comp, bytes_comp, ext_comp = st.session_state.audio_completo
        mime_tipo = "audio/wav" if ext_comp == "wav" else "audio/mp3"
        with st.container(border=True):
            st.markdown(f"### 🏆 Áudio Único ({ext_comp.upper()})")
            st.audio(bytes_comp, format=mime_tipo)
            st.download_button(
                label=f"📥 Descarregar Áudio Completo ({nome_comp})",
                data=bytes_comp,
                file_name=nome_comp,
                mime=mime_tipo,
                type="primary",
                use_container_width=True,
                key="dl_completo_unico"
            )

    if st.session_state.arquivos_partes:
        st.markdown("### 📚 Áudios Divididos por Partes")
        arquivos_para_zip = []
        
        for idx, (nome_arq, audio_bytes, primeira_frase, ext_arq) in enumerate(st.session_state.arquivos_partes):
            arquivos_para_zip.append((nome_arq, audio_bytes))
            mime_tipo = "audio/wav" if ext_arq == "wav" else "audio/mp3"
            with st.container(border=True):
                st.markdown(f"**🎵 {nome_arq}**")
                st.caption(f"Início: \"{primeira_frase[:100]}...\"")
                st.audio(audio_bytes, format=mime_tipo)
                st.download_button(
                    label=f"📥 Descarregar {nome_arq}",
                    data=audio_bytes,
                    file_name=nome_arq,
                    mime=mime_tipo,
                    key=f"dl_parte_{idx}"
                )
                
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for nome_arq, dados_arq in arquivos_para_zip:
                zip_file.writestr(nome_arq, dados_arq)
            if st.session_state.audio_completo:
                nome_comp, bytes_comp, _ = st.session_state.audio_completo
                zip_file.writestr(nome_comp, bytes_comp)
                
        st.download_button(
            label="📦 Descarregar Tudo num Ficheiro ZIP",
            data=zip_buffer.getvalue(),
            file_name=f"{st.session_state.livro_nome.rsplit('.', 1)[0]}_Pacote_Audiolivro.zip",
            mime="application/zip",
            type="primary",
            use_container_width=True,
            key="dl_zip_total"
        )
