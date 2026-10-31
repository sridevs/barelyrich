import streamlit as st


def show_saved(message: str) -> None:
    st.session_state["portfolio_message"] = message
    st.rerun()
