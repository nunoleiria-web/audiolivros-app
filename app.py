import streamlit as st
import fitz  # PyMuPDF (Lê PDF e EPUB nativamente!)
import asyncio
import edge_tts
import io
import re
import zipfile

st.set_page_config(page_title="Gerador de Audiolivros Gratuito", page_icon="🎧", layout="centered")

st.title("🎧 Conversor de Livros para Audiolivro (100% Gratuito)")
st.markdown("Converte o teu livro em **várias partes**, num **áudio único completo**, ou **ambos** de uma só vez.")

# --- BARRA LATERAL: CONFIGURAÇÕES ---
with st.sidebar:
    st.header("⚙️ Configurações de Voz")
    
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
        help="Define o tamanho das partes (e os blocos de processamento)."
    )
    
    frases_repetidas = st.number_input(
        "Frases a repetir no início de cada Parte",
        min_value=0,
        max_value=3,
        value=1,
        help="Aplica-se apenas aos ficheiros divididos por partes. O áudio completo nunca repete frases a meio."
    )

# --- FUNÇÕES DE EXTRAÇÃO E DIVISÃO ---
def extrair_documento(file_bytes: bytes, extensao: str) -> str:
    """Extrai texto de PDF ou EPUB diretamente em memória usando PyMuPDF."""
    doc = fitz.open(stream=file_bytes, filetype=extensao)
    texto = []
    for pagina in doc:
        t = pagina.get_text("text").replace("\n", " ").strip()
        if t:
            texto.append(t)
    doc.close()
    return " ".join(texto)

def separar_em_frases(texto: str) -> list[str]:
    texto_limpo = re.sub(r'\s+', ' ', texto).strip()
    frases = re.split(r'(?<=[.!?])\s+', texto_limpo)
    return [f.strip() for f in frases if f.strip()]

def dividir_partes_base(frases: list[str], max_chars_parte: int) -> list[list[str]]:
    """Divide o livro em partes limpas (sem repetição)."""
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

async def gerar_audio_texto(texto: str, voice: str) -> bytes:
    if not texto.strip():
        return b""
    communicate = edge_tts.Communicate(texto, voice)
    mp3_buffer = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            mp3_buffer.write(chunk["data"])
    return mp3_buffer.getvalue()

# --- INICIALIZAR MEMÓRIA DA SESSÃO ---
if "arquivos_partes" not in st.session_state:
    st.session_state.arquivos_partes = []
if "audio_completo" not in st.session_state:
    st.session_state.audio_completo = None
if "livro_nome" not in st.session_state:
    st.session_state.livro_nome = ""

# --- INTERFACE PRINCIPAL ---
uploaded_file = st.file_uploader("Escolhe o ficheiro do livro", type=["pdf", "epub", "txt"])

