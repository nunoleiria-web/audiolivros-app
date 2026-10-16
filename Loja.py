import streamlit as st

st.set_page_config(page_title="Loja — O Arquiteto de Sim Mesmo", page_icon="📚", layout="centered")

st.title("📚 O Arquiteto de Sim Mesmo")
st.markdown("### Transforme a sua estrutura interna. Adquira o livro e o audiolivro oficial.")

st.markdown("---")

# Layout de duas colunas para os produtos
col1, col2 = st.columns(2)

with col1:
    st.image("https://images.unsplash.com/photo-1544716278-ca5e3f4abd8c?w=400&q=80", use_column_width=True)
    st.subheader("📖 Livro Digital (EPUB)")
    st.markdown("""
    * Leitura imediata em qualquer e-reader, telemóvel ou tablet.
    * Inclui todos os capítulos, ferramentas práticas e reflexões.
    """)
    st.markdown("**Preço:** 9,99 €")
    
    # Botão de compra / download (podes integrar o teu link de pagamento do Stripe, PayPal, etc.)
    if st.button("Comprar EPUB", type="primary", key="btn_epub"):
        st.success("Redirecionando para o pagamento...")
        # st.switch_page ou link externo de pagamento

with col2:
    st.image("https://images.unsplash.com/photo-1590602847861-f357a9332bbc?w=400&q=80", use_column_width=True)
    st.subheader("🎧 Audiolivro Completo (MP3)")
    st.markdown("""
    * Formato profissional em alta qualidade (Estéreo).
    * Dividido por capítulos limpos para ouvir no carro, a caminhar ou em casa.
    """)
    st.markdown("**Preço:** 14,99 €")
    
    if st.button("Comprar Audiolivro", type="primary", key="btn_audio"):
        st.success("Redirecionando para o pagamento...")

st.markdown("---")

# Secção de Amostra de Áudio
st.subheader("🎧 Ouviu uma amostra gratuita")
st.markdown("Experimente a voz oficial do narrador antes de adquirir o audiolivro completo:")

# Podes colocar aqui um ficheiro MP3 de amostra que tenhas no teu repositório
# st.audio("amostra_capitulo1.mp3", format="audio/mp3")

st.markdown("---")

# Secção de FAQ / Ajuda
with st.expander("❓ Perguntas Frequentes"):
    st.markdown("""
    * **Como recebo os produtos após a compra?** 
      Receberá um link de acesso imediato por e-mail para descarregar o ficheiro EPUB e o arquivo ZIP com o audiolivro.
    * **Em que dispositivos posso ouvir o audiolivro?** 
      Os ficheiros estão em formato MP3 universal, compatível com telemóveis, computadores e leitores de música.
    """)

st.markdown("---")
st.caption("© 2026 O Arquiteto de Sim Mesmo. Todos os direitos reservados.")
