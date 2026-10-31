import logging

import streamlit as st

from src import config
from src.repo.db import initialise
from src.ui.dashboard import render_portfolio

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("src").setLevel(logging.INFO)

DATA = config.data_directory()
st.set_page_config(
    page_title=config.PAGE_TITLE, page_icon=config.PAGE_ICON, layout=config.PAGE_LAYOUT,
)
db_path = DATA / config.PORTFOLIO_DATABASE
initialise(db_path)
render_portfolio(db_path)
