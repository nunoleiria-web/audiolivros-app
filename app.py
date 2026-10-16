import streamlit as st
import fitz  # PyMuPDF
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
from elevenlabs.client import ElevenLabs
from elevenlabs import VoiceSettings
import io

st.set_page_config(page_title="Gerador de Audiolivros AI", page_icon="🎧", layout="centered")

st.title("🎧 Conversor de Livros para Audiolivro")
st.markdown("Carrega o teu livro em **PDF**, **EPUB** ou **TXT** e converte-o em áudio realista usando a **ElevenLabs**.")

with st.sidebar:
    st.header("⚙️ Configurações")
    default_key = st.secrets.get("ELEVENLABS_API_KEY", "")
    api_key = st.text_input("ElevenLabs API Key", value=default_key, type="password", help="Insere a tua chave da ElevenLabs")
    
    vozes_disponiveis = {
        "George (Narrador Calmo)": "JBFqnCBsd6RMkjVDRZzb",
        "Rachel (Clara e Expressiva)": "21m00Tcm4TlvDq8ikWAM",
        "Adam (Voz Profunda)": "pNInz6obpgDQGcFmaJgB",
        "Bella (Suave / Histórias)": "EXAVITQu4vr4xnSDxMaL"
    }
    voz_selecionada = st.selectbox("Escolhe a Voz", list(vozes_disponiveis.keys()))
    voice_id = vozes_disponiveis[voz_selecionada]
    
    modelo_id = st.selectbox(
        "Modelo de IA",
        ["eleven_multilingual_v2", "eleven_flash_v2_5"]
    )
    
    st.subheader("Ajustes da Voz")
    estabilidade = st.slider("Estabilidade", 0.0, 1.0, 0.65, 0.05)
    similaridade = st.slider("Similaridade", 0.0, 1.0, 0.75, 0.05)
    max_blocos = st.number_input("Limite de blocos a gerar (teste)", min_value=1, max_value=500, value=5)

def extrair_pdf(file_bytes) -> str:
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    texto = []
    for pagina in doc:
        t = pagina.get_text().replace("\n", " ").strip()
        if t:
            texto.append(t)
    return "\n\n".join(texto)

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
    return "\n\n".join(capitulos)

def dividir_em_blocos(texto: str, max_chars: int = 2500) -> list[str]:
    frases = texto.replace("\n\n", " ").split(". ")
    blocos = []
    bloco_atual = ""
    for frase in frases:
        frase_com_ponto = frase.strip() + ". "
        if len(bloco_atual) + len(frase_com_ponto) <= max_chars:
            bloco_atual += frase_com_ponto
        else:
            if bloco_atual:
                blocos.append(bloco_atual.strip())
            bloco_atual = frase_com_ponto
    if bloco_atual:
        blocos.append(bloco_atual.strip())
    return blocos

uploaded_file = st.file_uploader("Escolhe um ficheiro", type=["pdf", "epub", "txt"])

if uploaded_file is not None:
    file_bytes = uploaded_file.read()
    extensao = uploaded_file.name.split(".")[-1].lower()
    
    with st.spinner("A extrair e limpar o texto do livro..."):
        if extensao == "pdf":
            texto_extraido = extrair_pdf(file_bytes)
        elif extensao == "epub":
            texto_extraido = extrair_epub(file_bytes)
        else:
            texto_extraido = file_bytes.decode("utf-8", errors="ignore")
            
    blocos = dividir_em_blocos(texto_extraido)
    
    col1, col2 = st.columns(2)
    col1.metric("Total de Caracteres", f"{len(texto_extraido):,}")
    col2.metric("Blocos de Áudio", len(blocos))
    
    with st.expander("Pré-visualizar Texto Extraído"):
        st.write(texto_extraido[:1000] + "...")

    if st.button("🚀 Gerar Audiolivro", type="primary", use_container_width=True):
        if not api_key:
            st.error("Por favor, insere a tua chave de API da ElevenLabs na barra lateral esquerda.")
        else:
            try:
                client = ElevenLabs(api_key=api_key)
                blocos_para_processar = blocos[:max_blocos]
                
                barra_progresso = st.progress(0, text="A iniciar síntese de voz...")
                buffer_audio = io.BytesIO()
                
                for idx, chunk in enumerate(blocos_para_processar):
                    prev_text = blocos_para_processar[idx - 1][-200:] if idx > 0 else None
                    next_text = blocos_para_processar[idx + 1][:200] if idx < len(blocos_para_processar) - 1 else None
                    
                    audio_stream = client.text_to_speech.convert(
                        voice_id=voice_id,
                        text=chunk,
                        model_id=modelo_id,
                        output_format="mp3_44100_128",
                        previous_text=prev_text,
                        next_text=next_text,
                        voice_settings=VoiceSettings(
                            stability=estabilidade,
                            similarity_boost=similaridade
                        )
                    )
                    
                    for byte_chunk in audio_stream:
                        buffer_audio.write(byte_chunk)
                        
                    progresso = (idx + 1) / len(blocos_para_processar)
                    barra_progresso.progress(progresso, text=f"Bloco {idx + 1} de {len(blocos_para_processar)} concluído...")
                
                st.success("✅ Audiolivro gerado com sucesso!")
                audio_final = buffer_audio.getvalue()
                st.audio(audio_final, format="audio/mp3")
                
                nome_saida = uploaded_file.name.rsplit(".", 1)[0] + "_audiolivro.mp3"
                st.download_button(
                    label="📥 Descarregar MP3",
                    data=audio_final,
                    file_name=nome_saida,
                    mime="audio/mp3",
                    use_container_width=True
                )
            except Exception as e:
                st.error(f"Erro ao comunicar com a ElevenLabs: {e}")