if uploaded_file is not None:
    file_bytes = uploaded_file.read()
    extensao = uploaded_file.name.split(".")[-1].lower()
    nome_base = uploaded_file.name.rsplit(".", 1)[0]
    
    if st.session_state.livro_nome != uploaded_file.name:
        st.session_state.livro_nome = uploaded_file.name
        st.session_state.arquivos_partes = []
        st.session_state.audio_completo = None

    with st.spinner("A analisar o livro e preparar os blocos..."):
        if extensao in ["pdf", "epub"]:
            texto_extraido = extrair_documento(file_bytes, extensao)
        else:
            texto_extraido = file_bytes.decode("utf-8", errors="ignore")
            
        todas_as_frases = separar_em_frases(texto_extraido)
        partes_limpas = dividir_partes_base(todas_as_frases, chars_por_parte)
        
    total_partes = len(partes_limpas)
    
    if total_partes == 0:
        st.warning("Não foi possível encontrar texto legível neste ficheiro.")
    else:
        col1, col2, col3 = st.columns(3)
        col1.metric("Total de Caracteres", f"{len(texto_extraido):,}")
        col2.metric("Total de Frases", f"{len(todas_as_frases):,}")
        col3.metric("Partes Calculadas", total_partes)
        
        st.subheader("🎯 Intervalo a Processar")
        col_inicio, col_fim = st.columns(2)
        parte_inicial = col_inicio.number_input("Começar na Parte", min_value=1, max_value=total_partes, value=1)
        parte_final = col_fim.number_input("Terminar na Parte", min_value=parte_inicial, max_value=total_partes, value=total_partes)
        
        if st.button(f"🚀 Gerar ({modo_geracao})", type="primary", use_container_width=True):
            st.session_state.arquivos_partes = []
            st.session_state.audio_completo = None
            
            progresso_geral = st.progress(0, text="A iniciar síntese de voz...")
            indices_selecionados = list(range(parte_inicial - 1, parte_final))
            total_selecionadas = len(indices_selecionados)
            
            gerar_partes = modo_geracao in ["Vários Áudios (Por Partes)", "Ambos (Partes + Áudio Completo)"]
            gerar_completo = modo_geracao in ["Áudio Único (Livro Completo)", "Ambos (Partes + Áudio Completo)"]
            
            lista_partes_temp = []
            buffer_completo = io.BytesIO()
            
            for step, idx_real in enumerate(indices_selecionados):
                num_parte_humana = idx_real + 1
                progresso_geral.progress(
                    step / total_selecionadas,
                    text=f"A processar bloco {num_parte_humana} de {parte_final}..."
                )
                
                frases_atuais = partes_limpas[idx_real]
                texto_limpo_bloco = " ".join(frases_atuais)
                
                # 1. Gerar o áudio base da parte (sem repetição)
                audio_limpo_bytes = asyncio.run(gerar_audio_texto(texto_limpo_bloco, voice_id))
                
                # Se precisarmos do áudio completo, junta apenas o áudio limpo (sem repetições)
                if gerar_completo:
                    buffer_completo.write(audio_limpo_bytes)
                    
                # Se precisarmos das partes individuais, adiciona o áudio das frases repetidas da parte anterior
                if gerar_partes:
                    if idx_real > 0 and frases_repetidas > 0:
                        frases_overlap = partes_limpas[idx_real - 1][-frases_repetidas:]
                        texto_overlap = " ".join(frases_overlap)
                        audio_overlap_bytes = asyncio.run(gerar_audio_texto(texto_overlap, voice_id))
                        audio_final_parte = audio_overlap_bytes + audio_limpo_bytes
                        primeira_frase_mostrar = frases_overlap[0]
                    else:
                        audio_final_parte = audio_limpo_bytes
                        primeira_frase_mostrar = frases_atuais[0]
                        
                    nome_ficheiro_mp3 = f"{nome_base}_Parte_{num_parte_humana:02d}.mp3"
                    lista_partes_temp.append((nome_ficheiro_mp3, audio_final_parte, primeira_frase_mostrar))
                    
            if gerar_partes:
                st.session_state.arquivos_partes = lista_partes_temp
            if gerar_completo:
                nome_completo = f"{nome_base}_Audiolivro_Completo.mp3"
                st.session_state.audio_completo = (nome_completo, buffer_completo.getvalue())
                
            progresso_geral.progress(1.0, text="✅ Processamento concluído!")
            st.success("🎉 Os teus áudios foram gerados e guardados na sessão!")

# --- MOSTRAR RESULTADOS GUARDADOS NA SESSÃO ---
if st.session_state.audio_completo or st.session_state.arquivos_partes:
    st.markdown("---")
    st.subheader("📥 Os Teus Áudios Prontos")
    
    # 1. Secção do Áudio Único Completo
    if st.session_state.audio_completo:
        nome_comp, bytes_comp = st.session_state.audio_completo
        with st.container(border=True):
            st.markdown("### 🏆 Áudio Único (Livro Completo)")
            st.caption("Leitura contínua sem repetição de frases entre blocos.")
            st.audio(bytes_comp, format="audio/mp3")
            st.download_button(
                label=f"📥 Descarregar Áudio Completo ({nome_comp})",
                data=bytes_comp,
                file_name=nome_comp,
                mime="audio/mp3",
                type="primary",
                use_container_width=True,
                key="dl_completo_unico"
            )

    # 2. Secção dos Vários Áudios (Por Partes)
    if st.session_state.arquivos_partes:
        st.markdown("### 📚 Áudios Divididos por Partes")
        arquivos_para_zip = []
        
        for idx, (nome_mp3, audio_bytes, primeira_frase) in enumerate(st.session_state.arquivos_partes):
            arquivos_para_zip.append((nome_mp3, audio_bytes))
            with st.container(border=True):
                st.markdown(f"**🎵 {nome_mp3}**")
                st.caption(f"Começa com: \"{primeira_frase[:120]}...\"")
                st.audio(audio_bytes, format="audio/mp3")
                st.download_button(
                    label=f"📥 Descarregar {nome_mp3}",
                    data=audio_bytes,
                    file_name=nome_mp3,
                    mime="audio/mp3",
                    key=f"dl_parte_{idx}"
                )
                
        # Botão para descarregar tudo num único ZIP
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for nome_mp3, dados_mp3 in arquivos_para_zip:
                zip_file.writestr(nome_mp3, dados_mp3)
            if st.session_state.audio_completo:
                nome_comp, bytes_comp = st.session_state.audio_completo
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
