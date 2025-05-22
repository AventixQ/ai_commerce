import streamlit as st
import os

st.set_page_config(
    page_title="Site analysis",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("Welcome to e-commerce analysis")
st.markdown("---")

st.subheader("Pick type of analysis:")

path_analizator_llm_only = "pages/App_interface_with_LLM.py"
path_analizator_scrap_llm = "pages/App_interface_with_Scraping_and_LLM.py"

col1, col2 = st.columns(2)

with col1:
    if os.path.exists(path_analizator_llm_only):
        st.page_link(
            path_analizator_llm_only,
            label="Analizator LLM Only",
            icon="🧠",
            use_container_width=True
        )
        st.caption("Analysis using given text and LLM")
    else:
        st.error(f"File not found: {path_analizator_llm_only}")

with col2:
    if os.path.exists(path_analizator_scrap_llm):
        st.page_link(
            path_analizator_scrap_llm,
            label="Analizator with scraping and LLM",
            icon="⚙️",
            use_container_width=True
        )
        st.caption("Basic analysis using scraping and LLMs.")
    else:
        st.error(f"File not found: {path_analizator_scrap_llm}")

st.markdown("---")