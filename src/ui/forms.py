import streamlit as st
from streamlit.typing import UploadedFile

from src import config
from src.inference.ollama_runtime import (
    OllamaRuntime,
    OllamaRuntimeConfig,
    OllamaRuntimeError,
)
from src.service.entry_services import EntryServices
from src.service.portfolio import PortfolioActions
from src.ui import ui_text
from src.ui.state import StatementReviewSession
from src.ui.statement_batch import StatementBatchSession
from src.ui.statement_import import StatementImport
from src.ui.valuations import render_manual_valuation

_SELECTED_CARD = "wealth_card_selected"
_SELECTION_KEY = "wealth_entry"
_SELECTED_CARD_STYLE = f"""
    <style>
    .st-key-{_SELECTED_CARD} {{
        background: rgba(34, 197, 94, 0.10);
        border: 2px solid #15803d;
        border-radius: 0.75rem;
    }}
    </style>
"""


@st.cache_data(ttl=30)
def _installed_ollama_models() -> tuple[str, ...]:
    return OllamaRuntime.list_models()


def _default_ollama_model(models: tuple[str, ...]) -> str:
    default_name = OllamaRuntimeConfig.from_environment().model_name
    if default_name in models:
        return default_name
    return models[0]


def _render_ollama_model_selector() -> str | None:
    st.caption(ui_text.OLLAMA_MODEL_HELP)
    try:
        models = _installed_ollama_models()
    except OllamaRuntimeError as error:
        st.error(str(error))
        return None
    if not models:
        st.error(ui_text.OLLAMA_NO_MODELS)
        return None
    return st.selectbox(
        ui_text.OLLAMA_MODEL, models, index=models.index(_default_ollama_model(models)),
        key="statement_ollama_model",
    )


def _select_statement_model(services: EntryServices) -> tuple[EntryServices, bool]:
    model_name = _render_ollama_model_selector()
    if not model_name:
        return services, False
    return services.with_ollama_model(model_name), True


def render_statement_import(actions: PortfolioActions, services: EntryServices) -> None:
    review_session = StatementReviewSession(st.session_state)
    with st.container(border=True):
        st.subheader(ui_text.PARSE_WITH_AI)
        st.caption(ui_text.statement_guidance())
        kind, uploads, log_model_output = _render_statement_inputs(review_session)
        selected_services, ready = _select_statement_model(services)
        StatementImport(
            actions, selected_services, kind, uploads, log_model_output,
            StatementBatchSession(st.session_state),
        ).render(ready=ready)


def _render_statement_inputs(
    review_session: StatementReviewSession,
) -> tuple[str, list[UploadedFile], bool]:
    kind = st.selectbox(
        ui_text.ASSET_TYPE, ["asset", "liability"], key="statement_kind",
        help=ui_text.ASSET_TYPE_HELP,
    )
    upload = st.file_uploader(
        ui_text.statement_upload_label(),
        type=["pdf", "csv"], accept_multiple_files=True,
        key=f"statement_upload_{review_session.upload_revision}",
        max_upload_size=config.STATEMENT_UPLOAD_MB,
    )
    uploads = upload if isinstance(upload, list) else [upload] if upload else []
    debug = st.checkbox(
        ui_text.DEBUG_OUTPUT, value=False, key="statement_debug_output", help=ui_text.DEBUG_OUTPUT_HELP,
    )
    return kind, uploads, debug


def render_account_forms(actions: PortfolioActions, services: EntryServices | None = None) -> None:
    services = services or EntryServices()
    st.subheader(ui_text.DATA_ENTRY)
    selected = st.session_state.setdefault(_SELECTION_KEY, "Parse statement")
    st.html(_SELECTED_CARD_STYLE)
    for column, workflow in zip(st.columns(2), _workflows()):
        with column:
            _render_workflow_card(workflow, selected)
    if selected == "Manual valuation":
        render_manual_valuation(actions)
    else:
        render_statement_import(actions, services)


def _workflows() -> tuple[tuple[str, str, str, str], ...]:
    return (
        ("Parse statement", ui_text.PARSE_STATEMENT, ui_text.ACCOUNT_BALANCES, ui_text.STATEMENT_DESCRIPTION),
        ("Manual valuation", ui_text.MANUAL_VALUATION, ui_text.OTHER_ASSETS, ui_text.VALUATION_DESCRIPTION),
    )


def _render_workflow_card(workflow: tuple[str, str, str, str], selected: str) -> None:
    identity, label, caption, description = workflow
    with st.container(
        border=True, height="stretch",
        key=_SELECTED_CARD if selected == identity else f"wealth_card_{identity}",
    ):
        st.caption(caption)
        st.markdown(f"### {label}")
        st.write(description)
        st.caption(ui_text.SELECTED if selected == identity else ui_text.CHOOSE_WORKFLOW)
        st.button(
            label, key=f"choose_{identity}", width="stretch",
            type="primary",
            on_click=st.session_state.update, args=({_SELECTION_KEY: identity},),
        )
