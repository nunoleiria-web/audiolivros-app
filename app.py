import streamlit as st
import fitz  # PyMuPDF
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
import asyncio
import edge_tts
import io
import re
import zipfile

st.set_page_config(page_title="Gerador de Audiolivros Gratuito", page_icon="🎧", layout="centered")

st.title("🎧 Conversor de Livros para Audiolivro (100% Gratuito)")
st.markdown("Converte o teu livro completo em áudio usando as vozes neurais gratuitas da Microsoft via **Edge-TTS**.")

# --- BARRA LATERAL: CONFIGURAÇÕES ---
with st.sidebar:
    st.header("⚙️ Configurações de Voz")
    
    # Vozes em Português disponíveis no Edge TTS
    vozes_disponiveis = {
        "🇵🇹 Raquel (PT - Natural / Feminina)": "pt-PT-RaquelNeural",
        "🇵🇹 Duarte (PT - Natural / Masculina)": "pt-PT-DuarteNeural",
        "🇧🇷 Francisca (BR - Natural / Feminina)": "pt-BR-FranciscaNeural",
        "🇧🇷 Antonio (BR - Natural / Masculino)": "pt-BR-AntonioNeural"
    }
    
    voz_selecionada = st.selectbox("Escolhe a Voz", list(vozes_disponiveis.keys()))
    voice_id = vozes_disponiveis[voz_selecionada]
    
    st.subheader("Tamanho de cada Áudio")
    chars_por_parte = st.slider(
        "Caracteres por Parte de Áudio",
        min_value=3000,
        max_value=25000,
        value=10000,
        step=1000,
        help="10.000 caracteres equivalem a cerca de 8 a 10 minutos de áudio por ficheiro."
    )
    
    frases_repetidas = st.number_input(
        "Frases a repetir do áudio anterior",
        min_value=1,
        max_value=3,
        value=1,
        help="Quantas frases finais do áudio anterior devem ser repetidas no início do próximo áudio."
    )

# --- FUNÇÕES DE EXTRAÇÃO E DIVISÃO ---
def extrair_pdf(file_bytes) -> str:
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    texto = []
    for pagina in doc:
        t = pagina.get_text().replace("\n", " ").strip()
        if t:
            texto.append(t)
    return " ".join(texto)

def extrair_epub(file_bytes) -> str:
    with open("temp_book.epub", "wb") as f:
        f.write(file_bytes)
    book = epub.read_epub("temp_book.epub")
    capitulos = []
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            soup = BeautifulSoup(item.get_content(), "html.parser")
            texto = soup.get_text(separator=" ").strip()
            if texto:
                capitulos.append(texto)
    return " ".join(capitulos)

def separar_em_frases(texto: str) -> list[str]:
    texto_limpo = re.sub(r'\s+', ' ', texto).strip()
    frases = re.split(r'(?<=[.!?])\s+', texto_limpo)
    return [f.strip() for f in frases if f.strip()]

def criar_partes_com_repeticao(frases: list[str], max_chars_parte: int, num_overlap: int) -> list[list[str]]:
    partes = []
    parte_atual = []
    tamanho_atual = 0
    
    for frase in frases:
        if tamanho_atual + len(frase) + 1 <= max_chars_parte or not parte_atual:
            parte_atual.append(frase)
            tamanho_atual += len(frase) + 1
        else:
            partes.append(parte_atual)
            frases_anteriores = parte_atual[-num_overlap:] if num_overlap > 0 else []
            parte_atual = list(frases_anteriores) + [frase]
            tamanho_atual = sum(len(f) + 1 for f in parte_atual)
            
    if parte_atual:
        partes.append(parte_atual)
        
    return partes

async def gerar_audio_texto(texto: str, voice: str) -> bytes:
    communicate = edge_tts.Communicate(texto, voice)
    mp3_buffer = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            mp3_buffer.write(chunk["data"])
    return mp3_buffer.getvalue()

# --- INTERFACE PRINCIPAL ---
uploaded_file = st.file_uploader("Escolhe o ficheiro do livro", type=["pdf", "epub", "txt"])

if uploaded_file is not None:
    file_bytes = uploaded_file.read()
    extensao = uploaded_file.name.split(".")[-1].lower()
    nome_base = uploaded_file.name.rsplit(".", 1)[0]
    
    with st.spinner("A analisar o livro e preparar as partes..."):
        if extensao == "pdf":
            texto_extraido = extrair_pdf(file_bytes)
        elif extensao == "epub":
            texto_extraido = extrair_epub(file_bytes)
        else:
            texto_extraido = file_bytes.decode("utf-8", errors="ignore")
            
        todas_as_frases = separar_em_frases(texto_extraido)
        partes_do_livro = criar_partes_com_repeticao(todas_as_frases, chars_por_parte, frases_repetidas)
        
    total_partes = len(partes_do_livro)
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Total de Caracteres", f"{len(texto_extraido):,}")
    col2.metric("Total de Frases", f"{len(todas_as_frases):,}")
    col3.metric("Partes de Áudio", total_partes)
    
    st.subheader("🎯 Escolhe as Partes a Gerar")
    col_inicio, col_fim = st.columns(2)
    parte_inicial = col_inicio.number_input("Começar na Parte", min_value=1, max_value=total_partes, value=1)
    parte_final = col_fim.number_input("Terminar na Parte", min_value=parte_inicial, max_value=total_partes, value=total_partes)
    
    if st.button(f"🚀 Gerar Áudios Gratuitos (Parte {parte_inicial} até {parte_final})", type="primary", use_container_width=True):
        arquivos_gerados = []
        progresso_geral = st.progress(0, text="A iniciar conversão gratuita...")
        partes_selecionadas = partes_do_livro[parte_inicial - 1 : parte_final]
        total_selecionadas = len(partes_selecionadas)
        
        for idx_p, frases_parte in enumerate(partes_selecionadas):
            num_parte_real = parte_inicial + idx_p
            progresso_geral.progress(
                idx_p / total_selecionadas,
                text=f"A gerar Parte {num_parte_real} de {parte_final}..."
            )
            
            texto_bloco = " ".join(frases_parte)
            
            # Executar o gerador assíncrono do edge-tts
            audio_bytes = asyncio.run(gerar_audio_texto(texto_bloco, voice_id))
            
            nome_ficheiro_mp3 = f"{nome_base}_Parte_{num_parte_real:02d}.mp3"
            arquivos_gerados.append((nome_ficheiro_mp3, audio_bytes))
            
            with st.container(border=True):
                st.markdown(f"### 🎵 Parte {num_parte_real} de {total_partes}")
                st.caption(f"Começa com: \"{frases_parte[0][:120]}...\"")
                st.audio(audio_bytes, format="audio/mp3")
                st.download_button(
                    label=f"📥 Descarregar Parte {num_parte_real:02d} (MP3)",
                    data=audio_bytes,
                    file_name=nome_ficheiro_mp3,
                    mime="audio/mp3",
                    key=f"dl_{num_parte_real}"
                )
        
        progresso_geral.progress(1.0, text="✅ Geração concluída!")
        st.success("🎉 Todos os áudios gratuitos foram gerados com sucesso!")
        
        if len(arquivos_gerados) > 1:
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                for nome_mp3, dados_mp3 in arquivos_gerados:
                    zip_file.writestr(nome_mp3, dados_mp3)
                    
            st.download_button(
                label="📦 Descarregar TODOS os Áudios num Ficheiro ZIP",
                data=zip_buffer.getvalue(),
                file_name=f"{nome_base}_Audiolivro_Partes_{parte_inicial}_a_{parte_final}.zip",
                mime="application/zip",
                type="primary",
                use_container_width=True
            )
